#!/usr/bin/env python3
"""
AP Group Manager - Handles creation and management of UniFi AP groups.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class APGroupManager:
    """Manages UniFi AP groups including creation and AP movement."""
    
    def __init__(self, unifi, site):
        """
        Initialize AP Group Manager.
        
        Args:
            unifi: UniFi controller instance
            site: UniFi site instance
        """
        self.unifi = unifi
        self.site = site
    
    def get_existing_ap_groups(self) -> Dict[str, str]:
        """
        Get all existing AP groups in the site.
        
        Returns:
            Dictionary mapping AP group names to their IDs
        """
        try:
            ap_groups = self.site.ap_groups.all()
            return {ag.get("name"): ag.get("_id") for ag in ap_groups}
        except Exception as e:
            logger.error(f"Failed to get AP groups: {e}")
            return {}
    
    def create_ap_group(self, group_name: str) -> Optional[str]:
        """
        Create a new AP group.
        
        Args:
            group_name: Name of the AP group to create
            
        Returns:
            AP group ID if successful, None otherwise
        """
        try:
            # Check if AP group already exists
            existing_groups = self.get_existing_ap_groups()
            if group_name in existing_groups:
                logger.info(f"AP group '{group_name}' already exists in site '{self.site.name}'")
                return existing_groups[group_name]
            
            # Create new AP group with required fields
            ap_group_data = {
                "name": group_name,
                "site_id": self.site._id,
                "deviceMACs": []  # Required field - must be an array, not null
            }
            
            logger.info(f"Creating AP group '{group_name}' in site '{self.site.name}'")
            response = self.site.ap_groups.create(ap_group_data)
            
            if response and response.get('meta', {}).get('rc') == 'ok':
                ap_group_id = response.get('data', [{}])[0].get('_id')
                logger.info(f"Successfully created AP group '{group_name}' with ID: {ap_group_id}")
                return ap_group_id
            else:
                logger.error(f"Failed to create AP group '{group_name}': {response}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating AP group '{group_name}': {e}")
            return None
    
    def get_site_devices(self) -> List[Dict]:
        """
        Get all devices (APs) in the site.
        
        Returns:
            List of device dictionaries
        """
        try:
            devices = self.site.device.all()
            # Filter for access points only
            ap_devices = [device for device in devices if device.get('type') == 'uap']
            return ap_devices
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return []
    
    def move_aps_to_group(self, target_group_name: str, source_group_name: Optional[str] = None) -> bool:
        """
        Move APs from source group to target group.
        
        Args:
            target_group_name: Name of the target AP group
            source_group_name: Name of the source AP group (if None, moves all APs not in target)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get existing AP groups
            existing_groups = self.get_existing_ap_groups()
            
            if target_group_name not in existing_groups:
                logger.error(f"Target AP group '{target_group_name}' does not exist")
                return False
            
            target_group_id = existing_groups[target_group_name]
            
            # Get all AP devices
            ap_devices = self.get_site_devices()
            
            if not ap_devices:
                logger.warning(f"No AP devices found in site '{self.site.name}'")
                return True  # Not an error, just no APs to move
            
            moved_count = 0
            error_count = 0
            
            for device in ap_devices:
                try:
                    device_id = device.get('_id')
                    device_name = device.get('name', 'Unknown')
                    current_ap_group_id = device.get('ap_group_id')
                    
                    # Skip if already in target group
                    if current_ap_group_id == target_group_id:
                        logger.debug(f"AP '{device_name}' already in target group '{target_group_name}'")
                        continue
                    
                    # If source group specified, only move APs from that group
                    if source_group_name:
                        if source_group_name not in existing_groups:
                            logger.warning(f"Source AP group '{source_group_name}' does not exist, skipping")
                            continue
                        source_group_id = existing_groups[source_group_name]
                        if current_ap_group_id != source_group_id:
                            logger.debug(f"AP '{device_name}' not in source group '{source_group_name}', skipping")
                            continue
                    
                    # Move AP to target group
                    update_data = {
                        "ap_group_id": target_group_id
                    }
                    
                    logger.debug(f"Moving AP '{device_name}' to group '{target_group_name}'")
                    response = self.site.device.update(update_data, device_id)
                    
                    if response and response.get('meta', {}).get('rc') == 'ok':
                        moved_count += 1
                        logger.info(f"Successfully moved AP '{device_name}' to group '{target_group_name}'")
                    else:
                        error_count += 1
                        logger.error(f"Failed to move AP '{device_name}': {response}")
                        
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error moving AP device: {e}")
            
            logger.info(f"AP movement completed: {moved_count} moved, {error_count} errors")
            return error_count == 0
            
        except Exception as e:
            logger.error(f"Error moving APs to group '{target_group_name}': {e}")
            return False
    
    def ensure_ap_group_exists(self, group_name: str, move_aps: bool = True, source_group: Optional[str] = None) -> Optional[str]:
        """
        Ensure an AP group exists, creating it if necessary, and optionally move APs to it.
        
        Args:
            group_name: Name of the AP group to ensure exists
            move_aps: Whether to move APs to this group
            source_group: Source group to move APs from (if None, moves from wrong groups)
            
        Returns:
            AP group ID if successful, None otherwise
        """
        try:
            # Create AP group if it doesn't exist
            ap_group_id = self.create_ap_group(group_name)
            if not ap_group_id:
                return None
            
            # Move APs if requested
            if move_aps:
                success = self.move_aps_to_group(group_name, source_group)
                if not success:
                    logger.warning(f"AP group '{group_name}' created but failed to move some APs")
            
            return ap_group_id
            
        except Exception as e:
            logger.error(f"Error ensuring AP group '{group_name}' exists: {e}")
            return None

    def get_site_ap_count(self) -> int:
        """
        Get the number of AP devices in the site.
        
        Returns:
            Number of AP devices
        """
        try:
            ap_devices = self.get_site_devices()
            return len(ap_devices)
        except Exception as e:
            logger.error(f"Failed to get AP count: {e}")
            return 0
    
    def can_create_custom_ap_groups(self) -> bool:
        """
        Check if the site can create custom AP groups (requires 2+ APs).
        
        Returns:
            True if custom AP groups can be created, False otherwise
        """
        ap_count = self.get_site_ap_count()
        return ap_count >= 2
    
    def get_default_ap_group(self) -> Optional[str]:
        """
        Get the default "All APs" AP group ID.
        
        Returns:
            Default AP group ID if found, None otherwise
        """
        try:
            existing_groups = self.get_existing_ap_groups()
            
            # Look for common default AP group names
            default_names = ["All APs", "Default", "All APs (default)"]
            
            for name in default_names:
                if name in existing_groups:
                    logger.debug(f"Found default AP group '{name}' with ID: {existing_groups[name]}")
                    return existing_groups[name]
            
            # If no standard default found, use the first available AP group
            if existing_groups:
                first_group_name = list(existing_groups.keys())[0]
                first_group_id = existing_groups[first_group_name]
                logger.info(f"Using first available AP group '{first_group_name}' as default")
                return first_group_id
            
            logger.warning("No AP groups found in site")
            return None
            
        except Exception as e:
            logger.error(f"Error getting default AP group: {e}")
            return None

    def ensure_ap_group_for_wlan(self, required_ap_group: str) -> Optional[str]:
        """
        Ensure an AP group exists for a WLAN configuration.
        For single AP sites, uses the default AP group.
        For multi-AP sites, creates the required AP group if needed.
        
        Args:
            required_ap_group: Name of the AP group required by the WLAN
            
        Returns:
            AP group ID if successful, None otherwise
        """
        try:
            # Check if we can create custom AP groups
            if not self.can_create_custom_ap_groups():
                logger.info(f"Site '{self.site.name}' has only {self.get_site_ap_count()} AP(s). Using default AP group instead of creating '{required_ap_group}'")
                return self.get_default_ap_group()
            
            # For multi-AP sites, create the AP group if it doesn't exist
            existing_groups = self.get_existing_ap_groups()
            if required_ap_group in existing_groups:
                logger.info(f"AP group '{required_ap_group}' already exists in site '{self.site.name}'")
                return existing_groups[required_ap_group]
            
            # Create the AP group
            ap_group_id = self.create_ap_group(required_ap_group)
            if ap_group_id:
                # Move APs to the new group
                self.move_aps_to_group(required_ap_group)
                return ap_group_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error ensuring AP group '{required_ap_group}' for site '{self.site.name}': {e}")
            return None

def ensure_ap_group_for_wlan(unifi, site_name: str, required_ap_group: str) -> Optional[str]:
    """
    Convenience function to ensure an AP group exists for a WLAN configuration.
    
    Args:
        unifi: UniFi controller instance
        site_name: Name of the site
        required_ap_group: Name of the AP group required by the WLAN
        
    Returns:
        AP group ID if successful, None otherwise
    """
    try:
        if site_name not in unifi.sites:
            logger.error(f"Site '{site_name}' not found")
            return None
        
        site = unifi.sites[site_name]
        manager = APGroupManager(unifi, site)
        
        # Use the new smart AP group logic
        return manager.ensure_ap_group_for_wlan(required_ap_group)
        
    except Exception as e:
        logger.error(f"Error ensuring AP group '{required_ap_group}' for site '{site_name}': {e}")
        return None
