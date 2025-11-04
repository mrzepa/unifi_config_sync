#!/usr/bin/env python3
"""
Manual rollback CLI for UniFi configuration sync operations.

This script provides command-line interface for managing configuration backups
and performing manual rollbacks when needed.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from unifi.unifi import Unifi
from rollback_manager import (
    rollback_manager, 
    list_available_backups, 
    get_backup_data, 
    delete_config_backup,
    cleanup_old_backups
)
from utils import setup_logging
import logging

logger = logging.getLogger(__name__)

def format_backup_info(backup_metadata):
    """Format backup metadata for display."""
    timestamp = backup_metadata.get('timestamp', '')
    try:
        # Parse timestamp for better formatting
        dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
        formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        formatted_time = timestamp
    
    return f"""
Backup ID: {backup_metadata.get('backup_id', 'N/A')}
  Created: {formatted_time}
  Config Type: {backup_metadata.get('config_type', 'N/A')}
  Site: {backup_metadata.get('site_name', 'N/A')}
  Controller: {backup_metadata.get('controller_url', 'N/A')}
  Operation: {backup_metadata.get('operation', 'N/A')}
  Config Count: {backup_metadata.get('config_count', 0)}
"""

def perform_rollback(backup_id: str, dry_run: bool = False):
    """
    Perform rollback using the specified backup.
    
    Args:
        backup_id: The backup ID to rollback to
        dry_run: If True, only show what would be restored without making changes
    """
    backup_data = get_backup_data(backup_id)
    if not backup_data:
        logger.error(f"Backup {backup_id} not found")
        return False
    
    config_type = backup_data.get('config_type')
    site_name = backup_data.get('site_name')
    controller_url = backup_data.get('controller_url')
    configurations = backup_data.get('configurations', [])
    
    logger.info(f"Rollback Information:")
    logger.info(f"  Backup ID: {backup_id}")
    logger.info(f"  Config Type: {config_type}")
    logger.info(f"  Site: {site_name}")
    logger.info(f"  Controller: {controller_url}")
    logger.info(f"  Configurations to restore: {len(configurations)}")
    
    if dry_run:
        logger.info("\nDRY RUN - No changes will be made")
        for config in configurations:
            name = config.get('name') or config.get('key') or 'Unknown'
            logger.info(f"  Would restore: {name}")
        return True
    
    # Get authentication credentials
    try:
        ui_username = os.getenv("UI_USERNAME")
        ui_password = os.getenv("UI_PASSWORD")
        ui_mfa_secret = os.getenv("UI_MFA_SECRET")
        ui_api_key = os.getenv("UI_API_KEY")
        
        if not ui_username or not ui_password:
            logger.error("UI_USERNAME and UI_PASSWORD environment variables are required")
            return False
            
    except KeyError as e:
        logger.error(f"Missing required environment variable: {e}")
        return False
    
    try:
        # Connect to UniFi controller
        logger.info(f"Connecting to controller: {controller_url}")
        unifi = Unifi(controller_url, ui_username, ui_password, ui_mfa_secret, ui_api_key)
        
        # Get the site
        if site_name not in unifi.sites:
            logger.error(f"Site '{site_name}' not found on controller")
            return False
        
        ui_site = unifi.sites[site_name]
        
        # Import the appropriate module for the config type
        if config_type == 'network_conf':
            from network_conf import replace_item_at_site
        elif config_type == 'port_profiles':
            from port_profiles import replace_items_at_site
        elif config_type == 'radius_profiles':
            from radius_profiles import replace_item_at_site
        elif config_type == 'wlan_conf':
            from wlan_conf import replace_item_at_site
        elif config_type == 'global_settings':
            from global_settings import replace_item_at_site
        else:
            logger.error(f"Unsupported config type: {config_type}")
            return False
        
        logger.info(f"Starting rollback to backup {backup_id}...")
        
        # Create a new backup before rollback
        current_configs = []
        if config_type == 'network_conf':
            current_configs = ui_site.network_conf.all()
        elif config_type == 'port_profiles':
            current_configs = ui_site.port_conf.all()
        elif config_type == 'radius_profiles':
            current_configs = ui_site.radius_profile.all()
        elif config_type == 'wlan_conf':
            current_configs = ui_site.wlan_conf.all()
        elif config_type == 'global_settings':
            current_configs = ui_site.setting.all()
        
        pre_rollback_backup = rollback_manager.create_backup(
            config_type, site_name, controller_url, current_configs, "pre-rollback"
        )
        logger.info(f"Created pre-rollback backup: {pre_rollback_backup}")
        
        # Save the backup configurations to temporary files for restoration
        temp_dir = f"temp_rollback_{backup_id}"
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            # Write each configuration to a file
            for config in configurations:
                config_name = config.get('name') or config.get('key') or 'unknown'
                filename = f"{config_name}.json"
                filepath = os.path.join(temp_dir, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
            
            # Prepare context for replacement
            context = {
                'endpoint_dir': temp_dir,
                'include_names_list': [config.get('name') or config.get('key') for config in configurations],
                'exclude_name_list': None
            }
            
            # Perform the replacement
            if config_type == 'global_settings':
                success = replace_item_at_site(unifi, site_name, context)
            else:
                success = replace_item_at_site(unifi, site_name, context)
            
            if success:
                logger.info(f"Rollback completed successfully!")
                logger.info(f"Restored {len(configurations)} configurations")
                logger.info(f"Pre-rollback backup created: {pre_rollback_backup}")
                return True
            else:
                logger.error("Rollback failed - no changes were made")
                return False
                
        finally:
            # Clean up temporary directory
            try:
                shutil.rmtree(temp_dir)
                logger.debug(f"Cleaned up temporary directory: {temp_dir}")
            except:
                logger.warning(f"Failed to clean up temporary directory: {temp_dir}")
    
    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        return False

def main():
    """Main rollback CLI function."""
    parser = argparse.ArgumentParser(
        description="UniFi Configuration Rollback Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                                    # List all available backups
  %(prog)s list --config-type network_conf        # List network config backups
  %(prog)s list --site-name "Main Office"         # List backups for specific site
  %(prog)s info backup_id                         # Show backup details
  %(prog)s rollback backup_id                     # Perform rollback
  %(prog)s rollback backup_id --dry-run           # Show what would be restored
  %(prog)s delete backup_id                       # Delete a backup
  %(prog)s cleanup --days 30                      # Clean up old backups
        """
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List available backups')
    list_parser.add_argument('--config-type', help='Filter by configuration type')
    list_parser.add_argument('--site-name', help='Filter by site name')
    list_parser.add_argument('--controller', help='Filter by controller URL')
    
    # Info command
    info_parser = subparsers.add_parser('info', help='Show backup details')
    info_parser.add_argument('backup_id', help='Backup ID to inspect')
    
    # Rollback command
    rollback_parser = subparsers.add_parser('rollback', help='Perform rollback')
    rollback_parser.add_argument('backup_id', help='Backup ID to rollback to')
    rollback_parser.add_argument('--dry-run', action='store_true', 
                                help='Show what would be restored without making changes')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a backup')
    delete_parser.add_argument('backup_id', help='Backup ID to delete')
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old backups')
    cleanup_parser.add_argument('--days', type=int, default=30,
                               help='Number of days to keep backups (default: 30)')
    cleanup_parser.add_argument('--config-type', help='Filter by configuration type')
    
    args = parser.parse_args()
    
    # Set up logging
    if args.verbose:
        setup_logging(logging.DEBUG)
    else:
        setup_logging(logging.INFO)
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        if args.command == 'list':
            backups = list_available_backups(
                config_type=args.config_type,
                site_name=args.site_name,
                controller_url=args.controller
            )
            
            if not backups:
                logger.info("No backups found")
                return
            
            logger.info(f"Found {len(backups)} backup(s):")
            for backup in backups:
                print(format_backup_info(backup))
        
        elif args.command == 'info':
            backup_data = get_backup_data(args.backup_id)
            if not backup_data:
                logger.error(f"Backup {args.backup_id} not found")
                sys.exit(1)
            
            logger.info("Backup Details:")
            print(json.dumps(backup_data, indent=2, ensure_ascii=False))
        
        elif args.command == 'rollback':
            success = perform_rollback(args.backup_id, args.dry_run)
            if not success:
                sys.exit(1)
        
        elif args.command == 'delete':
            success = delete_config_backup(args.backup_id)
            if success:
                logger.info(f"Backup {args.backup_id} deleted successfully")
            else:
                logger.error(f"Failed to delete backup {args.backup_id}")
                sys.exit(1)
        
        elif args.command == 'cleanup':
            deleted_count = cleanup_old_backups(args.days, args.config_type)
            logger.info(f"Cleanup completed. Deleted {deleted_count} backup(s)")
    
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Command failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    import shutil
    main()
