from concurrent.futures import ThreadPoolExecutor, as_completed
from unifi.unifi import Unifi
from config import MAX_SITE_THREADS
import logging
import json
import os
import threading
from unifi.sites import Sites
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)
filelock = threading.Lock()

def process_controller(unifi, process_function, site_names, obj_class, include_name_list, exclude_name_list):
    """
       Processes a UniFi controller by authenticating and managing site data.
       This function connects to the specified UniFi controller, retrieves
       the available sites, and utilizes a thread pool to process each site concurrently.

       :param exclude_name_list: List of items to be excluded (e.g. profile names)
       :param include_name_list:  List of items to be included (e.g. profile names)
       :param unifi: Unifi object
       :param site_names: Set of site names to be processed
       :param process_function: A callable function to process each site (e.g., add_profiles_to_site).
       :return: None
       """

    # Fetch sites
    ui_site_names_set = set(unifi.get_site_list())
    site_names_to_process = list(site_names.intersection(ui_site_names_set))
    logger.debug(f'Found {len(site_names_to_process)} sites to process for this controller.')
    if len(site_names_to_process) == 0:
        logger.warning(f'No matching sites to process for controller {unifi.base_url}')
        return None

    # Process sites using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=MAX_SITE_THREADS) as executor:
        futures = []
        for site_name in site_names_to_process:
            # Pass the dynamic function
            futures.append(executor.submit(process_function,
                                           unifi, site_name, obj_class, include_name_list, exclude_name_list))

        # Wait for all site-processing threads to complete
        for future in as_completed(futures):
            try:
                future.result()  # Block until a thread completes
            except Exception as e:
                logger.exception(f"Error in process controller: {e}")


def process_single_controller(controller, process_function, site_names, obj_class, include_name_list, exclude_name_list,
                              username, password, mfa_secret, ):
    """
       Processes a single controller by delegating to the `process_controller` function.

       :param exclude_name_list: List of items to be excluded (e.g. profile names)
       :param include_name_list: List of UI items to be included (e.g. profile names)
       :param username: Username for accessing the UniFi controller.
       :param password: Password for accessing the UniFi controller.
       :param mfa_secret: MFA secret required for further authentication.
       :param site_names: Set of site names to be processed
       :param controller: The controller object to be processed.
       :type controller: Controller
       :param process_function: A callable function to process each site.
       :return: None
       """
    unifi = Unifi(controller, username, password, mfa_secret)
    unifi.authenticate()
    return process_controller(
        unifi=unifi,
        process_function=process_function,
        site_names=site_names,
        obj_class=obj_class,
        include_name_list=include_name_list,
        exclude_name_list=exclude_name_list
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

def backup(resource: dict, backup_dir: str):
    """
    Backup the configuration of the given resource before deleting it and clean up older backups.

    Each backup file is named after `Site.desc` and stores the configuration in the following structure:
    - object.endpoint:
        - date and time:
            - data

    Files older than 4 months are deleted automatically.

    :param resource: The resource object to back up. Must have `site` and `endpoint` attributes.
    :param backup_dir: Path to the directory where backups will be stored.
    """
    # Ensure the backup directory exists
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        logger.info(f"Backup directory created: {backup_dir}")

    # Get the site description and endpoint
    site_desc = resource.site.desc
    endpoint = resource.endpoint
    item_id = resource._id

    # Current date and time for backup categorization
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")

    # Backup file path
    backup_file_path = os.path.join(backup_dir, f"{site_desc}.json")

    # Prepare the backup data structure
    backup_data = {}
    if os.path.exists(backup_file_path):
        try:
            with open(backup_file_path, "r") as f:
                backup_data = json.load(f)  # Load existing backup
        except json.JSONDecodeError:
            logger.warning(f"Backup file {backup_file_path} is corrupted. A new backup will be created.")

    if endpoint not in backup_data:
        backup_data[endpoint] = {}

    # Retrieve configuration to be backed up
    data = resource.data

    # Add the new backup at the current timestamp and item_id
    if timestamp not in backup_data[endpoint]:
        backup_data[endpoint][timestamp] = {}

    backup_data[endpoint][timestamp][item_id] = data

    # Write back to the backup file
    with open(backup_file_path, "w") as f:
        json.dump(backup_data, f, indent=4)
        logger.info(f"Configuration backed up for site '{site_desc}' at endpoint '{endpoint}'.")

    # Clean up old backups (older than 4 months)
    cutoff_date = now - timedelta(days=4 * 30)  # Approximate 4 months as 120 days

    for date_str in list(backup_data[endpoint].keys()):
        backup_date = datetime.strptime(date_str, "%Y-%m-%d_%H-%M-%S")
        if backup_date < cutoff_date:
            del backup_data[endpoint][date_str]
            logger.info(f"Deleted old backup from {date_str} for '{endpoint}'.")

    # Save cleaned data back to the backup file
    with open(backup_file_path, "w") as f:
        json.dump(backup_data, f, indent=4)


def get_templates_from_base_site(unifi, site_name: str, obj_class, include_names: list = None, exclude_names: list = None):
    """
    Retrieves and processes templates/items from a specific site on a UniFi controller
    and saves the resulting item list after filtering based on include or exclude terms.

    This function interacts with the UniFi API to access data specific to a given
    site and processes the data based on the parameters provided. The filtered
    results are serialized into JSON format and saved locally.

    :param unifi: Instance of a UniFi controller to connect and retrieve data from.
    :param site_name: Name of the site to retrieve items from.
    :param obj_class: The class that represents the object type to retrieve.
    :param include_names: List of names of items to include. Only items with these
        names will be processed if specified.
    :param exclude_names: List of names of items to exclude. Items with these
        names will be omitted if specified.
    :return: Returns a boolean indicating the success of the operation.
    :rtype: bool
    """
    logger.debug(f'Searching for base site {site_name} on controller {unifi.base_url}')
    ui_site = Sites(unifi, desc=site_name)

    # get the list of items for the site
    ui_object = obj_class(unifi, site=ui_site)
    all_items = ui_object.all()
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
    logger.info(f'Saving {len(item_list)} {obj_class.__name__} in directory {obj_class.__name__.lower()}.')
    save_dicts_to_json(item_list, obj_class.__name__.lower())
    return True

def delete_item_from_site(unifi, site_name: str, obj_class, include_names: list, exclude_names: list = None):
    """
    Deletes items from a specified site in a UniFi controller.

    This function is responsible for deleting specified items from a site within a UniFi
    controller. First, it fetches the item by its name to acquire an identifier. If the item
    exists, it creates a backup of the item, attempts deletion, and logs the result. If the
    item does not exist, it logs a warning and skips the deletion for that item.

    :param unifi: UniFi controller instance used to perform actions.
    :type unifi: object
    :param site_name: The name of the site from which items will be deleted.
    :type site_name: str
    :param obj_class: The class type representing the object (e.g., devices, clients) that
        needs to be deleted.
    :type obj_class: type
    :param include_names: A list of item names to be deleted from the specified site.
    :type include_names: list
    :param exclude_names: A list of item names to be excluded from deletion. Default is None.
    :type exclude_names: list, optional
    :return: None
    """
    ui_site = Sites(unifi, desc=site_name)
    ui_object = obj_class(unifi, site=ui_site)

    for name in include_names:
        item_id = ui_object.get_id(name=name)
        if item_id:
            logger.info(f"Deleting {obj_class} '{name}' from site '{site}'")
            item_to_backup = obj_class(unifi, site=ui_site).get(_id=item_id)
            backup(item_to_backup, config.BACKUP_DIR)
            response = ui_object.delete(item_id)
            if response:
                logger.info(f"Successfully deleted {obj_class} '{name}' from site '{site}'")
            else:
                logger.error(f"Failed to delete {obj_class} '{name}' from site '{site}': {response}")
        else:
            logger.warning(f"{obj_class} '{name}' does not exist on site '{site}', skipping deletion.")

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