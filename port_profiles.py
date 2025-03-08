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
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning
from utils import process_single_controller, save_dicts_to_json, read_json_file
from config import SITE_NAMES
from unifi.unifi import Unifi
import config
import utils
from utils import setup_logging, get_filtered_files, backup, delete_item_from_site
from unifi.portconf import PortConf
from unifi.sites import Sites
from unifi.networkconf import NetworkConf

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

load_dotenv()
logger = logging.getLogger(__name__)

def get_templates_from_base_site(unifi, site_name: str, obj_class, include_names: list = None, exclude_names: list = None):
    """
    Retrieve a list of object templates from a specified base site on the UniFi controller.
    The function accesses the site specified by `site_name`, retrieves network and VLAN configurations,
    and fetches objects of the specified class (`obj_class`). The objects can be filtered by inclusion or
    exclusion lists for better customization.

    :param unifi: An instance of the UniFi controller.
    :param site_name: The name of the base site whose templates are to be retrieved.
    :type site_name: str
    :param obj_class: Class representing the type of objects to fetch.
    :param include_names: Optional list of object names to specifically include in the result.
                          If provided, only the objects matching these names will be included.
    :type include_names: list, optional
    :param exclude_names: Optional list of object names to specifically exclude from the result.
                          If provided, objects matching these names will be skipped.
    :type exclude_names: list, optional
    :return: Boolean value indicating whether the operation was completed successfully.
    :rtype: bool
    """
    logger.debug(f'Searching for base site {site_name} on controller {unifi.base_url}')
    ui_site = Sites(unifi, desc=site_name)

    # get the list of vlans for the site
    network = NetworkConf(unifi, site=ui_site)
    networks = network.all()
    vlans = {}
    for network in networks:
        vlans.update({network['_id']: network['name']})

    ui_object = obj_class(unifi, site=ui_site)
    item_list = []

    all_items = ui_object.all()
    for item in all_items:
        # remove site specific entries
        del item['site_id']
        del item['_id']
        # Need to keep track of the vlan names which is not part of the profile info
        if 'native_networkconf_id' in item:
            item['native_networkconf_vlan_name'] = vlans.get(item['native_networkconf_id'])
        if 'voice_networkconf_id' in item:
            item['voice_networkconf_vlan_name'] = vlans.get(item['voice_networkconf_id'])
        if "excluded_networkconf_ids" in item:
            item["excluded_networkconf_vlan_names"] = [vlans.get(item_id) for item_id in item["excluded_networkconf_ids"]]

        if include_names:
            # Only fetch items that have been requested
            if item.get('name') in include_names:
                item_list.append(item)
        elif exclude_names:
            continue
        else:
            # Fetch all items
            item_list.append(item)
    logger.info(f'Saving {len(all_items)} {ENDPOINT} to {endpoint_dir}.')
    save_dicts_to_json(all_items, endpoint_dir)
    return True

def add_item_to_site(unifi: Unifi, site_name: str, obj_class, include_names: list, exclude_names: list = None):
    """
    Adds items to a specific site in the Unifi Controller by processing JSON files in a designated
    directory. Validates the existence of the target directory, reads configuration files, checks
    for existing objects, updates items with site-specific VLAN IDs, and uploads them to the
    Unifi Controller. Logs detailed information for each step.

    :param unifi: The Unifi object to interact with the Unifi Controller.
    :param site_name: Name of the site in the Unifi Controller where items will be added.
    :param obj_class: The class type for creating objects to interact with the Unifi API.
    :param include_names: List of file names to include in the process.
    :param exclude_names: Optional list of file names to exclude from the process.
    :return: None
    :raises ValueError: If the specified directory does not exist.
    :raises Exception: For failures in retrieving or uploading data from/to the Unifi Controller.
    """
    ui_site = Sites(unifi, desc=site_name)
    network = NetworkConf(unifi, site=ui_site)
    ui_object = obj_class(unifi, site=ui_site)

    vlans = {}
    networks = network.all()
    for vlan in networks:
        vlans.update({vlan.get("name"): vlan.get("_id")})

    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        logger.error(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")
        raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")

    try:
        logger.debug(f"Fetching existing {ENDPOINT} from site '{site_name}'")
        existing_items = ui_object.all()
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
                if key == "native_networkconf_id":
                    new_items[key] = vlans['native_networkconf_vlan_name']
                    # no longer need the custom vlan name
                    del new_items['native_networkconf_vlan_name']
                if key == "voice_networkconf_id":
                    new_items[key] = vlans['voice_networkconf_vlan_name']
                    # no longer need the custom vlan name
                    del new_items['voice_networkconf_vlan_name']
                if key == "excluded_networkconf_ids":
                    new_items[key] = [vlan_id for vlan_id in vlans['excluded_networkconf_vlan_names']]
                    # no longer need the custom vlan name
                    del new_items['excluded_networkconf_vlan_names']

            # Make the request to add the item
            logger.debug(f"Uploading {ENDPOINT} '{item_name}' to site '{site_name}'")
            response = ui_object.create(new_items)
            if response:
                logger.info(f"Successfully created {ENDPOINT} '{item_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to create {ENDPOINT} {item_name}: {response}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.error(f"Error processing file '{file_name}': {e}")

def replace_items_at_site(unifi: Unifi, site_name: str, obj_class, include_names: list, exclude_names: list = None):
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
    :param obj_class: The class representing the object to be manipulated in the site.
    :type obj_class: type
    :param include_names: A list of file names to include while searching for configuration files.
    :type include_names: list
    :param exclude_names: Optional list containing file names to exclude during the search.
    :type exclude_names: list, optional
    :return: None
    """
    ui_site = Sites(unifi, desc=site_name)
    network = NetworkConf(unifi, site=ui_site)
    ui_object = obj_class(unifi, site=ui_site)

    vlans = {}
    networks = network.all()
    for vlan in networks:
        vlans.update({vlan.get("name"): vlan.get("_id")})

    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        logger.error(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")
        raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")

    # Fetch existing items from the site
    try:
        logger.debug(f"Fetching existing {ENDPOINT} from site '{site_name}'")
        existing_items = ui_object.all()
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
                    item_to_backup = obj_class(unifi, site=ui_site).get(_id=item_id)
                    backup(item_to_backup, config.BACKUP_DIR)
                    delete_response = ui_object.delete(item_id)
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
            response = ui_object.create(new_item)
            if response:
                logger.info(f"Successfully created {ENDPOINT} '{item_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to create {ENDPOINT} {item_name}: {response}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.error(f"Error processing file '{file_name}': {e}")


if __name__ == "__main__":
    ENDPOINT = 'Port Profiles'
    parser = argparse.ArgumentParser(description=f"{ENDPOINT} management script")

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
    endpoint_dir = 'portconf'
    os.makedirs(endpoint_dir, exist_ok=True)
    backup_dir = config.BACKUP_DIR
    site_names_path = config.SITE_NAMES

    try:
        with open(site_names_path, 'r') as f:
            site_names = set(json.load(f))
    except FileNotFoundError:
        raise FileNotFoundError(f'The file {site_names_path} does not exist.')
    except json.JSONDecodeError:
        raise ValueError(f'The file {site_names_path} is not a valid JSON file.')

    base_site = config.BASE_SITE
    if not base_site:
        raise ValueError("Base site is not defined in the configuration file.")

    MAX_CONTROLLER_THREADS = config.MAX_CONTROLLER_THREADS

    process_fucntion = None
    include_names_list = None
    exclude_names_list = None

    if args.get:
        logging.info(f"Option selected: Get {ENDPOINT}")
        process_fucntion = get_templates_from_base_site
        site_names = {base_site}
        if args.include_names:
            include_name_list = args.include_names
        if args.exclude_names:
            exclude_name_list = args.exclude_names

    elif args.add:
        logging.info(f"Option selected: Add {ENDPOINT}")
        process_fucntion = add_item_to_site
        if args.include_names:
            include_name_list = args.include_names
        if args.exclude_names:
            exclude_name_list = args.exclude_names

    elif args.replace:
        logging.info(f"Option selected: Replace {ENDPOINT}")

        if not args.include_names:
            logger.error(f"--replace requires a list of {ENDPOINT} names to replace using --include-names.")
            sys.exit(1)

        # Log the items to be replaced
        logging.info(f"{ENDPOINT} names to be replaced: {args.include_names}")
        include_names_list = args.include_names
        process_fucntion = replace_items_at_site

    elif args.delete:
        logging.info(f"Option selected: Delete {ENDPOINT}")
        if not args.include_names:
            logger.error(f"--delete requires a list of {ENDPOINT} names to delete using --include-names.")
            sys.exit(1)
        logging.info(f"{ENDPOINT} names to be deleted: {args.include_names}")
        include_names_list = args.include_names
        process_fucntion = delete_item_from_site

    if process_fucntion:
        # Use concurrent.futures to handle multithreading
        with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
            # Submit each controller to the thread pool for processing
            future_to_controller = {executor.submit(process_single_controller, controller,
                                                    process_fucntion,
                                                    site_names,
                                                    PortConf,
                                                    include_names_list,
                                                    exclude_names_list,
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
