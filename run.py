import os
import argparse
import copy
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning
import warnings
import config
import global_settings
import network_conf
import port_profiles
import radius_profiles
import wlan_conf
from utils import get_valid_names_from_dir, process_single_controller, validate_names, setup_logging
from dotenv import load_dotenv
from backup_ports import backup_single_controller
from config_dependencies import validate_config_dependencies, get_deployment_order

env_path = os.path.join(os.path.expanduser("~"), ".env")
load_dotenv()
# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

logger = logging.getLogger(__name__)

def permission_error_handler():
    """Called when a permission error is detected in any thread"""
    from unifi.permission_flag import set_permission_error
    set_permission_error()
    logger.warning("Permission error detected - stopping all threads...")

# Reset permission error flag at start
from unifi.permission_flag import reset_permission_error
reset_permission_error()

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

    # Add module selection option
    parser.add_argument(
        "-m", "--module",
        choices=['network_conf', 'radius_profiles', 'port_profiles', 'wlan_conf', 'global_settings'],
        help="Test only a specific module (e.g., network_conf)"
    )

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
    ui_username = os.getenv("UI_USERNAME")
    ui_password = os.getenv("UI_PASSWORD")
    ui_mfa_secret = os.getenv("UI_MFA_SECRET")
    ui_api_key = os.getenv("UI_API_KEY")

    # Check if API key auth is disabled
    skip_api_key_auth = getattr(config, 'SKIP_API_KEY_AUTH', False)
    
    if skip_api_key_auth:
        # API key auth is disabled, require username/password/mfa
        if not all([ui_username, ui_password, ui_mfa_secret]):
            logger.critical("SKIP_API_KEY_AUTH is True. Provide UI_USERNAME, UI_PASSWORD, and UI_MFA_SECRET.")
            raise SystemExit(1)
        logger.info("API key authentication disabled (SKIP_API_KEY_AUTH=True)")
    else:
        # Require either API key OR username/password/mfa
        if not ui_api_key and not all([ui_username, ui_password, ui_mfa_secret]):
            logger.critical("Provide either UI_API_KEY or UI_USERNAME, UI_PASSWORD, and UI_MFA_SECRET.")
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

    # Filter modules if --module argument is provided
    if args.module:
        logger.info(f"Testing only module: {args.module}")
        # Keep only the specified module
        module_mapping = {args.module: module_mapping[args.module]}
        context_dict = {args.module: context_dict[args.module]}

    # Get the configuration types being processed
    config_types = list(context_dict.keys())
    
    # Validate dependencies and get proper deployment order
    if not args.get:  # Dependencies only matter for add/replace/delete operations
        logger.info("Validating configuration dependencies...")
        
        # Use smart dependency validation that checks existing resources on target sites
        # This allows deploying WLAN configs when VLANs already exist on the controller
        if not validate_config_dependencies(config_types, check_existing_resources=True):
            logger.error("Dependency validation failed. Please check the deployment order.")
            sys.exit(1)
        
        logger.info("✅ Smart dependency validation enabled - checking existing resources on target sites")
        logger.info("   • VLANs, RADIUS profiles, and other dependencies will be validated on each target site")
        logger.info("   • No need to deploy dependencies if they already exist on the controller")
        
        # Still use deployment order for consistency, but don't require all dependencies to be in deployment list
        ordered_types = get_deployment_order(config_types)
        logger.info(f"Processing order: {' -> '.join(ordered_types)}")
        
        # Reorder context_dict and module_mapping according to dependencies
        ordered_context_dict = {}
        ordered_module_mapping = {}
        for config_type in ordered_types:
            if config_type in context_dict:
                ordered_context_dict[config_type] = context_dict[config_type]
                ordered_module_mapping[config_type] = module_mapping[config_type]
        
        context_dict = ordered_context_dict
        module_mapping = ordered_module_mapping

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

        for context_item in context_dict:
            module = module_mapping[context_item]
            # Retrieve the function object instead of a string.
            if context_item == 'global_settings':
                # global_settings does not support add_item_to_site, use replace_item_at_site instead
                context_dict[context_item]['process_function'] = module.replace_item_at_site
            else:
                context_dict[context_item]['process_function'] = module.add_item_to_site

        if not valid_names:
            raise ValueError(f"Base template directories do not exist. Please run with -g/--get first")

        if args.include_names:
            if not validate_names(args.include_names, valid_names, 'include-names'):
                raise argparse.ArgumentError(None, "Invalid include-names")
        if args.exclude_names:
            if not validate_names(args.exclude_names, valid_names, 'exclude-names'):
                raise argparse.ArgumentError(None, "Invalid exclude-names")

    if args.replace:
        logging.info(f"Option selected: Replace")
        for context_item in context_dict:
            module = module_mapping[context_item]
            # Retrieve the function object instead of a string.
            context_dict[context_item]['process_function'] = module.replace_item_at_site

        if not args.include_names:
            logger.error(f"--replace requires a list of names to replace using --include-names.")
            raise argparse.ArgumentError(None, "--replace requires a list of names to replace using --include-names.")

        if not valid_names:
            raise ValueError(f"Base template directories do not exist. Please run with -g/--get first")

        if validate_names(args.include_names, valid_names, 'include-names'):
            # Log the items to be replaced
            logging.info(f"Names to be replaced: {args.include_names}")
        else:
            raise argparse.ArgumentError(None, "Invalid include-names for replacement")

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
            raise argparse.ArgumentError(None, "--delete requires a list of names to delete using --include-names.")

        if not valid_names:
            raise ValueError(f"Base template directories do not exist. Please run with -g/--get first")

        if validate_names(args.include_names, valid_names, 'include-names'):
            logging.info(f"Names to be deleted: {args.include_names}")
        else:
            raise argparse.ArgumentError(None, "Invalid include-names for deletion")

    ui_name_filename = args.site_names_file
    ui_name_path = os.path.join(config.INPUT_DIR, ui_name_filename)
    if not args.get:
        try:
            with open(ui_name_path, 'r', encoding="utf-8") as f:
                site_names = [line.strip().replace("\xa0", " ") for line in f if line.strip()]
        except FileNotFoundError:
            logger.critical(f'No file {ui_name_path} found. Please create a file with site names, one per line.')
            sys.exit(1)

    base_context = {
        'include_names_list': args.include_names,
        'exclude_name_list': args.exclude_names,
        'site_names': site_names,
    }
    if args.verbose:
        base_context['verbose'] = True
    else:
        base_context['verbose'] = False

    # backup unifi switch ports
    # Use concurrent.futures to handle multithreading
    with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
        # Submit each controller to the thread pool for processing
        future_to_controller = {executor.submit(backup_single_controller, controller,
                                                base_context,
                                                ui_username,
                                                ui_password,
                                                ui_mfa_secret,
                                                ui_api_key): controller for controller in
                                controller_list}

        # Wait for all controller-processing threads to complete
        for future in as_completed(future_to_controller):
            try:
                future.result()
            except Exception as e:
                # Handle exceptions for individual tasks
                logger.error(e)
                continue

    for context_item in context_dict:
        context = copy.copy(base_context)
        context['process_function'] = context_dict[context_item]['process_function']
        context['endpoint_dir'] = context_item
        context['endpoint'] = context_dict[context_item]['endpoint']
        if context_item == 'global_settings':
            context['include_names_list'] = ['global_switch']
        if context_item == 'network_conf':
            context['skip_vlan_check'] = True

        # Use concurrent.futures to handle multithreading
        with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
            # Submit each controller to the thread pool for processing
            future_to_controller = {executor.submit(process_single_controller, controller,
                                                    context,
                                                    ui_username,
                                                    ui_password,
                                                    ui_mfa_secret,
                                                    ui_api_key,
                                                    permission_error_handler): controller for controller in
                                    controller_list}

            # Wait for all controller-processing threads to complete
            permission_errors = []
            for future in as_completed(future_to_controller):
                controller = future_to_controller[future]
                
                # Check if permission error was detected in another thread
                from unifi.permission_flag import is_permission_error_detected
                if is_permission_error_detected():
                    # Cancel remaining futures
                    for f in future_to_controller:
                        if not f.done():
                            f.cancel()
                    break
                
                try:
                    future.result()
                except PermissionError as e:
                    # Collect permission errors for summary
                    permission_errors.append(str(e))
                except Exception as e:
                    # Handle exceptions for individual tasks
                    logger.exception(f"Error processing controller {controller}: {e}")
                    continue
            
            # Provide permission error summary if any occurred
            if permission_errors:
                logger.warning("\n" + "=" * 80)
                logger.warning("PERMISSION SUMMARY")
                logger.warning("One or more controllers encountered permission issues.")
                logger.warning("This is expected if your admin account has read-only access.")
                logger.warning("To enable write operations, see the solutions above.")
                logger.warning("=" * 80)
                sys.exit(1)
