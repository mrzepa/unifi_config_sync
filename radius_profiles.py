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
from config import SITE_NAMES, RADIUS_SERVERS
from unifi.unifi import Unifi
import config
import utils
from utils import (setup_logging, get_templates_from_base_site, delete_item_from_site, get_filtered_files, backup,
                   get_valid_names_from_dir, validate_names)
from unifi.sites import Sites
from unifi.radiusprofile import RadiusProfile

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

load_dotenv()
logger = logging.getLogger(__name__)


def add_item_to_site(unifi, site_name: str, obj_class, include_names: list = None, exclude_names: list = None):
    ui_site = Sites(unifi, desc=site_name)
    ui_object = obj_class(unifi, site=ui_site)

    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        raise ValueError(f"{ENDPOINT} directory '{endpoint_dir}' does not exist.")

    # Fetch existing port configurations from the site
    try:
        logger.debug(f"Fetching existing {ENDPOINT} from site '{site_name}'")
        existing_items = ui_object.all()
        existing_item_names = {item.get("name") for item in existing_items}
        logger.debug(f"Existing netwroks: {existing_item_names}")
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

            # Check if the name already exists
            if item_name in existing_item_names:
                logger.warning(f"{ENDPOINT} '{item_name}' already exists on site '{site_name}', skipping upload.")
                continue

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
            logger.exception(f"Error processing file '{file_name}': {e}")

def replace_item_at_site(unifi, site_name: str, obj_class, include_names: list = None, exclude_names: list = None):
    ui_site = Sites(unifi, desc=site_name)
    ui_object = obj_class(unifi, site=ui_site)

    # Ensure directory exists
    if not os.path.exists(endpoint_dir):
        raise ValueError(f"{ENDPOINT} '{endpoint_dir}' does not exist.")

    # Fetch existing items from the site
    try:
        logger.debug(f"Fetching existing {ENDPOINT} items from site '{site_name}'")
        existing_items = ui_object.all()
        existing_item_map = {item.get("name"): item for item in existing_items}
        logger.debug(f"Existing {ENDPOINT}: {list(existing_item_map.keys())}")
    except Exception as e:
        logger.error(f"Failed to fetch existing {ENDPOINT} items from site '{site_name}': {e}")
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

            # Check if the name exists and delete it using its _id
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
    endpoint_dir = 'radiusprofile'
    os.makedirs(endpoint_dir, exist_ok=True)
    valid_names = get_valid_names_from_dir(endpoint_dir)
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
    exclude_name_list = None

    if args.get:
        logging.info(f"Option selected: Get {ENDPOINT}")
        process_fucntion = get_templates_from_base_site
        site_names = {base_site}
        # Can't validate the include/exclude names since we don't know what they are until after they are retrieved.
        if args.include_names:
            include_names_list = args.include_names
        if args.exclude_names:
            exclude_name_list = args.exclude_names

    elif args.add:
        logging.info(f"Option selected: Add {ENDPOINT}")
        process_fucntion = add_item_to_site
        if args.include_names:
            if validate_names(args.include_names, valid_names, 'include-names'):
                include_name_list = args.include_names
            else:
                sys.exit(1)
        if args.exclude_names:
            if validate_names(args.exclude_names, valid_names, 'exclude-names'):
                exclude_name_list = args.exclude_names
            else:
                sys.exit(1)

    elif args.replace:
        logging.info(f"Option selected: Replace {ENDPOINT}")

        if not args.include_names:
            logger.error(f"--replace requires a list of {ENDPOINT} names to replace using --include-names.")
            sys.exit(1)

        if not valid_names:
            logger.error(f"No {ENDPOINT} files found in the directory '{endpoint_dir}'.")
            sys.exit(1)

        if validate_names(args.include_names, valid_names, 'include-names'):
            # Log the items to be replaced
            logging.info(f"{ENDPOINT} names to be replaced: {args.include_names}")
            include_name_list = args.include_names
        else:
            sys.exit(1)
        process_fucntion = replace_item_at_site

    elif args.delete:
        logging.info(f"Option selected: Delete {ENDPOINT}")
        if not args.include_names:
            logger.error(f"--delete requires a list of {ENDPOINT} names to delete using --include-names.")
            sys.exit(1)
        logging.info(f"{ENDPOINT} names to be deleted: {args.include_names}")
        if not valid_names:
            logger.error(f"No {ENDPOINT} files found in the directory '{endpoint_dir}'.")
            sys.exit(1)

        if validate_names(args.include_names, valid_names, 'include-names'):
            logging.info(f"{ENDPOINT} names to be deleted: {args.include_names}")
            include_name_list = args.include_names
        else:
            sys.exit(1)
        process_fucntion = delete_item_from_site

    if process_fucntion:
        # Use concurrent.futures to handle multithreading
        with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
            # Submit each controller to the thread pool for processing
            future_to_controller = {executor.submit(process_single_controller, controller,
                                                    process_fucntion,
                                                    site_names,
                                                    RadiusProfile,
                                                    include_names_list,
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
