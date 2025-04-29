from concurrent.futures import ThreadPoolExecutor, as_completed
from unifi.unifi import Unifi
import config

import logging
import json
import os
import threading
from datetime import datetime, timedelta
from icecream import ic

logger = logging.getLogger(__name__)
filelock = threading.Lock()
site_data_lock = threading.Lock()

def vlan_check(unifi, site_name: str):
    """
    Validates that all required VLANs exist for the specified site. Compares the
    current VLAN configuration of the given site with a predefined baseline to
    identify any missing or extra VLANs.

    The function reads the baseline VLANs from a JSON file located in the directory
    specified within the configuration. It then compares them with the VLANs
    defined in the given site's configuration and logs the discrepancies.

    :param unifi: The Unifi instance providing access to site configurations.
    :type unifi: object
    :param site_name: The name of the site to validate VLANs for.
    :type site_name: str
    :return: Returns True if all required VLANs exist, otherwise False.
    :rtype: bool
    """
    logger.info(f'Validating that all required VLANs exist for {site_name}... ')

    ui_site = unifi.sites[site_name]
    # Get all the local vlans
    vlans = {}
    networks = ui_site.network_conf.all()
    for vlan in networks:
        vlans[vlan.get("name")] = vlan.get("_id")

    # Compare the local vlans to the baseline vlans
    baseline_filename = os.path.join(config.SITE_DATA_DIR, config.BASE_SITE_DATA_FILE)
    with open(baseline_filename, 'r', encoding='utf-8') as f:
        baseline_data = json.load(f)
        baseline_vlans = baseline_data.get("vlans", {})

    # Get the sets of VLAN names from both dictionaries
    existing_vlan_names = set(vlans.keys())
    baseline_vlan_names = set(baseline_vlans.keys())

    # Find missing and extra VLANs
    missing_vlans = baseline_vlan_names - existing_vlan_names
    extra_vlans = existing_vlan_names - baseline_vlan_names

    if missing_vlans:
        logger.error(f"Missing VLANs in {site_name}: {', '.join(sorted(missing_vlans))}")
    if extra_vlans:
        logger.info(f"Extra VLANs in {site_name}: {', '.join(sorted(extra_vlans))}")

    return len(missing_vlans) == 0


def build_site_data(unifi, site_name: str, output_filename: str, make_template: bool = False,):
    """
    Builds and saves site-specific data including VLANs, radius profiles, user groups,
    and access point groups for the given UniFi site. The resulting data is either stored
    in a specific file or used as a template based on the `make_template` flag.

    This function interacts with the UniFi site configuration to gather relevant
    information and stores or updates it in a JSON file. If the file already exists
    and the `make_template` flag is not set, the site-specific data is updated;
    otherwise, a new template or data structure is created for the specified site.

    :param unifi: UniFi instance that provides access to site configurations.
    :type unifi: UniFiController
    :param site_name: Name of the UniFi site to process.
    :type site_name: str
    :param output_filename: Path to the output JSON file for saving site data.
    :type output_filename: str
    :param make_template: If set to True, creates a new site data template
        without reading or updating existing data.
    :type make_template: bool
    :return: None
    :rtype: None
    :raises Exception: If there is an issue with loading or saving the site data.
    """
    logger.info(f'Getting local site data for {site_name}... ')
    ui_site = unifi.sites[site_name]

    logger.debug(f'Saving site info for {site_name} to {output_filename}...')
    # Get all the local vlans
    vlans = {}
    networks = ui_site.network_conf.all()
    for vlan in networks:
        vlans[vlan.get("name")] = vlan.get("_id")

    # Get all the local radius profiles
    radius_profiles_dict = {}
    radius_profiles = ui_site.radius_profile.all()
    for radius_profile in radius_profiles:
        if radius_profile.get("name") == 'Default':
            continue
        radius_profiles_dict[radius_profile.get("name")] = radius_profile.get("_id")

    # Get all local user groups
    user_groups_dict = {}
    user_groups = ui_site.user_group.all()
    for user_group in user_groups:
        if user_group.get("name") == 'Default':
            continue
        user_groups_dict[user_group.get("name")] = user_group.get("_id")

    # Get all local ap groups
    ap_groups_dict = {}
    ap_groups = ui_site.ap_groups.all()
    for ap_group in ap_groups:
        ap_groups_dict[ap_group.get("name")] = ap_group.get("_id")

    # New site data to be added/updated
    new_site_data = {
        "vlans": vlans,
        "radius_profiles": radius_profiles_dict,
        "user_groups": user_groups_dict,
        "ap_groups": ap_groups_dict,
    }

    # Make sure the SITE_DATA_DIR exists.
    os.makedirs(config.SITE_DATA_DIR, exist_ok=True)

    # Load existing data (if any) and update/add the new site info.
    with site_data_lock:
        try:
            if not make_template:
                if os.path.exists(output_filename):
                    with open(output_filename, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        logger.debug(f'Loaded existing site data for {site_name} from {output_filename}')
                else:
                    data = {}

                # Update the data for the specific site
                data[site_name] = new_site_data
            else:
                data = new_site_data
            # Write combined data back to file
            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                logger.info(f'Saved site data for {site_name} to {output_filename}')
        except Exception as e:
            logger.error(f'Failed to save site data to {output_filename}: {e}')

def process_controller(unifi, context: dict):
    """
    This function processes sites related to a given controller. It checks for matching site names between the
    provided context and the controller's available sites. For each matching site, the function executes a
    dynamically passed processing function in a multi-threaded manner using a ThreadPoolExecutor. Logging is
    done for debugging and issue identification. If no site is passed, then all sites on the controller are processed.

    :param unifi: Represents the controller object that contains available site details and functionalities.
    :type unifi: object
    :param context: A dictionary containing the context for site processing. It includes the list of site names
                    to match and a reference to the dynamic processing function for execution.
    :type context: dict
    :return: Returns None if no matching sites are found or if processing completes successfully.
    :rtype: None
    """
    site_names_set = set(context.get("site_names", []))
    if site_names_set:
        # Fetch sites, we only care to process the list of site names on this controller that are part of the list of
        # site names provided.
        ui_site_names_set = set(unifi.sites.keys())
        site_names_to_process = list(site_names_set.intersection(ui_site_names_set))
        logger.debug(f'Found {len(site_names_to_process)} sites to process for controller {unifi.base_url}.')
        if len(site_names_to_process) == 0:
            logger.warning(f'No matching sites to process for controller {unifi.base_url}')
            return None
    else:
        site_names_to_process = list(unifi.sites.keys())

    process_function = context.get("process_function")

    if process_function.__name__ == 'get_templates_from_base_site':
        output_filename = os.path.join(config.SITE_DATA_DIR, config.BASE_SITE_DATA_FILE)
        build_site_data(unifi, site_names_to_process[0], output_filename, make_template=True)
    else:
        output_filename = os.path.join(config.SITE_DATA_DIR, config.SITE_DATA_FILE)
        with ThreadPoolExecutor(max_workers=config.MAX_SITE_THREADS) as executor:
            futures = []
            for site_name in site_names_to_process:
                if not context.get('skip_vlan_check'):
                    if not vlan_check(unifi, site_name):
                        logger.error(f'Vlans not matching, skipping {site_name}... ')
                        return None
                futures.append(executor.submit(build_site_data, unifi, site_name, output_filename, make_template=False))

            # Wait for all site-processing threads to complete
            for future in as_completed(futures):
                try:
                    future.result()  # Block until a thread completes
                except Exception as e:
                    logger.exception(f"Error in process controller: {e}")

    # Process sites using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=config.MAX_SITE_THREADS) as executor:
        futures = []
        for site_name in site_names_to_process:
            # Pass the dynamic function
            futures.append(executor.submit(process_function,
                                           unifi, site_name, context))

        # Wait for all site-processing threads to complete
        for future in as_completed(futures):
            try:
                future.result()  # Block until a thread completes
            except Exception as e:
                logger.exception(f"Error in process controller: {e}")


def process_single_controller(controller, context: dict, username: str, password: str, mfa_secret: str):
    """
    Processes a single controller by creating a Unifi instance, authenticating, and delegating the
    controller processing task. This function acts as a wrapper that prepares and initializes
    necessary parameters and context for controller processing.

    :param controller: The controller instance to be processed.
    :param context: Dictionary containing the context required for processing the controller.
    :param username: Username to authenticate with the controller.
    :param password: Password to authenticate with the controller.
    :param mfa_secret: MFA secret for additional authentication layer.
    :return: The result of processing the given controller.
    """
    unifi = Unifi(controller, username, password, mfa_secret)

    if not unifi.sites:
        return None
    return process_controller(
        unifi=unifi,
        context=context,
    )

def save_dicts_to_json(dict_list, output_dir="output"):
    """
    Saves each dictionary in the list as a separate JSON file.
    The filename is based on the "name" key in the dictionary.

    :param dict_list: List of dictionaries
    :param output_dir: Directory where JSON files will be saved
    """
    with filelock:
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        for item in dict_list:
            if "name" in item or "key" in item:
                # Determine the filename based on "name" or "key"
                filename = f"{item.get('name', item.get('key'))}.json"
                filepath = os.path.join(output_dir, filename)

                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(item, f, indent=4)

                logger.info(f"Saved: {filepath}")
            else:
                logger.warning("Skipping dictionary without 'name' key:", item)


def read_json_file(filepath):
    """
    Reads a JSON file and returns the contents as a dictionary.

    :param filepath: Path to the JSON file
    :return: Dictionary with JSON content
    """
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def setup_logging(min_log_level=logging.INFO):
    """
    Sets up logging to separate files for each log level.
    Only logs from the specified `min_log_level` and above are saved in their respective files.
    Includes console logging for the same log levels.

    :param min_log_level: Minimum log level to log. Defaults to logging.INFO.
    """
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    if not os.access(logs_dir, os.W_OK):
        raise PermissionError(f"Cannot write to log directory: {logs_dir}")

    # Log files for each level
    log_levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }

    # Create the root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Capture all log levels

    # Define a log format
    log_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Set up file handlers for each log level
    for level_name, level_value in log_levels.items():
        if level_value >= min_log_level:
            log_file = os.path.join(logs_dir, f"{level_name.lower()}.log")
            handler = logging.FileHandler(log_file)
            handler.setLevel(level_value)
            handler.setFormatter(log_format)

            # Add a filter so only logs of this specific level are captured
            handler.addFilter(lambda record, lv=level_value: record.levelno == lv)
            logger.addHandler(handler)

    # Set up console handler for logs at `min_log_level` and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(min_log_level)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    logging.info(f"Logging is set up. Minimum log level: {logging.getLevelName(min_log_level)}")

def get_filtered_files(directory: str, include_names: list = None, exclude_names: list = None) -> list:
    """
    Get the list of files to process based on the given directory and file names.
    If include_names is empty, all JSON files in the directory will be returned.

    :param exclude_names: List of names to exclude, empty means no filtering.
    :param directory: Directory containing profile JSON files.
    :param include_names: List of names to include, empty means all files.
    :return: List of file paths matching the filtering criteria.
    """
    # Get all JSON files in the directory
    all_files = [f for f in os.listdir(directory) if f.endswith(".json")]

    # If include_names is provided, filter files only from include_names
    if include_names:
        return [
            os.path.join(directory, f)
            for f in all_files
            if os.path.splitext(f)[0] in include_names
        ]

    # If exclude_names is provided, exclude files from this list
    if exclude_names:
        exclude_names = set(exclude_names)  # Convert to set for faster lookups
        return [
            os.path.join(directory, f)
            for f in all_files
            if os.path.splitext(f)[0] not in exclude_names
        ]

    # If neither include_names nor exclude_names is provided, return all files
    return [os.path.join(directory, f) for f in all_files]


def get_valid_names_from_dir(directory: str) -> list:
    """
    Extract valid names (filenames without .json extension) from a given directory.

    :param directory: Directory to retrieve files from
    :return: List of filenames without the .json extension
    """
    try:
        # List all files in the directory and filter out non-json files
        valid_names = [os.path.splitext(file)[0] for file in os.listdir(directory) if file.endswith('.json')]
        return valid_names
    except FileNotFoundError:
        logger.error(f"The directory {directory} does not exist.")
        return []
    except Exception as e:
        logger.exception(f"An error occurred while retrieving files from {directory}: {e}")
        return []

def validate_names(provided_names: list, valid_names: list, include_exclude: str) -> bool:
    """
    Validate a list of provided names against a list of valid names within the context
    of inclusion or exclusion. If any invalid names are found, they are logged as errors
    with the associated context, and the function returns False. Otherwise, it returns
    True if all names are valid.

    :param provided_names: A list of names to validate.
    :param valid_names: A list of valid names that the provided_names will be checked against.
    :param include_exclude: A string indicating whether the context is for inclusion
        or exclusion, used for logging purposes.
    :return: A boolean indicating whether all provided names are valid.
    """
    provded_names_set = set(provided_names)
    valid_names_set = set(valid_names)
    if not provded_names_set.issubset(valid_names_set):
        invalid_names = provded_names_set - valid_names_set  # Find invalid names
        for invalid_name in invalid_names:
            logger.error(f"Invalid name encountered in --{include_exclude}: {invalid_name}")
        return False
    return True


