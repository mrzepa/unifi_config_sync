from datetime import datetime
from unifi.unifi import Unifi
import config
import logging
import json
import os
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning
logger = logging.getLogger(__name__)
warnings.simplefilter("ignore", InsecureRequestWarning)

back_lock = threading.Lock()

def port_backup(unifi, site_name: str):
    """
    Backs up port information of devices for a specified site managed in UniFi. The backup includes information
    from the device's `port_table` and excludes specific attributes listed in `ignore_port_info`. The output is
    saved in the form of JSON files, organized in a directory structure based on the site name. A file is generated
    for each device, timestamped to maintain historical data of the device's port configuration.

    :param unifi: The unifi controller the site belongs to.
    :param site_name: The name of the site from which port data for devices will be backed up.
    :type site_name: str
    :return: None
    """
    backup_dir = os.path.join(config.BACKUP_DIR, site_name)
    os.makedirs(backup_dir, exist_ok=True)
    ui_site = unifi.sites[site_name]
    devices = ui_site.device.all()
    ignore_port_info = ['rx_broadcast', 'rx_bytes', 'rx_dropped', 'rx_errors', 'rx_multicast', 'rx_packets',
                        'tx_broadcast',
                        'tx_bytes', 'tx_dropped', 'tx_errors', 'tx_multicast', 'tx_packets', 'tx_bytes-r', 'rx_bytes-r',
                        'bytes-r', 'poe_current', 'poe_power', 'poe_voltage']
    for device in devices:
        # Prepare the backup data structure
        backup_data = {}
        name = device['name']

        backup_filename = os.path.join(backup_dir, name + '.json')
        if os.path.exists(backup_filename):
            try:
                with open(backup_filename, "r") as f:
                    backup_data = json.load(f)  # Load existing backup
            except json.JSONDecodeError:
                logger.warning(f"Backup file {backup_filename} is corrupted. A new backup will be created.")

        _id = device['_id']
        ip = device['ip']

        port_table = device.get('port_table')
        if name not in backup_data:
            backup_data[name] = {}

        # Current date and time for backup categorization
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")

        if timestamp not in backup_data[name]:
            backup_data[name][timestamp] = {}

        backup_data[name][timestamp]['ip'] = ip
        backup_data[name][timestamp]['_id'] = _id
        if port_table:
            for port in port_table:
                for key in ignore_port_info:
                    port.pop(key, None)
        backup_data[name][timestamp]['port_table'] = port_table

        with back_lock:
            with open(backup_filename, 'w') as f:
                json.dump(backup_data, f, indent=4)

def process_backups(unifi, context: dict):
    """
    This function processes sites related to a given controller. It checks for matching site names between the
    provided context and the controller's available sites. For each matching site, the function executes a
    dynamically passed processing function in a multi-threaded manner using a ThreadPoolExecutor. Logging is
    done for debugging and issue identification. If no site is passed, then all sites on the controller are processed.

    :param unifi: Represents the controller object that contains available site details and functionalities.
    :type unifi: object
    :param context: A dictionary containing the context for site processing. It includes the list of site names
                    to match.
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

    with ThreadPoolExecutor(max_workers=config.MAX_SITE_THREADS) as executor:
        futures = []
        for site_name in site_names_to_process:
            futures.append(executor.submit(port_backup, unifi, site_name))

        # Wait for all site-processing threads to complete
        for future in as_completed(futures):
            try:
                future.result()  # Block until a thread completes
            except Exception as e:
                logger.exception(f"Error in process controller: {e}")

def backup_single_controller(controller, context: dict, username: str, password: str, mfa_secret: str):
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
    return process_backups(
        unifi=unifi,
        context=context,
    )

if __name__ == "__main__":

    env_path = os.path.join(os.path.expanduser("~"), ".env")
    load_dotenv()
    ENDPOINT = 'Network Configuration'

    parser = argparse.ArgumentParser(description=f"{ENDPOINT} Management Script")

    # Add the verbose flag
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output (debug level logging)"
    )
    parser.add_argument(
        "--site-names-file",
        type=str,
        default='sites.txt',
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
        logger.critical("Unifi username or password is missing from environment variables.")
        raise SystemExit(1)

    # get the list of controllers
    controller_list = config.CONTROLLERS
    logger.info(f'Found {len(controller_list)} controllers.')

    MAX_CONTROLLER_THREADS = config.MAX_CONTROLLER_THREADS

    # Get the site name(s) to apply changes too
    ui_name_filename = args.site_names_file
    ui_name_path = os.path.join(config.INPUT_DIR, ui_name_filename)
    with open(ui_name_path, 'r') as f:
        site_names = [line.strip() for line in f if line.strip()]

    context = {'site_names': site_names}

    with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
        futures = []
        future_to_controller = {executor.submit(backup_single_controller, controller,
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