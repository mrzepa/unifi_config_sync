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
from utils import process_single_controller, save_dicts_to_json, read_json_file, validate_names
from config import SITE_NAMES
from unifi.unifi import Unifi
import config
import utils
from utils import setup_logging, delete_item_from_site, get_filtered_files
from unifi.sites import Sites
from unifi.networkconf import NetworkConf
from unifi.radiusprofile import RadiusProfile
from unifi.setting import Setting

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

load_dotenv()
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
    :param context: A dictionary containing additional information for processing:
        - `endpoint_dir` (str): Directory containing configuration files.
        - `include_names` (list of str): List of file names to include.
        - `exclude_names` (list of str, optional): List of file names to exclude.
    :return: Returns a boolean indicating the success of the operation.
    :rtype: bool
    """

    endpoint_dir = context.get("endpoint_dir")
    include_names = context.get("include_names", None)
    ui_site = unifi.sites[site_name]
    ui_site.output_dir = endpoint_dir
    logger.debug(f'Searching for base site {site_name} on controller {unifi.base_url}')

    # get the list of items for the site
    all_items = ui_site.setting.all()
    item_list = []

    # get the list of vlans for the site
    networks = ui_site.networkconf.all()
    vlans = {}
    for network in networks:
        vlans.update({network['_id']: network['name']})

    # get the radius profiles for the site
    radius_profiles = ui_site.radiusprofile.all()
    radius_profiles_dict = {}
    for radius_profile in radius_profiles:
        radius_profiles_dict.update({radius_profile['_id']: radius_profile['name']})

    for item in all_items:
        if any(value in include_names for key, value in item.items()):
            # Copy the dictionary and remove unwanted keys in the process
            filtered_item = item.copy()  # Create a copy of the original `item` dictionary

            # Remove unnecessary keys in the copy
            filtered_item.pop('site_id', None)
            filtered_item.pop('_id', None)
            filtered_item.pop('switch_exclusions', None)

            # Add additional fields in the copy
            if 'dot1x_fallback_networkconf_id' in item:
                filtered_item['dot1x_fallback_networkconf_vlan_name'] = vlans[item['dot1x_fallback_networkconf_id']]
            if 'radiusprofile_id' in item:
                filtered_item['radiusprofile_id_name'] = radius_profiles_dict[item['radiusprofile_id']]

            # Append the modified copy to your item_list
            item_list.append(filtered_item)

    logger.info(f'Saving {len(item_list)} {obj_class.__name__} in directory {ui_site.output_dir}.')
    save_dicts_to_json(item_list, ui_site.output_dir)
    return True


def update_settings_at_site(unifi: Unifi, site_name: str, context: dict):
    """
    Adds items to a specific site in the Unifi Controller by processing JSON files in a designated
    directory. Validates the existence of the target directory, reads configuration files, checks
    for existing objects, updates items with site-specific VLAN IDs, and uploads them to the
    Unifi Controller. Logs detailed information for each step.

    :param unifi: The Unifi object to interact with the Unifi Controller.
    :param site_name: Name of the site in the Unifi Controller where items will be added.
    :param context: A dictionary containing additional information for processing:
        - `endpoint_dir` (str): Directory containing configuration files.
        - `include_names` (list of str): List of file names to include.
        - `exclude_names` (list of str, optional): List of file names to exclude.
    :return: None
    :raises ValueError: If the specified directory does not exist.
    :raises Exception: For failures in retrieving or uploading data from/to the Unifi Controller.
    """
    ui_site = unifi.sites[site_name]

    vlans = {}
    networks = ui_site.networkconf.all()
    for vlan in networks:
        vlans.update({vlan.get("name"): vlan.get("_id")})

    radius = RadiusProfile(unifi, site=ui_site)
    radius_profiles = radius.all()
    radius_profiles_dict = {}
    for radius_profile in radius_profiles:
        radius_profiles_dict.update({radius_profile.get("name"): radius_profile.get("_id")})

    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        logger.error(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")
        raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")

    try:
        logger.debug(f"Fetching existing {ENDPOINT} from site '{site_name}'")
        existing_items = ui_site.setting.all()
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
            item_name = new_items.get("key")
            item_id = ui_site.setting.get(key=item_name).get("_id")

            # modify the item for site specific vlan IDs and Radius profiles
            for key, value in new_items.items():
                if key == "dot1x_fallback_networkconf_id":
                    new_items[key] = vlans['dot1x_fallback_networkconf_vlan_name']
                    # no longer need the custom vlan name
                    del new_items['dot1x_fallback_networkconf_vlan_name']
                if key == "radiusprofile_id":
                    new_items[key] = vlans['radiusprofile_id_name']
                    # no longer need the custom radius profile name
                    del new_items['radiusprofile_id_name']

            # Make the request to add the item
            logger.debug(f"Uploading {ENDPOINT} '{item_name}' to site '{site_name}'")
            url = f"{ui_site.setting.API_PATH}/{ui_site.name}/{ui_site.setting.base_path}/{ui_site.setting.endpoint}/{item_name}/{item_id}"
            response = ui_site.setting.make_request(url, 'PUT', data=new_items)
            if response.get("meta", {}).get('rc') == 'ok':
                logger.info(f"Successfully updated {ENDPOINT} '{item_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to update {ENDPOINT} {item_name}: {response}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.error(f"Error processing file '{file_name}': {e}")


if __name__ == "__main__":
    ENDPOINT = 'Global Settings'
    valid_keys = ['global_switch']
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
    endpoint_dir = 'global_settings'
    if os.path.exists(endpoint_dir):
        valid_names = get_valid_names_from_dir(endpoint_dir)
    else:
        valid_names = []

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
    exclude_name_list = None

    if args.get:
        logging.info(f"Option selected: Get {ENDPOINT}")
        if not args.include_names:
            logger.error(f"--get requires a list of {ENDPOINT} keys to get using --include-names. Valid keys are: {valid_keys}")
            sys.exit(1)

        process_fucntion = get_templates_from_base_site
        site_names = {base_site}
        if validate_names(args.include_names, valid_keys, 'include-names'):
            logger.info(f'{ENDPOINT} keys to be retrieved: {args.include_names}')
            include_names_list = args.include_names
        else:
            sys.exit(1)

    elif args.add:
        logger.warning(f'Option: Add not allowed for {ENDPOINT}.')
        sys.exit(1)

    elif args.replace:
        logging.info(f"Option selected: Replace {ENDPOINT}")

        if not args.include_names:
            logger.error(f"--replace requires a list of {ENDPOINT} keys to replace using --include-names. Valid keys are: {valid_keys}")
            sys.exit(1)
        if not valid_names:
            raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist. Please run with -g/--get first")

        # Log the items to be replaced
        if validate_names(args.include_names, valid_keys, 'include-names'):
            logging.info(f"{ENDPOINT} names to be replaced: {args.include_names}")
        else:
            sys.exit(1)
        process_fucntion = replace_item_at_site

    elif args.delete:
        logger.warning(f'Option: Delete not allowed for {ENDPOINT}.')
        sys.exit(1)

    if process_fucntion:
        context = {'process_function': process_function,
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
