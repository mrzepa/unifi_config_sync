#!/usr/bin/env python3
"""
Manual backup CLI for UniFi configuration sync operations.

This script provides command-line interface for creating manual backups
of UniFi configurations on demand.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from unifi.unifi import Unifi
from rollback_manager import create_config_backup, list_available_backups
from utils import setup_logging
import logging
import config

logger = logging.getLogger(__name__)

def backup_single_controller(controller, config_types: list, site_names: list, 
                            username: str, password: str, mfa_secret: str, api_key: str = None):
    """Backup configurations for a single controller."""
    try:
        # Check if API key auth is disabled
        skip_api_key_auth = getattr(config, 'SKIP_API_KEY_AUTH', False)
        
        # Check for per-controller API key
        controller_api_key_env = getattr(config, 'CONTROLLER_API_KEYS', {}).get(controller)
        
        if controller_api_key_env:
            # Use per-controller API key from environment variable
            controller_api_key = os.getenv(controller_api_key_env)
            if controller_api_key:
                logger.debug(f"Using per-controller API key from {controller_api_key_env} for: {controller}")
            else:
                logger.warning(f"Environment variable {controller_api_key_env} not found for controller: {controller}")
                controller_api_key = None
        else:
            # No per-controller configuration
            controller_api_key = api_key
    
        # Username/password/MFA are global (same across all controllers)
        try:
            unifi = Unifi(controller, username, password, mfa_secret, api_key=controller_api_key, force_modern_auth=skip_api_key_auth)
        except Exception as e:
            logger.error(f"Authentication error for controller {controller}: {e}")
            return None

        if not unifi.sites:
            logger.error(f"No sites found on controller {controller}")
            return None
        
        backup_ids = []
        
        for site_name in site_names:
            if site_name not in unifi.sites:
                logger.warning(f"Site '{site_name}' not found on controller {controller}")
                continue
                
            logger.info(f"Creating manual backups for site '{site_name}' on controller {controller}")
            
            for config_type in config_types:
                try:
                    # Get the appropriate site object
                    ui_site = unifi.sites[site_name]
                    
                    # Get current configurations based on type
                    configs = []
                    if config_type == 'wlanconf':
                        configs = ui_site.wlan_conf.all()
                    elif config_type == 'networkconf':
                        configs = ui_site.network_conf.all()
                    elif config_type == 'radiusprofile':
                        configs = ui_site.radius_profile.all()
                    elif config_type == 'portconf':
                        configs = ui_site.port_conf.all()
                    elif config_type == 'usergroup':
                        configs = ui_site.user_group.all()
                    elif config_type == 'apgroup':
                        configs = ui_site.ap_groups.all()
                    else:
                        logger.warning(f"Unknown config type: {config_type}")
                        continue
                    
                    if configs:
                        # Create backup using rollback manager
                        backup_id = create_config_backup(
                            config_type=config_type,
                            site_name=site_name,
                            controller_url=controller,
                            configs=configs,
                            operation="manual"
                        )
                        backup_ids.append(backup_id)
                        logger.info(f"✅ Created backup: {backup_id}")
                    else:
                        logger.info(f"No {config_type} configurations found to backup")
                        
                except Exception as e:
                    logger.error(f"Failed to backup {config_type} for site {site_name}: {e}")
        
        return backup_ids
        
    except Exception as e:
        logger.error(f"Error processing controller {controller}: {e}")
        return None

def main():
    """Main manual backup CLI function."""
    parser = argparse.ArgumentParser(
        description="UniFi Configuration Manual Backup Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --all                                    # Backup all config types for all sites
  %(prog)s --config-types wlanconf networkconf     # Backup specific config types
  %(prog)s --sites "Main Office" "Branch 1"        # Backup specific sites
  %(prog)s --config-types wlanconf --sites "Main"  # Backup WLAN configs for specific site
  %(prog)s --list                                   # List existing backups
        """
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    
    # Backup options
    parser.add_argument(
        "--all",
        action="store_true",
        help="Backup all configuration types"
    )
    
    parser.add_argument(
        "--config-types",
        nargs="+",
        choices=['wlanconf', 'networkconf', 'radiusprofile', 'portconf', 'usergroup', 'apgroup'],
        help="Configuration types to backup"
    )
    
    parser.add_argument(
        "--sites",
        nargs="+",
        help="Site names to backup (default: all sites)"
    )
    
    parser.add_argument(
        "--site-names-file",
        type=str,
        default='sites.txt',
        help='File containing a list of site names to backup.'
    )
    
    parser.add_argument(
        "--list",
        action="store_true",
        help="List existing backups instead of creating new ones"
    )
    
    # Parse the arguments
    args = parser.parse_args()
    
    # Set up logging based on the verbose flag
    if args.verbose:
        setup_logging(logging.DEBUG)
    else:
        setup_logging(logging.INFO)
    
    # Load environment variables
    load_dotenv()
    
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
    
    # If just listing backups, do that and exit
    if args.list:
        logger.info("Listing existing backups:")
        backups = list_available_backups()
        if backups:
            for backup in backups:
                print(f"  {backup['backup_id']} - {backup['timestamp']} ({backup['config_type']})")
        else:
            print("  No backups found.")
        return
    
    # Validate backup options
    if not args.all and not args.config_types:
        logger.error("Must specify either --all or --config-types")
        parser.print_help()
        raise SystemExit(1)
    
    # Determine config types to backup
    if args.all:
        config_types = ['wlanconf', 'networkconf', 'radiusprofile', 'portconf', 'usergroup', 'apgroup']
    else:
        config_types = args.config_types
    
    # Get site names
    if args.sites:
        site_names = args.sites
    else:
        # Read from sites file
        ui_name_filename = args.site_names_file
        ui_name_path = os.path.join(config.INPUT_DIR, ui_name_filename)
        if not os.path.exists(ui_name_path):
            logger.error(f"Site names file not found: {ui_name_path}")
            logger.error("Create this file with one site name per line, or use --sites to specify sites directly.")
            raise SystemExit(1)
        
        with open(ui_name_path, 'r') as f:
            site_names = [line.strip() for line in f if line.strip()]
    
    if not site_names:
        logger.error("No site names specified. Use --sites or create a sites.txt file.")
        raise SystemExit(1)
    
    logger.info(f"Starting manual backup for {len(config_types)} config types across {len(site_names)} sites")
    
    # Get the list of controllers
    controller_list = config.CONTROLLERS
    logger.info(f'Found {len(controller_list)} controllers.')
    
    MAX_CONTROLLER_THREADS = config.MAX_CONTROLLER_THREADS
    
    # Process controllers
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    all_backup_ids = []
    
    with ThreadPoolExecutor(max_workers=MAX_CONTROLLER_THREADS) as executor:
        futures = []
        for controller in controller_list:
            future = executor.submit(backup_single_controller, controller, config_types, site_names,
                                   ui_username, ui_password, ui_mfa_secret, ui_api_key)
            futures.append(future)
        
        # Wait for all backup operations to complete
        for future in as_completed(futures):
            try:
                backup_ids = future.result()
                if backup_ids:
                    all_backup_ids.extend(backup_ids)
            except Exception as e:
                logger.error(f"Error in backup operation: {e}")
    
    # Summary
    if all_backup_ids:
        logger.info(f"\n🎉 Manual backup completed successfully!")
        logger.info(f"📁 Total backups created: {len(all_backup_ids)}")
        logger.info(f"\nBackup IDs created:")
        for backup_id in all_backup_ids:
            logger.info(f"  • {backup_id}")
        logger.info(f"\n💡 Use these backup IDs with rollback.py to restore if needed:")
        logger.info(f"   python3 rollback.py list")
        logger.info(f"   python3 rollback.py info <backup_id>")
        logger.info(f"   python3 rollback.py rollback <backup_id> --dry-run")
    else:
        logger.warning("No backups were created.")

if __name__ == "__main__":
    main()
