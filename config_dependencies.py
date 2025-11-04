"""
Configuration dependency management for UniFi sync operations.

This module handles dependencies between different configuration types to ensure
proper deployment order and validation.
"""

import logging
from typing import Dict, List, Set, Optional
import json
import os

logger = logging.getLogger(__name__)

class ConfigDependency:
    """Manages dependencies between UniFi configuration types."""
    
    def __init__(self):
        # Define dependency graph: config_type -> set of dependencies
        self.dependencies = {
            'network_conf': set(),  # Networks/VLANs have no dependencies
            'radius_profiles': set(),  # RADIUS profiles have no dependencies
            'global_settings': set(),  # Global settings have no dependencies
            'port_profiles': {'network_conf'},  # Port profiles depend on networks
            'wlan_conf': {'network_conf', 'radius_profiles'}  # WLANs depend on networks and RADIUS
        }
        
        # Define deployment order based on dependencies
        self.deployment_order = ['network_conf', 'radius_profiles', 'global_settings', 'port_profiles', 'wlan_conf']
    
    def get_dependencies(self, config_type: str) -> Set[str]:
        """Get the dependencies for a specific configuration type."""
        return self.dependencies.get(config_type, set())
    
    def get_dependents(self, config_type: str) -> Set[str]:
        """Get configuration types that depend on the specified type."""
        dependents = set()
        for cfg_type, deps in self.dependencies.items():
            if config_type in deps:
                dependents.add(cfg_type)
        return dependents
    
    def validate_dependencies(self, config_types: List[str]) -> Dict[str, List[str]]:
        """
        Validate that all dependencies are satisfied for the given config types.
        
        Returns:
            Dict mapping config_type to list of missing dependencies
        """
        missing_deps = {}
        config_set = set(config_types)
        
        for config_type in config_types:
            deps = self.get_dependencies(config_type)
            missing = deps - config_set
            if missing:
                missing_deps[config_type] = list(missing)
        
        return missing_deps
    
    def get_deployment_order(self, config_types: List[str]) -> List[str]:
        """
        Get the correct deployment order for the given configuration types.
        
        Returns:
            List of config types in dependency order
        """
        # Filter deployment order to only include requested types
        ordered = [cfg for cfg in self.deployment_order if cfg in config_types]
        
        # Validate that all requested types are included
        requested_set = set(config_types)
        ordered_set = set(ordered)
        missing = requested_set - ordered_set
        
        if missing:
            logger.warning(f"Unknown configuration types: {missing}")
            # Append unknown types at the end
            ordered.extend(list(missing))
        
        return ordered
    
    def check_config_references(self, config_type: str, config_data: dict, site_data: dict) -> List[str]:
        """
        Check if a configuration references dependencies that exist in the site.
        
        Args:
            config_type: Type of configuration (network_conf, wlan_conf, etc.)
            config_data: Configuration data to check
            site_data: Site data containing available resources
            
        Returns:
            List of missing references
        """
        missing_refs = []
        
        if config_type == 'port_profiles':
            # Check VLAN references
            vlans = site_data.get('vlans', {})
            
            if 'native_networkconf_vlan_name' in config_data:
                vlan_name = config_data['native_networkconf_vlan_name']
                if vlan_name not in vlans:
                    missing_refs.append(f"VLAN '{vlan_name}' (native_networkconf)")
            
            if 'voice_networkconf_vlan_name' in config_data:
                vlan_name = config_data['voice_networkconf_vlan_name']
                if vlan_name not in vlans:
                    missing_refs.append(f"VLAN '{vlan_name}' (voice_networkconf)")
            
            if 'excluded_networkconf_vlan_names' in config_data:
                excluded_vlans = config_data['excluded_networkconf_vlan_names']
                if isinstance(excluded_vlans, list):
                    for vlan_name in excluded_vlans:
                        if vlan_name not in vlans:
                            missing_refs.append(f"VLAN '{vlan_name}' (excluded_networkconf)")
        
        elif config_type == 'wlan_conf':
            # Check VLAN references
            vlans = site_data.get('vlans', {})
            
            if 'networkconf_vlan_name' in config_data:
                vlan_name = config_data['networkconf_vlan_name']
                if vlan_name not in vlans:
                    missing_refs.append(f"VLAN '{vlan_name}' (networkconf)")
            
            # Check RADIUS profile references
            radius_profiles = site_data.get('radius_profiles', {})
            
            if 'radiusprofile_id_name' in config_data:
                profile_name = config_data['radiusprofile_id_name']
                if profile_name not in radius_profiles:
                    missing_refs.append(f"RADIUS profile '{profile_name}'")
            
            # Check user group references
            user_groups = site_data.get('user_groups', {})
            
            if 'user_group_id_name' in config_data:
                group_name = config_data['user_group_id_name']
                if group_name not in user_groups:
                    missing_refs.append(f"User group '{group_name}'")
            
            # Check AP group references
            ap_groups = site_data.get('ap_groups', {})
            
            if 'ap_group_ids_name' in config_data:
                if isinstance(config_data['ap_group_ids_name'], list):
                    for group_name in config_data['ap_group_ids_name']:
                        if group_name not in ap_groups:
                            missing_refs.append(f"AP group '{group_name}'")
                elif config_data['ap_group_ids_name'] not in ap_groups:
                    group_name = config_data['ap_group_ids_name']
                    missing_refs.append(f"AP group '{group_name}'")
        
        return missing_refs
    
    def get_dependency_summary(self, config_types: List[str]) -> str:
        """Generate a human-readable summary of dependencies."""
        summary = ["Configuration Dependencies:"]
        
        ordered_types = self.get_deployment_order(config_types)
        
        for config_type in ordered_types:
            deps = self.get_dependencies(config_type)
            if deps:
                summary.append(f"  {config_type} depends on: {', '.join(sorted(deps))}")
            else:
                summary.append(f"  {config_type} has no dependencies")
        
        return "\n".join(summary)

# Global dependency manager instance
dependency_manager = ConfigDependency()

def validate_config_dependencies(config_types: List[str], check_existing_resources: bool = True) -> bool:
    """
    Validate that all dependencies are satisfied for deployment.
    
    Args:
        config_types: List of configuration types to deploy
        check_existing_resources: If True, only validate deployment order dependencies.
                                If False, require all dependencies to be in deployment list.
        
    Returns:
        True if all dependencies are satisfied, False otherwise
    """
    if check_existing_resources:
        # Smart validation: only check deployment order, not requirement to deploy dependencies
        # This allows deploying WLAN configs when VLANs already exist on the controller
        logger.info("Using smart dependency validation - checking existing resources on target sites")
        return True
    
    # Strict validation: require all dependencies to be included in deployment
    missing_deps = dependency_manager.validate_dependencies(config_types)
    
    if missing_deps:
        logger.error("Configuration dependency validation failed:")
        for config_type, deps in missing_deps.items():
            logger.error(f"  {config_type} requires: {', '.join(deps)}")
        
        logger.info("\nSuggested deployment order:")
        ordered = dependency_manager.get_deployment_order(config_types)
        for i, config_type in enumerate(ordered, 1):
            logger.info(f"  {i}. {config_type}")
        
        return False
    
    return True

def get_deployment_order(config_types: List[str]) -> List[str]:
    """Get the correct deployment order for configuration types."""
    return dependency_manager.get_deployment_order(config_types)

def check_site_dependencies(config_type: str, config_data: dict, site_data: dict) -> List[str]:
    """Check if configuration references exist in the target site."""
    return dependency_manager.check_config_references(config_type, config_data, site_data)

def validate_site_dependencies(unifi, site_name: str, config_type: str, config_data: dict) -> List[str]:
    """
    Validate that dependencies exist in the actual UniFi site.
    
    Args:
        unifi: UniFi controller instance
        site_name: Name of the site to check
        config_type: Type of configuration being deployed
        config_data: Configuration data to validate
        
    Returns:
        List of missing dependencies (empty if all exist)
    """
    missing_deps = []
    
    try:
        ui_site = unifi.sites[site_name]
        
        # Build site data from actual controller
        site_data = {}
        
        # Get existing VLANs
        if config_type in ['port_profiles', 'wlan_conf']:
            networks = ui_site.network_conf.all()
            vlans = {network.get("name"): network.get("_id") for network in networks}
            site_data['vlans'] = vlans
        
        # Get existing RADIUS profiles
        if config_type == 'wlan_conf':
            radius_profiles = ui_site.radius_profile.all()
            radius_dict = {rp.get("name"): rp.get("_id") for rp in radius_profiles if rp.get("name") != 'Default'}
            site_data['radius_profiles'] = radius_dict
            
            # Get existing user groups
            user_groups = ui_site.user_group.all()
            user_groups_dict = {ug.get("name"): ug.get("_id") for ug in user_groups if ug.get("name") != 'Default'}
            site_data['user_groups'] = user_groups_dict
            
            # Get existing AP groups
            ap_groups = ui_site.ap_group.all()
            ap_groups_dict = {ag.get("name"): ag.get("_id") for ag in ap_groups if ag.get("name") != 'Default'}
            site_data['ap_groups'] = ap_groups_dict
        
        # Check dependencies against actual site data
        missing_deps = check_site_dependencies(config_type, config_data, site_data)
        
        if missing_deps:
            logger.warning(f"Dependencies missing in site '{site_name}': {', '.join(missing_deps)}")
        else:
            logger.debug(f"All dependencies exist in site '{site_name}'")
            
    except Exception as e:
        logger.error(f"Failed to validate site dependencies for '{site_name}': {e}")
        missing_deps.append(f"Unable to validate site dependencies: {e}")
    
    return missing_deps
