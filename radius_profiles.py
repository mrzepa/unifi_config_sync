import json
from dotenv import load_dotenv
import os
import sys
import logging
import warnings
import requests
from icecream import ic
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning
from utils import process_single_controller, save_dicts_to_json, read_json_file
from config import RADIUS_SERVERS
from unifi.unifi import Unifi
import config
import utils
from utils import setup_logging, get_filtered_files, get_valid_names_from_dir, validate_names

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

logger = logging.getLogger(__name__)

def get_templates_from_base_site(unifi, site_name: str, context: dict):
    """
    Fetches and processes network configuration templates from a specified base site.

    This function retrieves all network configuration items from the specified
    site of the UniFi controller, filters the items based on provided inclusion
    or exclusion criteria, and saves the resulting items into JSON files within
    a specified directory. The filtering logic operates based on `include_names`
    or `exclude_names` specified in the context. The resulting configuration
    data are prepared for further use by removing non-essential fields such as
    `site_id` and `_id`.

    :param unifi: Controller instance used to interact with the UniFi API.
    :type unifi: object
    :param site_name: Name of the site to retrieve configuration templates from.
    :type site_name: str
    :param context: Dictionary containing additional parameters. Keys include
                    'endpoint_dir' (directory for saving), 'include_names' (list
                    of names to include), and 'exclude_names' (list of names to
                    exclude).
    :type context: dict
    :return: Indicates whether the operation completed successfully.
    :rtype: bool
    """
    endpoint_dir = context.get("endpoint_dir")
    include_names = context.get("include_names_list", None)
    exclude_names = context.get("exclude_names_list", None)
    ui_site = unifi.sites[site_name]
    ui_site.output_dir = endpoint_dir

    logger.debug(f'Searching for base site {site_name} on controller {unifi.base_url}')
    # get the list of items for the site
    all_items = ui_site.radius_profile.all()
    item_list = []

    for item in all_items:
        del item['site_id']
        del item['_id']
        if include_names:
            # Only fetch items that have been requested
            if item.get('name') in include_names:
                item_list.append(item)
        elif exclude_names:
            if item.get('name') not in exclude_names:
                continue
        else:
            # Fetch all item profiles
            item_list.append(item)
    logger.info(f'Saving {len(item_list)} Radius Profiles in directory {ui_site.output_dir}.')
    save_dicts_to_json(item_list, ui_site.output_dir)
    return True

def delete_item_from_site(unifi, site_name: str, context: dict):
    """
    Deletes items from a specified site in the UniFi Controller based on the provided
    context. The method allows deletion of specific network configurations from the
    site and includes functionality to back up items before deletion.

    :param unifi: Instance of the UniFi API client to interact with the UniFi Controller.
    :param site_name: Name of the site where the items will be deleted.
    :param context: A dictionary containing configuration for the deletion process.
        - endpoint_dir: The directory of the API endpoint to be used.
        - include_names: A list of item names to be deleted.
        - exclude_names: An optional list of item names to be excluded from deletion.
    :return: None
    """
    ENDPOINT = context.get("endpoint")
    include_names = context.get("include_names_list")
    ui_site = unifi.sites[site_name]

    for name in include_names:
        item_id = ui_site.radius_profile.get_id(name=name)
        if item_id:
            logger.info(f"Deleting {ENDPOINT} '{name}' from site '{site_name}'")
            item_to_backup = ui_site.radius_profile.get(_id=item_id)
            item_to_backup.backup(config.BACKUP_DIR)
            response = ui_site.radius_profile.delete(item_id)
            if response:
                logger.info(f"Successfully deleted {ENDPOINT} '{name}' from site '{site_name}'")
            else:
                logger.error(f"Failed to delete {obj_class} '{name}' from site '{site_name}': {response}")
        else:
            logger.warning(f"{obj_class} '{name}' does not exist on site '{site_name}', skipping deletion.")


def add_item_to_site(unifi, site_name: str, context: dict):
    """
    Adds configurations from specified files to a site's endpoint directory in the UniFi system. The
    function first validates the existence of the provided directory, fetches the existing
    configurations from the site, and selectively processes the files based on filtering
    rules. If the configuration from a file already exists in the site, the function skips
    uploading it. Otherwise, it uploads the new configuration and logs the success or failure
    of the operation. Errors such as invalid JSON or file processing issues are logged
    appropriately.

    :param unifi: The UniFi system object used to interact with sites and configurations.
    :param site_name: The name of the UniFi site where configurations are to be added.
    :type site_name: str
    :param context: A dictionary containing the context of the operation, which includes:
        - **endpoint_dir** (*str*): Path to the directory containing JSON configuration files.
        - **include_names** (*list*, optional): List of file names to include during processing.
        - **exclude_names** (*list*, optional): List of file names to exclude during processing.
        Defaults to None for both optional filters.
    :type context: dict
    :return: None
    """
    ENDPOINT = context.get("endpoint")
    endpoint_dir = context.get("endpoint_dir")
    include_names = context.get("include_names_list", None)
    exclude_names = context.get("exclude_names_list", None)
    ui_site = unifi.sites[site_name]

    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")

    # Fetch existing port configurations from the site
    try:
        logger.debug(f"Fetching existing {ENDPOINT} from site '{site_name}'")
        existing_items = ui_site.radius_profile.all()
        existing_item_names = {vlan.get("name") for vlan in existing_items}
        logger.debug(f"Existing {ENDPOINT}: {existing_item_names}")
    except Exception as e:
        logger.error(f"Failed to fetch existing {ENDPOINT} from site '{site_name}': {e}")
        raise

    # Get files to process from the directory
    files = get_filtered_files(endpoint_dir, include_names, exclude_names)

    # Process selected files
    for file_path in files:
        file_name = os.path.basename(file_path)
        try:
            logger.debug(f"Reading {ENDPOINT} from file: {file_path}")
            new_item = read_json_file(file_path)
            item_name = new_item.get("name")

            # Add in the radius server secret
            for idx, server in enumerate(new_item.get('auth_servers', [])):
                ip = server.get('ip')
                if ip in RADIUS_SERVERS:
                    # Update 'x_secret' in the current server dictionary
                    new_item['auth_servers'][idx]['x_secret'] = RADIUS_SERVERS[ip]

            # Check if the item name already exists
            if item_name in existing_item_names:
                logger.info(f'Radius profile {item_name} already exists at site. Replacing the configuraiton.')
                item_to_delete = existing_item_map[item_name]
                item_id = item_to_delete.get("_id")
                if item_id:
                    item_to_backup = ui_site.radius_profile.get(_id=item_id)
                    item_to_backup.backup(config.BACKUP_DIR)
                    delete_response = ui_site.radius_profile.delete(item_id)

            # Make the request to add the item
            logger.debug(f"Uploading {ENDPOINT} '{item_name}' to site '{site_name}'")
            response = ui_site.radius_profile.create(new_item)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.exception(f"Error processing file '{file_name}': {e}")

def replace_item_at_site(unifi, site_name: str, context: dict):
    """
    Replaces or updates items at a specific site in the UniFi framework using
    provided configurations. The function performs operations to ensure the
    consistency and accuracy of VLAN configurations. It reads JSON configuration
    files from the specified directory, processes them, and applies the updates
    to the provided UniFi site while replacing any existing configurations that
    correspond to the same name.

    This function ensures backup of existing configurations, removal of stale
    items, and upload of new configurations.

    :param unifi: The UniFi API client instance used to interact with the UniFi framework.
    :param site_name: The name of the site where items are to be replaced or updated.
    :type site_name: str
    :param context: A dictionary containing additional information for processing:
        - `endpoint_dir` (str): Directory containing configuration files.
        - `include_names` (list of str): List of file names to include.
        - `exclude_names` (list of str, optional): List of file names to exclude.
    :type context: dict
    :return: None
    """
    ENDPOINT = context.get("endpoint")
    endpoint_dir = context.get("endpoint_dir")
    include_names = context.get("include_names_list")
    exclude_names = context.get("exclude_names_list", None)
    ui_site = unifi.sites[site_name]

    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")

    # Fetch existing port configurations from the site
    try:
        logger.debug(f"Fetching existing {ENDPOINT} for site '{site_name}'")
        existing_items = ui_site.radius_profile.all()
        existing_item_map = {item.get("name"): item for item in existing_items}
        logger.debug(f"Existing {ENDPOINT}: {list(existing_item_map.keys())}")
    except Exception as e:
        logger.error(f"Failed to fetch existing {ENDPOINT} for site '{site_name}': {e}")
        raise

    # Get files to process from the items directory
    files = get_filtered_files(endpoint_dir, include_names, exclude_names)
    # Process selected files
    for file_path in files:
        file_name = os.path.basename(file_path)
        try:
            logger.debug(f"Reading {ENDPOINT} from file: {file_path}")
            new_item = read_json_file(file_path)
            item_name = new_item.get("name")

            # Check if the profile name exists and delete it using its _id
            if item_name in existing_item_map:
                item_to_delete = existing_item_map[item_name]
                item_id = item_to_delete.get("_id")
                if item_id:
                    item_to_backup = ui_site.radius_profile.get(_id=item_id)
                    item_to_backup.backup(config.BACKUP_DIR)
                    delete_response = ui_site.radius_profile.delete(item_id)
                    if not delete_response:
                        continue
                else:
                    logger.error(f"Vlan '{item_name}' exists but its '_id' is missing. Skipping delete.")
                    continue
            # Make the request to add the item config
            logger.debug(f"Uploading {ENDPOINT} '{item_name}' to site '{site_name}'")
            response = ui_site.radius_profile.create(new_item)
            if response:
                logger.info(f"Successfully created {ENDPOINT} '{item_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to create {ENDPOINT} {item_name}: {response}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.exception(f"Error processing file '{file_name}': {e}")


if __name__ == "__main__":
    env_path = os.path.join(os.path.expanduser("~"), ".env")
    load_dotenv()
    ENDPOINT = 'Radius Profiles'
    parser = argparse.ArgumentParser(description=f"{ENDPOINT} Management Script")

    # Add the verbose flag
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output (debug level logging)"
    )

    # Create mutually exclusive group for -g/--get, -a/--add, -r/--replace, -d/--delete
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-g", "--get",
        action="store_true",
        help=f"Get {ENDPOINT}."
    )
    group.add_argument(
        "-a", "--add",
        action="store_true",
        help=f"Add {ENDPOINT}."
    )
    group.add_argument("-r", "--replace",
                       action="store_true",
                       help=f"Replace {ENDPOINT}.")

    group.add_argument("-d", "--delete",
                       action="store_true",
                       help=f"Delete {ENDPOINT}.")

    inex = parser.add_mutually_exclusive_group(required=False)
    inex.add_argument(
        "--include-names",
        nargs="*",
        default=[],  # Default to an empty list
        help="List of names to include"
    )

    inex.add_argument(
        "--exclude-names",
        nargs="*",
        default=[],
        help="List of names to exclude"
    )

    parser.add_argument(
        "--site-names-file",
        type=str,
        default='sites.txt',
        help='File containing a list of site names to apply changes to.'
    )
    parser.add_argument(
        "--base-site-name",
        type=str,
        default='Default',
        help='Name of the base site to get configuraitons from.'
    )
    # Parse the arguments
    args = parser.parse_args()

    # Set up logging based on the verbose flag
    if args.verbose:
        setup_logging(logging.DEBUG)
    else:
        setup_logging(logging.INFO)

    # Read in the environment variables
    try:
        ui_username = os.getenv("UI_USERNAME")
        ui_password = os.getenv("UI_PASSWORD")
        ui_mfa_secret = os.getenv("UI_MFA_SECRET")

    except KeyError as e:
        logger.critical("Unifi username or password is missing from environment variables.")
        raise SystemExit(1)

    # get the list of controllers
    controller_list = config.CONTROLLERS
    logger.info(f'Found {len(controller_list)} controllers.')

    # Get the directory for storing the items
    endpoint_dir = os.path.splitext(os.path.basename(__file__))[0]
    if os.path.exists(endpoint_dir):
        valid_names = get_valid_names_from_dir(endpoint_dir)
    else:
        valid_names = []

    # Get the site name(s) to apply changes too
    ui_name_filename = args.site_names_file
    ui_name_path = os.path.join(config.INPUT_DIR, ui_name_filename)
    with open(ui_name_path, 'r') as f:
        site_names = [line.strip() for line in f if line.strip()]

    MAX_CONTROLLER_THREADS = config.MAX_CONTROLLER_THREADS

    process_fucntion = None
    include_names_list = None
    exclude_name_list = None

    if args.get:
        logging.info(f"Option selected: Get {ENDPOINT}")
        process_fucntion = get_templates_from_base_site
        # Can't validate the include/exclude names since we don't know what they are until after they are retrieved.
        site_names = [args.base_site_name]

    elif args.add:
        logging.info(f"Option selected: Add {ENDPOINT}")
        process_fucntion = add_item_to_site

        if not valid_names:
            raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist. Please run with -g/--get first")

        if args.include_names:
            if not validate_names(args.include_names, valid_names, 'include-names'):
                sys.exit(1)
        if args.exclude_names:
            if not validate_names(args.exclude_names, valid_names, 'exclude-names'):
                sys.exit(1)

    elif args.replace:
        logging.info(f"Option selected: Replace {ENDPOINT}")

        if not args.include_names:
            logger.error(f"--replace requires a list of {ENDPOINT} names to replace using --include-names.")
            sys.exit(1)

        if not valid_names:
            raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist. Please run with -g/--get first")

        if validate_names(args.include_names, valid_names, 'include-names'):
            # Log the items to be replaced
            logging.info(f"{ENDPOINT} names to be replaced: {args.include_names}")
        else:
            sys.exit(1)
        process_fucntion = replace_item_at_site

    elif args.delete:
        logging.info(f"Option selected: Delete {ENDPOINT}")
        if not args.include_names:
            logger.error(f"--delete requires a list of {ENDPOINT} names to delete using --include-names.")
            sys.exit(1)

        if not valid_names:
            raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist. Please run with -g/--get first")

        if validate_names(args.include_names, valid_names, 'include-names'):
            logging.info(f"{ENDPOINT} names to be deleted: {args.include_names}")
        else:
            sys.exit(1)
        process_fucntion = delete_item_from_site

    if process_fucntion:
        context = {'process_function': process_fucntion,
                   'site_names': site_names,
                   'endpoint_dir': endpoint_dir,
                   'include_names_list': args.include_names,
                   'exclude_name_list': args.exclude_names, }
        # Use concurrent.futures to handle multithreading
        with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
            # Submit each controller to the thread pool for processing
            future_to_controller = {executor.submit(process_single_controller, controller,
                                                    context,
                                                    ui_username,
                                                    ui_password,
                                                    ui_mfa_secret): controller for controller in
                                    controller_list}

            # Wait for all controller-processing threads to complete
            for future in as_completed(future_to_controller):
                try:
                    future.result()
                except Exception as e:
                    # Handle exceptions for individual tasks
                    logger.exception(e)
                    continue
