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
from utils import setup_logging
from unifi.portconf import PortConf
from unifi.sites import Sites
from unifi.networkconf import NetworkConf

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

load_dotenv()
logger = logging.getLogger(__name__)

def get_networks_from_base(unifi, site_name: str, inclide_names: list = None, exclude_names: list = None):
    logger.debug(f'Searching for base site {site_name} on controller {unifi.base_url}')
    ui_site = Sites(unifi, desc=site_name)

    # get the list of vlans for the site
    ui_network = NetworkConf(unifi, site=ui_site)
    ui_networks = ui_network.all()
    vlans = []
    for vlan in ui_networks:
        del vlan['site_id']
        del vlan['_id']
        if inclide_names:
            # Only fetch network that have been requested
            if vlan.get('name') in inclide_names:
                vlans.append(vlan)
        elif exclude_names:
            if vlan.get('name') not in exclude_names:
                continue
        else:
            # Fetch all networks
            vlans.append(vlan)
    logger.info(f'Saving {len(vlans)} network vlans to {network_dir}.')
    save_dicts_to_json(vlans, network_dir)
    return True

def add_networks_to_site(unifi, site_name: str, inclide_names: list = None, exclude_names: list = None):
    ui_site = Sites(unifi, desc=site_name)
    ui_network = NetworkConf(unifi, site=ui_site)

    # Ensure network_dir exists
    if not os.path.exists(network_dir):
        raise ValueError(f"Network directory '{network_dir}' does not exist.")

    # Fetch existing port configurations from the site
    try:
        logger.debug(f"Fetching existing network configurations for site '{site_name}'")
        existing_networks = ui_network.all()
        existing_network_names = {vlan.get("name") for vlan in existing_networks}
        logger.debug(f"Existing netwroks: {existing_network_names}")
    except Exception as e:
        logger.error(f"Failed to fetch existing networks for site '{site_name}': {e}")
        raise

    # Get files to process from the networks directory
    network_files = get_filtered_files(network_dir, include_names, exclude_names)

    # Process selected files
    for file_path in network_files:
        file_name = os.path.basename(file_path)
        try:
            logger.debug(f"Reading network conf from file: {file_path}")
            new_item = read_json_file(file_path)
            item_name = new_item.get("name")

            # Check if the network name already exists
            if item_name in existing_network_names:
                logger.warning(f"Vlan '{item_name}' already exists on site '{site}', skipping upload.")
                continue

            # Make the request to add the network
            logger.debug(f"Uploading network '{item_name}' to site '{site}'")
            response = ui_network.create(new_item)
            if response:
                logger.info(f"Successfully created network config '{item_name}' at site '{site}'")
            else:
                logger.error(f"Failed to create network config {item_name}: {response}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.error(f"Error processing file '{file_name}': {e}")

def replace_network_at_site(unifi, site_name: str, inclide_names: list = None, exclude_names: list = None):
    ui_site = Sites(unifi, desc=site_name)
    ui_network = NetworkConf(unifi, site=ui_site)

    # Ensure network_dir exists
    if not os.path.exists(network_dir):
        raise ValueError(f"Network directory '{network_dir}' does not exist.")

    # Fetch existing port configurations from the site
    try:
        logger.debug(f"Fetching existing network configurations for site '{site_name}'")
        existing_items = ui_network.all()
        existing_item_map = {item.get("name"): item for item in existing_items}
        logger.debug(f"Existing networks: {list(existing_item_map.keys())}")
    except Exception as e:
        logger.error(f"Failed to fetch existing networks for site '{site_name}': {e}")
        raise

    # Get files to process from the networks directory
    network_files = get_filtered_files(network_dir, include_names, exclude_names)
    # Process selected files
    for file_path in network_files:
        file_name = os.path.basename(file_path)
        try:
            logger.debug(f"Reading network config from file: {file_path}")
            new_item = read_json_file(file_path)
            item_name = new_item.get("name")

            # Check if the vlan name exists and delete it using its _id
            if item_name in existing_item_map:
                item_to_delete = existing_item_map[item_name]
                item_id = item_to_delete.get("_id")
                if item_id:
                    item_to_backup = NetworkConf(unifi, site=ui_site).get(_id=item_id)
                    backup(item_to_backup, config.BACKUP_DIR)
                    delete_response = ui_network.delete(item_id)
                    if not delete_response:
                        continue
                else:
                    logger.error(f"Vlan '{item_name}' exists but its '_id' is missing. Skipping delete.")
                    continue
            # Make the request to add the network config
            logger.debug(f"Uploading vlan '{item_name}' to site '{site_name}'")
            response = ui_network.create(new_item)
            if response:
                logger.info(f"Successfully created vlan '{item_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to create vlan {item_name}: {response}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.error(f"Error processing file '{file_name}': {e}")

def delete_networks_at_site(unifi, site_name: str, include_names: list, exclude_names: list = None):
    ui_site = Sites(unifi, desc=site_name)
    ui_network = NetworkConf(unifi, site=ui_site)

    for name in include_names:
        item_id = ui_network.get_id(name=name)
        if item_id:
            logger.info(f"Deleting vlan '{name}' from site '{site}'")
            item_to_backup = NetworkConf(unifi, site=ui_site).get(_id=item_id)
            backup(item_to_backup, config.BACKUP_DIR)
            response = ui_network.delete(item_id)
            if response:
                logger.info(f"Successfully deleted vlan '{name}' from site '{site}'")
            else:
                logger.error(f"Failed to delete vlan '{name}' from site '{site}': {response}")
        else:
            logger.warning(f"Vlan '{name}' does not exist on site '{site}', skipping deletion.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Network Config Management Script")

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
        help="Get networks."
    )
    group.add_argument(
        "-a", "--add",
        action="store_true",
        help="Add networks."
    )
    group.add_argument("-r", "--replace",
                       action="store_true",
                       help="Replace networks.")

    group.add_argument("-d", "--delete",
                       action="store_true",
                       help="Delete networks.")

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

    # Get the directory for storing the networks
    network_dir = config.NETWORK_DIR
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
    inclide_name_list = None
    exclude_name_list = None
    if args.get:
        logging.info("Option selected: Get Networks")
        process_fucntion = get_networks_from_base
        site_names = {base_site}
        if args.include_names:
            inclide_name_list = args.network_names
        if args.exclude_names:
            exclude_name_list = args.network_names
    elif args.add:
        logging.info("Option selected: Add Networks")
        process_fucntion = add_networks_to_site
        if args.include_names:
            inclide_name_list = args.network_names
        if args.exclude_names:
            exclude_name_list = args.network_names
    elif args.replace:
        logging.info("Option selected: Replace Networks")

        if not args.network_names:
            logger.error("--replace requires a list of network names to replace using --include-names.")
            sys.exit(1)

        # Log the networks to be replaced
        logging.info(f"Network names to be replaced: {args.network_names}")
        inclide_name_list = args.network_names

        process_fucntion = replace_network_at_site
    elif args.delete:
        logging.info("Option selected: Delete Networks")
        if not args.network_names:
            logger.error("--delete requires a list of networks names to delete using --include-names.")
            sys.exit(1)
        logging.info(f"Network names to be deleted: {args.network_names}")
        inclide_name_list = args.network_names
        process_fucntion = delete_networks_at_site

    if process_fucntion:
        # Use concurrent.futures to handle multithreading
        with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
            # Submit each controller to the thread pool for processing
            future_to_controller = {executor.submit(process_single_controller, controller,
                                                    process_fucntion,
                                                    site_names,
                                                    inclide_name_list,
                                                    exclude_name_list,
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
