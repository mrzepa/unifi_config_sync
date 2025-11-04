#!/usr/bin/env python3
"""
Test script to demonstrate configuration dependency management and rollback functionality.

This script provides examples of how the dependency system works and how to use rollback features.
"""

import logging
from config_dependencies import dependency_manager, validate_config_dependencies, get_deployment_order
from rollback_manager import rollback_manager, create_config_backup, list_available_backups

def test_dependency_validation():
    """Test configuration dependency validation."""
    print("=== Testing Smart Configuration Dependency Validation ===\n")
    
    # Test smart validation (default behavior) - should always pass
    print("1. Testing smart dependency validation (default behavior):")
    configs = ['wlan_conf']  # WLAN without network_conf in deployment list
    result = validate_config_dependencies(configs, check_existing_resources=True)
    
    if result:
        print("   ✅ Smart validation passed - will check existing resources on target sites")
        print("   💡 This allows deploying WLAN configs when VLANs already exist on the controller")
    else:
        print("   ❌ Smart validation failed")
    
    # Test strict validation - should fail for missing dependencies
    print("\n2. Testing strict dependency validation:")
    configs = ['wlan_conf']  # WLAN without network_conf in deployment list
    result = validate_config_dependencies(configs, check_existing_resources=False)
    
    if result:
        print("   ✅ Strict validation passed")
    else:
        print("   ❌ Strict validation failed - requires all dependencies to be included")
        print("   💡 WLAN requires: network_conf, radius_profiles")
    
    # Test deployment ordering
    print("\n3. Testing deployment ordering (still used for consistency):")
    configs = ['wlan_conf', 'network_conf', 'port_profiles', 'radius_profiles']
    ordered = get_deployment_order(configs)
    print(f"   Input order: {configs}")
    print(f"   Processing order: {ordered}")
    print("   ✅ Dependencies resolved automatically (even with smart validation)")

def test_dependency_chain():
    """Show the complete dependency chain."""
    print("\n=== Complete Dependency Chain ===\n")
    
    summary = dependency_manager.get_dependency_summary(['network_conf', 'radius_profiles', 'port_profiles', 'wlan_conf'])
    print(summary)

def test_rollback_system():
    """Test rollback system functionality."""
    print("\n=== Testing Rollback System ===\n")
    
    # Create a test backup
    print("1. Creating test backup:")
    test_configs = [
        {
            "name": "Test-VLAN",
            "vlan": 100,
            "purpose": "Test VLAN for rollback demo"
        },
        {
            "name": "Another-VLAN", 
            "vlan": 200,
            "purpose": "Another test VLAN"
        }
    ]
    
    backup_id = create_config_backup(
        'network_conf', 
        'Test-Site', 
        'https://test-controller:8443',
        test_configs,
        'test-operation'
    )
    
    print(f"   ✅ Created backup: {backup_id}")
    
    # List available backups
    print("\n2. Listing available backups:")
    backups = list_available_backups(config_type='network_conf')
    for backup in backups[:3]:  # Show first 3 backups
        print(f"   📦 {backup['backup_id']}")
        print(f"      Created: {backup['timestamp']}")
        print(f"      Site: {backup['site_name']}")
        print(f"      Configs: {backup['config_count']}")
    
    # Retrieve backup data
    print("\n3. Retrieving backup data:")
    backup_data = rollback_manager.get_backup(backup_id)
    if backup_data:
        print(f"   ✅ Retrieved backup with {len(backup_data['configurations'])} configurations")
        for config in backup_data['configurations']:
            print(f"      - {config['name']} (VLAN {config['vlan']})")
    else:
        print("   ❌ Failed to retrieve backup")
    
    # Clean up test backup
    print("\n4. Cleaning up test backup:")
    if rollback_manager.delete_backup(backup_id):
        print(f"   ✅ Deleted test backup: {backup_id}")
    else:
        print(f"   ❌ Failed to delete test backup")

def test_site_dependency_validation():
    """Test site-specific dependency validation."""
    print("\n=== Testing Site Dependency Validation ===\n")
    
    # Mock site data
    site_data = {
        'vlans': {
            'Corporate-VLAN': 'vlan_id_123',
            'Guest-VLAN': 'vlan_id_456'
        },
        'radius_profiles': {
            'Corporate-RADIUS': 'radius_id_789'
        },
        'user_groups': {
            'Corporate-Users': 'group_id_101'
        },
        'ap_groups': {
            'Building-A-APs': 'apgroup_id_202'
        }
    }
    
    # Test valid WLAN configuration
    print("1. Testing valid WLAN configuration:")
    valid_wlan = {
        'name': 'Corporate-WiFi',
        'networkconf_vlan_name': 'Corporate-VLAN',
        'radiusprofile_id_name': 'Corporate-RADIUS',
        'user_group_id_name': 'Corporate-Users'
    }
    
    missing_deps = dependency_manager.check_config_references('wlan_conf', valid_wlan, site_data)
    if missing_deps:
        print(f"   ❌ Missing dependencies: {missing_deps}")
    else:
        print("   ✅ All dependencies satisfied")
    
    # Test invalid WLAN configuration
    print("\n2. Testing invalid WLAN configuration:")
    invalid_wlan = {
        'name': 'Invalid-WiFi',
        'networkconf_vlan_name': 'Nonexistent-VLAN',
        'radiusprofile_id_name': 'Missing-RADIUS'
    }
    
    missing_deps = dependency_manager.check_config_references('wlan_conf', invalid_wlan, site_data)
    if missing_deps:
        print(f"   ❌ Missing dependencies: {missing_deps}")
        print("   💡 These resources must exist in the target site before deployment")
    else:
        print("   ✅ All dependencies satisfied")

def main():
    """Run all tests."""
    print("🧪 UniFi Configuration Dependencies & Rollback Tests\n")
    print("=" * 60)
    
    # Set up logging for tests
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    try:
        test_dependency_validation()
        test_dependency_chain()
        test_rollback_system()
        test_site_dependency_validation()
        
        print("\n" + "=" * 60)
        print("✅ All tests completed successfully!")
        print("\n💡 Key Takeaways:")
        print("   • 🧠 Smart dependency validation is now enabled by default")
        print("   • 🔍 System checks if dependencies already exist on target sites")
        print("   • ⚡ No need to deploy VLANs that already exist on the controller")
        print("   • 🎯 Site-specific validation ensures resources exist per site")
        print("   • 🔄 Automatic backups are created before making changes")
        print("   • 📋 Manual rollback is available via rollback.py CLI")
        print("\n🚀 Smart Validation Benefits:")
        print("   • Deploy WLAN configs when VLANs already exist")
        print("   • Faster deployments - skip what's already there")
        print("   • Reduced risk - fewer unnecessary changes")
        print("   • Flexible - works with existing infrastructure")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
