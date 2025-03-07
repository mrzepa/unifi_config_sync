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
from utils import setup_logging, get_filtered_files
from unifi.portconf import PortConf
from unifi.sites import Sites
from unifi.networkconf import NetworkConf

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

load_dotenv()
logger = logging.getLogger(__name__)

def get_profiles_from_base(unifi, site_name: str, include_names: list = None, exclude_names: list = None):
    logger.debug(f'Searching for base site {site_name} on controller {unifi.base_url}')
    ui_site = Sites(unifi, desc=site_name)

    # get the list of vlans for the site
    network = NetworkConf(unifi, site=ui_site)
    networks = network.all()
    vlans = {}
    for network in networks:
        vlans.update({network['_id']: network['name']})

    port_profile = PortConf(unifi, site=ui_site)
    port_profiles = []

    portconfs = port_profile.all()
    for portconf in portconfs:
        # remove site specific entries
        del portconf['site_id']
        del portconf['_id']
        # Need to keep track of the vlan names which is not part of the profile info
        if 'native_networkconf_id' in portconf:
            portconf['native_networkconf_vlan_name'] = vlans[portconf['native_networkconf_id']]
        if 'voice_networkconf_id' in portconf:
            portconf['voice_networkconf_vlan_name'] = vlans[portconf['voice_networkconf_id']]
        if "excluded_networkconf_ids" in portconf:
            portconf["excluded_networkconf_vlan_names"] = [vlans[port_id] for port_id in portconf["excluded_networkconf_ids"]]

        if include_names:
            # Only fetch profiles that have been requested
            if portconf.get('name') in include_names:
                port_profiles.append(portconf)
        elif exclude_names:
            continue
        else:
            # Fetch all profiles
            port_profiles.append(portconf)
    logger.info(f'Saving {len(portconfs)} port porfiles to {profile_dir}.')
    save_dicts_to_json(portconfs, profile_dir)
    return True

def add_profiles_to_site(unifi: Unifi, site_name: str, include_names: list, exclude_names: list = None):
    """
    Add port profiles filtered from profile_names to a given site within the Unifi network.

    :param exclude_names: List of names to exclude from processing.
    :param unifi: An instance of the Unifi class to interact with the Unifi controller.
    :param site_name: The name of the UniFi site for which profiles are added.
    :param include_names: List of profile names to process. If empty, process all available profiles in the directory.
    """
    ui_site = Sites(unifi, desc=site_name)
    network = NetworkConf(unifi, site=ui_site)
    port_profile = PortConf(unifi, site=ui_site)

    vlans = {}
    networks = network.all()
    for vlan in networks:
        vlans.update({vlan.get("name"): vlan.get("_id")})

    # Ensure profiles_dir exists
    if not os.path.exists(profile_dir):
        logger.error(f"Profile directory '{profile_dir}' does not exist.")
        raise ValueError(f"Profile directory '{profile_dir}' does not exist.")

    # Fetch existing port configurations from the site
    try:
        logger.debug(f"Fetching existing port configurations for site '{site_name}'")
        existing_profiles = port_profile.all()
        existing_profile_names = {profile.get("name") for profile in existing_profiles}
        logger.debug(f"Existing profiles: {existing_profile_names}")
    except Exception as e:
        logger.error(f"Failed to fetch existing profiles for site '{site_name}': {e}")
        raise

    # Get files to process from the profiles directory
    profile_files = get_filtered_files(profile_dir, include_names, exclude_names)

    # Process selected files
    for file_path in profile_files:
        file_name = os.path.basename(file_path)
        try:
            logger.debug(f"Reading profile from file: {file_path}")
            new_portconf = read_json_file(file_path)
            portconf_name = new_portconf.get("name")

            # Check if the profile name already exists
            if portconf_name in existing_profile_names:
                logger.warning(f"Profile '{portconf_name}' already exists on site '{site_name}', skipping upload.")
                continue

            # modify the profile for site specific vlan IDs
            for key, value in new_portconf.items():
                if key == "native_networkconf_id":
                    new_portconf[key] = vlans['native_networkconf_vlan_name']
                    # no longer need the custom vlan name
                    del new_portconf['native_networkconf_vlan_name']
                if key == "voice_networkconf_id":
                    new_portconf[key] = vlans['voice_networkconf_vlan_name']
                    # no longer need the custom vlan name
                    del new_portconf['voice_networkconf_vlan_name']
                if key == "excluded_networkconf_ids":
                    new_portconf[key] = [vlan_id for vlan_id in vlans['excluded_networkconf_vlan_names']]
                    # no longer need the custom vlan name
                    del new_portconf['excluded_networkconf_vlan_names']

            # Make the request to add the profile
            logger.debug(f"Uploading profile '{portconf_name}' to site '{site_name}'")
            response = port_profile.create(new_portconf)
            if response:
                logger.info(f"Successfully created portconf '{portconf_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to create portconf {portconf_name}: {response}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.error(f"Error processing file '{file_name}': {e}")

def replace_profiles_at_site(unifi: Unifi, site_name: str, include_names: list, exclude_names: list = None):
    """
    Replace port profiles filtered from profile_names within a specified site in the Unifi network.

    :param exclude_names: List of names to exclude from processing.
    :param unifi: An instance of the Unifi class to interact with the controller.
    :param site_name: The name of the UniFi site for which profiles are replaced.
    :param include_names: List of profile names to process. If empty, process all available profiles in the directory.
    """
    ui_site = Sites(unifi, desc=site_name)
    network = NetworkConf(unifi, site=ui_site)
    port_profile = PortConf(unifi, site=ui_site)

    vlans = {}
    networks = network.all()
    for vlan in networks:
        vlans.update({vlan.get("name"): vlan.get("_id")})

    # Ensure profiles_dir exists
    if not os.path.exists(profile_dir):
        logger.error(f"Profile directory '{profile_dir}' does not exist.")
        raise ValueError(f"Profile directory '{profile_dir}' does not exist.")

    # Fetch existing port configurations from the site
    try:
        logger.debug(f"Fetching existing port configurations for site '{site_name}'")
        existing_items = port_profile.all()
        existing_item_map = {item.get("name"): item for item in existing_items}
        logger.debug(f"Existing profiles: {list(existing_item_map.keys())}")
    except Exception as e:
        logger.error(f"Failed to fetch existing port profiles for site '{site_name}': {e}")
        raise

    # Get files to process from the profiles directory
    profile_files = get_filtered_files(profile_dir, include_names, exclude_names)

    # Process selected files
    for file_path in profile_files:
        file_name = os.path.basename(file_path)
        try:
            logger.debug(f"Reading port profile from file: {file_path}")
            new_item = read_json_file(file_path)
            item_name = new_item.get("name")

            # Check if the profile name exists and delete it using its _id
            if item_name in existing_item_map:
                profile_to_delete = existing_item_map[item_name]
                profile_id = profile_to_delete.get("_id")
                if profile_id:
                    item_to_backup = PortConf(unifi, site=ui_site).get(_id=item_id)
                    backup(item_to_backup, config.BACKUP_DIR)
                    delete_response = port_profile.delete(profile_id)
                    if not delete_response:
                        continue
                else:
                    logger.error(f"Port profile '{item_name}' exists but its '_id' is missing. Skipping delete.")
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
            # Make the request to add the profile
            logger.debug(f"Uploading port profile '{item_name}' to site '{site_name}'")
            response = port_profile.create(new_item)
            if response:
                logger.info(f"Successfully created port profile '{item_name}' at site '{site_name}'")
            else:
                logger.error(f"Failed to create port profile {item_name}: {response}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{file_name}': {e}")
        except Exception as e:
            logger.error(f"Error processing file '{file_name}': {e}")

def delete_profiles_at_site(unifi: Unifi, site: str, include_names: list, exclude_names: list = None):
    """
    Deletes specified port profiles at a given site on a UniFi controller. This function first retrieves the site and its
    associated configurations, then iterates through the provided list of profile names to look up and delete the
    corresponding profiles. It logs the results of each operation, including skipped profiles, successful deletions,
    and failed deletion attempts.

    :param exclude_names: Not needed for delete operation.
    :param unifi: Object representing the UniFi controller API.
    :type unifi: Unifi
    :param site: The identifier or description of the UniFi site where the profiles should be deleted.
    :type site: str
    :param include_names: A list of names of port profiles to be deleted.
    :type include_names: list
    :return: None
    """
    ui_site = Sites(unifi, desc=site)
    port_profile = PortConf(unifi, site=ui_site)
    for name in include_names:
        item_id = port_profile.get_id(name=name)
        if item_id:
            item_to_backup = PortConf(unifi, site=ui_site).get(_id=item_id)
            backup(item_to_backup, config.BACKUP_DIR)
            logger.info(f"Deleting port profile '{name}' from site '{site}'")
            response = port_profile.delete(item_id)
            if response:
                logger.info(f"Successfully deleted port profile '{name}' from site '{site}'")
            else:
                logger.error(f"Failed to delete port profile '{name}' from site '{site}': {response}")
        else:
            logger.warning(f"Port profile '{name}' does not exist on site '{site}', skipping deletion.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Profile management script")

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
        help="Get profiles."
    )
    group.add_argument(
        "-a", "--add",
        action="store_true",
        help="Add profiles."
    )
    group.add_argument("-r", "--replace",
                       action="store_true",
                       help="Replace profiles.")

    group.add_argument("-d", "--delete",
                       action="store_true",
                       help="Delete profiles.")

    parser.add_argument(
        "--profile-names",
        nargs="*",
        default=[],  # Default to an empty list
        help="List of profile names to manipulate"
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

    # Get the directory for storing the profiles
    profile_dir = config.PROFILE_DIR
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
    profile_names_list = None
    if args.get:
        logging.info("Option selected: Get profiles")
        process_fucntion = get_profiles_from_base
        site_names = {base_site}
        profile_names_list = args.profile_names
    elif args.add:
        logging.info("Option selected: Add profiles")
        process_fucntion = add_profiles_to_site
        profile_names_list = args.profile_names
    elif args.replace:
        logging.info("Option selected: Replace profiles")

        if not args.profile_names:
            logger.error("--replace requires a list of profile names to replace using --profile-names.")
            sys.exit(1)

        # Log the profiles to be replaced
        logging.info(f"Profile names to be replaced: {args.profile_names}")
        profile_names_list = args.profile_names

        process_fucntion = replace_profiles_at_site
    elif args.delete:
        logging.info("Option selected: Delete profiles")
        if not args.profile_names:
            logger.error("--delete requires a list of profile names to delete using --profile-names.")
            sys.exit(1)
        logging.info(f"Profile names to be deleted: {args.profile_names}")
        profile_names_list = args.profile_names
        process_fucntion = delete_profiles_at_site

    if process_fucntion:
        # Use concurrent.futures to handle multithreading
        with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
            # Submit each controller to the thread pool for processing
            future_to_controller = {executor.submit(process_single_controller, controller,
                                                    process_fucntion,
                                                    site_names,
                                                    profile_names_list,
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
