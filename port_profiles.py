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
from utils import (process_single_controller, save_dicts_to_json, read_json_file,
                 get_valid_names_from_dir, validate_names)
from unifi.unifi import Unifi
import config
import utils
from utils import setup_logging, get_filtered_files

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

logger = logging.getLogger(__name__)


def get_templates_from_base_site(unifi, site_name: str, context: dict):
    """
    Retrieves and processes templates/items from a specific site on a UniFi controller
    and saves the resulting item list after filtering based on include or exclude terms.

    This function interacts with the UniFi API to access data specific to a given
    site and processes the data based on the parameters provided. The filtered
    results are serialized into JSON format and saved locally.

    :param unifi: Instance of a UniFi controller to connect and retrieve data from.
    :param site_name: Name of the site to retrieve items from.
    :param context: A dictionary containing configuration for the deletion process.
        - endpoint_dir: The directory of the API endpoint to be used.
        - include_names: A list of item names to be deleted.
        - exclude_names: An optional list of item names to be excluded from deletion.
    :return: Returns a boolean indicating the success of the operation.
    :rtype: bool
    """

    endpoint_dir = context.get("endpoint_dir")
    include_names = context.get("include_names_list", None)
    exclude_names = context.get("exclude_names_list", None)
    ui_site = unifi.sites[site_name]
    ui_site.output_dir = endpoint_dir
    logger.debug(f'Searching for base site {site_name} on controller {unifi.base_url}')

    site_data_filename = os.path.join(config.SITE_DATA_DIR, config.SITE_DATA_FILE)
    with open(site_data_filename, 'r') as f:
        all_site_data = json.load(f)

    site_data = all_site_data.get(site_name)
    vlans = site_data.get("vlans")

    # get the list of items for the site
    all_items = ui_site.port_conf.all()
    item_list = []

    for item in all_items:
        if not include_names or any(value in include_names for key, value in item.items()):
            # Copy the dictionary and remove unwanted keys in the process
            filtered_item = item.copy()  # Create a copy of the original `item` dictionary

            # Remove unnecessary keys in the copy
            filtered_item.pop('site_id', None)
            filtered_item.pop('_id', None)

            # Add native_networkconf_id name if available
            if 'native_networkconf_id' in item:
                native_networkconf_id = item.get('native_networkconf_id')
                name = next((name for name, id_ in vlans.items() if id_ == native_networkconf_id), None)
                if name:
                    filtered_item['native_networkconf_vlan_name'] = name

            # Add voice_networkconf_id name if available
            if 'voice_networkconf_id' in item:
                voice_networkconf_id = item.get('voice_networkconf_id')
                name = next((name for name, id_ in vlans.items() if id_ == voice_networkconf_id),
                            None)
                if name:
                    filtered_item['voice_networkconf_vlan_name'] = name

            # Add excluded_networkconf_ids name if available
            if 'excluded_networkconf_ids' in item:
                excluded_networkconf_ids = item.get('excluded_networkconf_ids')
                name = next((name for name, id_ in vlans.items() if id_ == excluded_networkconf_ids),
                            None)
                if name:
                    filtered_item['excluded_networkconf_vlan_names'] = name

            # Append the modified copy to your item_list
            item_list.append(filtered_item)

    logger.info(f'Saving {len(item_list)} Port Profiles to {ui_site.output_dir}.')
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
        item_id = ui_site.port_conf.get_id(name=name)
        if item_id:
            logger.info(f"Deleting {ENDPOINT} '{name}' from site '{site_name}'")
            item_to_backup = ui_site.port_conf.get(_id=item_id)
            item_to_backup.backup(config.BACKUP_DIR)
            response = ui_site.port_conf.delete(item_id)
            if response:
                logger.info(f"Successfully deleted {ENDPOINT} '{name}' from site '{site_name}'")
            else:
                logger.error(f"Failed to delete {obj_class} '{name}' from site '{site_name}': {response}")
        else:
            logger.warning(f"{obj_class} '{name}' does not exist on site '{site_name}', skipping deletion.")

def add_item_to_site(unifi: Unifi, site_name: str, context: dict):
    """
    Adds items to a specific site in the Unifi Controller by processing JSON files in a designated
    directory. Validates the existence of the target directory, reads configuration files, checks
    for existing objects, updates items with site-specific VLAN IDs, and uploads them to the
    Unifi Controller. Logs detailed information for each step.

    :param unifi: The Unifi object to interact with the Unifi Controller.
    :param site_name: Name of the site in the Unifi Controller where items will be added.
    :param context: A dictionary containing configuration for the deletion process.
        - endpoint_dir: The directory of the API endpoint to be used.
        - include_names: A list of item names to be deleted.
        - exclude_names: An optional list of item names to be excluded from deletion.
    :return: None
    :raises ValueError: If the specified directory does not exist.
    :raises Exception: For failures in retrieving or uploading data from/to the Unifi Controller.
    """
    endpoint_dir = context.get("endpoint_dir")
    ENDPOINT = context.get("endpoint")
    include_names = context.get("include_names_list", None)
    exclude_names = context.get("exclude_names_list", None)
    ui_site = unifi.sites[site_name]

    site_data_filename = os.path.join(config.SITE_DATA_DIR, config.SITE_DATA_FILE)
    with open(site_data_filename, 'r') as f:
        all_site_data = json.load(f)

    site_data = all_site_data.get(site_name)
    vlans = site_data.get("vlans")

    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        logger.error(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")
        raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")

    try:
        logger.debug(f"Fetching existing {ENDPOINT} from site '{site_name}'")
        existing_items = ui_site.port_conf.all()
        existing_item_names = {item.get("name") for item in existing_items}
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
            new_items = read_json_file(file_path)
            item_name = new_items.get("name")

            # Check if the item name already exists
            if item_name in existing_item_names:
                logger.warning(f"{ENDPOINT} '{item_name}' already exists on site '{site_name}', skipping upload.")
                continue

            # modify the item for site specific vlan IDs
            for key, value in new_items.items():
                if key == "native_networkconf_id" and new_items['native_networkconf_id']:
                    new_items[key] = vlans[new_items['native_networkconf_vlan_name']]

                if key == "voice_networkconf_id" and new_items['voice_networkconf_id']:
                    new_items[key] = vlans[new_items['voice_networkconf_vlan_name']]

                if key == "excluded_networkconf_ids":
                    excluded_vlan_names = new_items.get("excluded_networkconf_vlan_names", None)

                    if excluded_vlan_names and isinstance(excluded_vlan_names, list):
                        # Build the list using the 'vlans' dictionary
                        new_items[key] = [vlans[vlan_name] for vlan_name in excluded_vlan_names if vlan_name in vlans]

            # Make the request to add the item
            logger.debug(f"Uploading {ENDPOINT} '{item_name}' to site '{site_name}'")
            response = ui_site.port_conf.create(new_items)
            if response:
                logger.info(f"Successfully created {ENDPOINT} '{item_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to create {ENDPOINT} {item_name}: {response}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except KeyError as e:
            logger.exception(f"Missing required key in file '{file_name}': {e}")
        except Exception as e:
            logger.exception(f"Error processing file '{file_name}': {e}")


def replace_items_at_site(unifi: Unifi, site_name: str, context: dict):
    """
    Replace items at a specified site by synchronizing the network configuration files found in
    a specific directory. This function allows replacing existing network entities such as VLANs
    or other network configurations for a defined site.

    The function fetches existing site configurations, processes specific files from
    the directory (based on inclusion and exclusion filters), replaces their network
    attributes with site-specific VLAN identifiers, backs up existing data, and finally updates
    the site configuration with the new definitions.

    :param unifi: An instance of the Unifi class for interfacing with the UniFi API.
    :type unifi: Unifi
    :param site_name: The name of the UniFi site where the operation will be performed.
    :type site_name: str
    :param context: A dictionary containing configuration for the deletion process.
        - endpoint_dir: The directory of the API endpoint to be used.
        - include_names: A list of item names to be deleted.
        - exclude_names: An optional list of item names to be excluded from deletion.
    :return: None
    """
    endpoint_dir = context.get("endpoint_dir")
    ENDPOINT = context.get("endpoint")
    include_names = context.get("include_names_list", None)
    exclude_names = context.get("exclude_names_list", None)
    ui_site = unifi.sites[site_name]

    site_data_filename = os.path.join(config.SITE_DATA_DIR, config.SITE_DATA_FILE)
    with open(site_data_filename, 'r') as f:
        all_site_data = json.load(f)

    site_data = all_site_data.get(site_name)
    vlans = site_data.get("vlans")
    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        logger.error(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")
        raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")

    # Fetch existing items from the site
    try:
        logger.debug(f"Fetching existing {ENDPOINT} from site '{site_name}'")
        existing_items = ui_site.port_conf.all()
        existing_item_map = {item.get("name"): item for item in existing_items}
        logger.debug(f"Existing {ENDPOINT}: {list(existing_item_map.keys())}")
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

            # Check if the item name exists and delete it using its _id
            if item_name in existing_item_map:
                item_to_delete = existing_item_map[item_name]
                item_id = item_to_delete.get("_id")
                if item_id:
                    item_to_backup = ui_site.port_conf.get(_id=item_id)
                    item_to_backup.backup(config.BACKUP_DIR)
                    delete_response = ui_site.port_conf.delete(item_id)
                    if not delete_response:
                        continue
                else:
                    logger.error(f"{ENDPOINT} '{item_name}' exists but its '_id' is missing. Skipping delete.")
                    continue

            # modify the profile for site specific vlan IDs
            for key, value in new_item.items():
                if key == "native_networkconf_id":
                    new_item[key] = vlans['native_networkconf_vlan_name']
                    # no longer need the custom vlan name
                    del new_item['native_networkconf_vlan_name']
                if key == "voice_networkconf_id":
                    new_item[key] = vlans['voice_networkconf_vlan_name']
                    # no longer need the custom vlan name
                    del new_item['voice_networkconf_vlan_name']
                if key == "excluded_networkconf_ids":
                    new_item[key] = [vlan_id for vlan_id in vlans['excluded_networkconf_vlan_names']]
                    # no longer need the custom vlan name
                    del new_item['excluded_networkconf_vlan_names']

            # Make the request to add the item
            logger.debug(f"Uploading {ENDPOINT} '{item_name}' to site '{site_name}'")
            response = ui_site.port_conf.create(new_item)
            if response:
                logger.info(f"Successfully created {ENDPOINT} '{item_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to create {ENDPOINT} {item_name}: {response}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.error(f"Error processing file '{file_name}': {e}")


if __name__ == "__main__":
    env_path = os.path.join(os.path.expanduser("~"), ".env")
    load_dotenv()
    ENDPOINT = 'Port Profiles'
    parser = argparse.ArgumentParser(description=f"{ENDPOINT} management script")
    site_name_group = parser.add_mutually_exclusive_group(required=True)
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
    site_name_group.add_argument(
        "--site-name",
        nargs=1,
        help="Name of the site to apply the changes to."
    )
    site_name_group.add_argument(
        "--site-names-file",
        type=str,
        help='File containing a list of site names to apply changes to.'
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
        logger.exception("Unifi username or password is missing from environment variables.")
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
    logger.debug(f'Valid {ENDPOINT} names: {valid_names}')

    # Get the site name(s) to apply changes too
    if args.site_name:
        site_names = args.site_name
    elif args.site_names_file:
        ui_name_filename = args.site_names_file
        ui_name_path = os.path.join(config.INPUT_DIR, ui_name_filename)
        with open(ui_name_path, 'r') as f:
            site_names = [line.strip() for line in f if line.strip()]
    else:
        logger.error('Missing site name. Please use --site-name [site_name] or --site-names-file [filename.txt].')
        raise SystemExit(1)

    MAX_CONTROLLER_THREADS = config.MAX_CONTROLLER_THREADS

    process_fucntion = None
    include_names_list = None
    exclude_names_list = None

    if args.get:
        logging.info(f"Option selected: Get {ENDPOINT}")
        process_fucntion = get_templates_from_base_site
        # Can't validate the include/exclude names since we don't know what they are until after they are retrieved.

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

        process_fucntion = replace_items_at_site

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
