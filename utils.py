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

def process_controller(unifi, process_function, site_names, include_name_list, exclude_name_list):
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
            futures.append(executor.submit(process_function, unifi, site_name, include_name_list, exclude_name_list))

        # Wait for all site-processing threads to complete
        for future in as_completed(futures):
            try:
                future.result()  # Block until a thread completes
            except Exception as e:
                logger.error(f"Error processing site: {e}")


def process_single_controller(controller, process_function, site_names, include_name_list, exclude_name_list,
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
            if "name" in item:
                filename = f"{item['name']}.json"
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

