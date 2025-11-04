"""
Manual rollback management for UniFi configuration sync operations.

This module provides functionality to create backups before making changes
and manually restore configurations when needed.
"""

import logging
import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Any
import threading

logger = logging.getLogger(__name__)

class RollbackManager:
    """Manages configuration backups and rollbacks for UniFi sync operations."""
    
    def __init__(self, backup_dir: str = None):
        # Use provided backup_dir or default to config.BACKUP_DIR
        if backup_dir is None:
            import config
            backup_dir = config.BACKUP_DIR
        
        self.backup_dir = backup_dir
        self.backup_lock = threading.Lock()
        os.makedirs(backup_dir, exist_ok=True)
    
    def create_backup(self, config_type: str, site_name: str, controller_url: str, 
                     configs: List[Dict[str, Any]], operation: str = "sync") -> str:
        """
        Create a backup of current configurations before making changes.
        
        Args:
            config_type: Type of configuration (network_conf, wlan_conf, etc.)
            site_name: Name of the site
            controller_url: URL of the UniFi controller
            configs: List of current configurations
            operation: Operation being performed (add, replace, delete)
            
        Returns:
            Backup ID that can be used for rollback
        """
        with self.backup_lock:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_controller = controller_url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
            backup_id = f"{config_type}_{site_name}_{safe_controller}_{timestamp}_{operation}"
            
            backup_data = {
                "backup_id": backup_id,
                "timestamp": timestamp,
                "config_type": config_type,
                "site_name": site_name,
                "controller_url": controller_url,
                "operation": operation,
                "configurations": configs
            }
            
            backup_file = os.path.join(self.backup_dir, f"{backup_id}.json")
            
            try:
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, indent=2, ensure_ascii=False)
                
                logger.info(f"Created backup: {backup_id}")
                logger.debug(f"Backup saved to: {backup_file}")
                return backup_id
                
            except Exception as e:
                logger.error(f"Failed to create backup {backup_id}: {e}")
                raise
    
    def get_backup(self, backup_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve backup data by backup ID.
        
        Args:
            backup_id: The backup ID to retrieve
            
        Returns:
            Backup data dictionary or None if not found
        """
        backup_file = os.path.join(self.backup_dir, f"{backup_id}.json")
        
        if not os.path.exists(backup_file):
            logger.error(f"Backup not found: {backup_id}")
            return None
        
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read backup {backup_id}: {e}")
            return None
    
    def list_backups(self, config_type: Optional[str] = None, 
                    site_name: Optional[str] = None,
                    controller_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List available backups with optional filtering.
        
        Args:
            config_type: Filter by configuration type
            site_name: Filter by site name
            controller_url: Filter by controller URL
            
        Returns:
            List of backup metadata
        """
        backups = []
        
        try:
            for filename in os.listdir(self.backup_dir):
                if not filename.endswith('.json'):
                    continue
                
                backup_file = os.path.join(self.backup_dir, filename)
                try:
                    with open(backup_file, 'r', encoding='utf-8') as f:
                        backup_data = json.load(f)
                    
                    # Apply filters
                    if config_type and backup_data.get('config_type') != config_type:
                        continue
                    if site_name and backup_data.get('site_name') != site_name:
                        continue
                    if controller_url and backup_data.get('controller_url') != controller_url:
                        continue
                    
                    # Return metadata without full configurations
                    metadata = {
                        'backup_id': backup_data.get('backup_id'),
                        'timestamp': backup_data.get('timestamp'),
                        'config_type': backup_data.get('config_type'),
                        'site_name': backup_data.get('site_name'),
                        'controller_url': backup_data.get('controller_url'),
                        'operation': backup_data.get('operation'),
                        'config_count': len(backup_data.get('configurations', []))
                    }
                    backups.append(metadata)
                    
                except Exception as e:
                    logger.warning(f"Failed to read backup file {filename}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
        
        # Sort by timestamp (newest first), handling None values
        backups.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
        return backups
    
    def delete_backup(self, backup_id: str) -> bool:
        """
        Delete a backup by backup ID.
        
        Args:
            backup_id: The backup ID to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        backup_file = os.path.join(self.backup_dir, f"{backup_id}.json")
        
        try:
            if os.path.exists(backup_file):
                os.remove(backup_file)
                logger.info(f"Deleted backup: {backup_id}")
                return True
            else:
                logger.warning(f"Backup not found for deletion: {backup_id}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete backup {backup_id}: {e}")
            return False
    
    def cleanup_old_backups(self, days_to_keep: int = 30, 
                           config_type: Optional[str] = None) -> int:
        """
        Clean up old backups beyond the retention period.
        
        Args:
            days_to_keep: Number of days to keep backups
            config_type: Optional filter for specific config type
            
        Returns:
            Number of backups deleted
        """
        cutoff_date = datetime.now().timestamp() - (days_to_keep * 24 * 3600)
        deleted_count = 0
        
        try:
            for filename in os.listdir(self.backup_dir):
                if not filename.endswith('.json'):
                    continue
                
                backup_file = os.path.join(self.backup_dir, filename)
                
                try:
                    # Check file age
                    file_mtime = os.path.getmtime(backup_file)
                    if file_mtime < cutoff_date:
                        # Check config type filter if specified
                        if config_type:
                            with open(backup_file, 'r', encoding='utf-8') as f:
                                backup_data = json.load(f)
                            if backup_data.get('config_type') != config_type:
                                continue
                        
                        os.remove(backup_file)
                        deleted_count += 1
                        logger.debug(f"Deleted old backup: {filename}")
                        
                except Exception as e:
                    logger.warning(f"Failed to process backup file {filename} for cleanup: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Failed to cleanup old backups: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old backups (older than {days_to_keep} days)")
        
        return deleted_count
    
    def export_backup(self, backup_id: str, export_path: str) -> bool:
        """
        Export a backup to a specified path.
        
        Args:
            backup_id: The backup ID to export
            export_path: Path to export the backup file
            
        Returns:
            True if exported successfully, False otherwise
        """
        backup_file = os.path.join(self.backup_dir, f"{backup_id}.json")
        
        if not os.path.exists(backup_file):
            logger.error(f"Backup not found for export: {backup_id}")
            return False
        
        try:
            shutil.copy2(backup_file, export_path)
            logger.info(f"Exported backup {backup_id} to {export_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export backup {backup_id}: {e}")
            return False
    
    def import_backup(self, import_path: str) -> Optional[str]:
        """
        Import a backup from a specified path.
        
        Args:
            import_path: Path to the backup file to import
            
        Returns:
            New backup ID if imported successfully, None otherwise
        """
        if not os.path.exists(import_path):
            logger.error(f"Import file not found: {import_path}")
            return None
        
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            # Validate backup structure
            required_fields = ['backup_id', 'timestamp', 'config_type', 'site_name', 'controller_url', 'configurations']
            for field in required_fields:
                if field not in backup_data:
                    logger.error(f"Invalid backup file: missing field '{field}'")
                    return None
            
            # Generate new backup ID to avoid conflicts
            old_backup_id = backup_data['backup_id']
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_backup_id = f"{backup_data['config_type']}_{backup_data['site_name']}_imported_{timestamp}"
            
            backup_data['backup_id'] = new_backup_id
            backup_data['timestamp'] = timestamp
            backup_data['imported_from'] = old_backup_id
            
            # Save imported backup
            backup_file = os.path.join(self.backup_dir, f"{new_backup_id}.json")
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Imported backup as: {new_backup_id}")
            return new_backup_id
            
        except Exception as e:
            logger.error(f"Failed to import backup from {import_path}: {e}")
            return None

# Global rollback manager instance
rollback_manager = RollbackManager()

def create_config_backup(config_type: str, site_name: str, controller_url: str, 
                        configs: List[Dict[str, Any]], operation: str = "sync") -> str:
    """Create a backup of current configurations."""
    return rollback_manager.create_backup(config_type, site_name, controller_url, configs, operation)

def get_backup_data(backup_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve backup data by backup ID."""
    return rollback_manager.get_backup(backup_id)

def list_available_backups(config_type: Optional[str] = None, 
                          site_name: Optional[str] = None,
                          controller_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """List available backups with optional filtering."""
    return rollback_manager.list_backups(config_type, site_name, controller_url)

def delete_config_backup(backup_id: str) -> bool:
    """Delete a backup by backup ID."""
    return rollback_manager.delete_backup(backup_id)

def cleanup_old_backups(days_to_keep: int = 30, config_type: Optional[str] = None) -> int:
    """Clean up old backups beyond the retention period."""
    return rollback_manager.cleanup_old_backups(days_to_keep, config_type)
