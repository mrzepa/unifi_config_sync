import os
import argparse
import copy
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning
import warnings
from icecream import ic
import config
import global_settings
import network_conf
import port_profiles
import radius_profiles
import wlan_conf
from utils import get_valid_names_from_dir, process_single_controller, validate_names, setup_logging
from dotenv import load_dotenv

env_path = os.path.join(os.path.expanduser("~"), ".env")
load_dotenv()
# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    ENDPOINT = 'Global'

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

    parser.add_argument(
        "--site-names-file",
        type=str,
        default='sites.txt',
        help='File containing a list of site names to apply changes to.'
    )
    parser.add_argument(
        "--base-site-name",
        type=str,
        default='Default',
        help='Name of the base site to get configuraitons from.'
    )
    # Parse the arguments
    args = parser.parse_args()

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

    MAX_CONTROLLER_THREADS = config.MAX_CONTROLLER_THREADS

    # Build a mapping from context item to an actual module.
    module_mapping = {
        'network_conf': network_conf,
        'radius_profiles': radius_profiles,
        'port_profiles': port_profiles,
        'wlan_conf': wlan_conf,
        'global_settings': global_settings
    }

    context_dict = {'network_conf': {'endpoint': 'Network'},
                    'radius_profiles': {'endpoint': 'Radius Profiles'},
                    'port_profiles': {'endpoint': 'Port Profiles'},
                    'wlan_conf': {'endpoint': 'WLANs'},
                    'global_settings': {'endpoint': 'Global Settings'}}

    # Get the directory for storing the items
    valid_names = []
    for endpoint_dir in context_dict:
        if os.path.exists(endpoint_dir):
            valid_names.extend(get_valid_names_from_dir(endpoint_dir))

    if args.verbose:
        setup_logging(logging.DEBUG)
    else:
        setup_logging(logging.INFO)

    if args.get:
        # Can't validate the include/exclude names since we don't know what they are until after they are retrieved.
        logging.info(f"Option selected: Get")

        for context_item in context_dict:
            module = module_mapping[context_item]
            # Retrieve the function object instead of a string.
            context_dict[context_item]['process_function'] = module.get_templates_from_base_site

        site_names = [args.base_site_name]

    if args.add:
        logging.info(f"Option selected: Add")

        # Remove "global_settings" if it does not support add_item_to_site
        context_dict.pop("global_settings", None)

        for context_item in context_dict:
            module = module_mapping[context_item]
            # Retrieve the function object instead of a string.
            if context_item == 'global_settings':
                context_dict[context_item]['process_function'] = module.replace_item_at_site
            else:
                context_dict[context_item]['process_function'] = module.add_item_to_site

        if not valid_names:
            raise ValueError(f"Base template directories do not exist. Please run with -g/--get first")

        if args.include_names:
            if not validate_names(args.include_names, valid_names, 'include-names'):
                raise argparse.ArgumentError
        if args.exclude_names:
            if not validate_names(args.exclude_names, valid_names, 'exclude-names'):
                raise argparse.ArgumentError

    if args.replace:
        logging.info(f"Option selected: Replace")
        for context_item in context_dict:
            module = module_mapping[context_item]
            # Retrieve the function object instead of a string.
            context_dict[context_item]['process_function'] = module.replace_item_at_site

        if not args.include_names:
            logger.error(f"--replace requires a list of names to replace using --include-names.")
            raise argparse.ArgumentError

        if not valid_names:
            raise ValueError(f"Base template directories do not exist. Please run with -g/--get first")

        if validate_names(args.include_names, valid_names, 'include-names'):
            # Log the items to be replaced
            logging.info(f"Names to be replaced: {args.include_names}")
        else:
            raise argparse.ArgumentError

    if args.delete:
        logging.info(f"Option selected: Delete")

        # Remove "global_settings" if it does not support delete_item_from_site
        context_dict.pop("global_settings", None)

        for context_item in context_dict:
            module = module_mapping[context_item]
            # Retrieve the function object instead of a string.
            if context_item == 'global_settings':
                context_dict[context_item]['process_function'] = None
            else:
                context_dict[context_item]['process_function'] = module.delete_item_from_site

        if not args.include_names:
            logger.error(f"--delete requires a list of names to delete using --include-names.")
            raise argparse.ArgumentError

        if not valid_names:
            raise ValueError(f"Base template directories do not exist. Please run with -g/--get first")

        if validate_names(args.include_names, valid_names, 'include-names'):
            logging.info(f"Names to be deleted: {args.include_names}")
        else:
            raise argparse.ArgumentError

    ui_name_filename = args.site_names_file
    ui_name_path = os.path.join(config.INPUT_DIR, ui_name_filename)
    if not args.get:
        try:
            with open(ui_name_path, 'r') as f:
                site_names = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            logger.critical(f'No file {ui_name_path} found. Please create a file with site names, one per line.')
            sys.exit(1)

    base_context = {
        'include_names_list': args.include_names,
        'exclude_name_list': args.exclude_names,
        'site_names': site_names,
    }

    for context_item in context_dict:
        context = copy.copy(base_context)
        context['process_function'] = context_dict[context_item]['process_function']
        context['endpoint_dir'] = context_item
        context['endpoint'] = context_dict[context_item]['endpoint']
        if context_item == 'global_settings':
            context['include_names_list'] = ['global_switch']

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
