# UniFi Python Module

A robust Python module for interacting with UniFi Network controllers, supporting both legacy (pre-9.5) and modern (9.5+) API versions with automatic endpoint detection and fallback.

## 🚀 Features

- **Multi-Version Support**: Works with UniFi 7.x, 8.x, 9.5+ controllers
- **Automatic API Detection**: Automatically detects and uses the correct API endpoints
- **Multiple Authentication Methods**: API key, username/password, and MFA support
- **Resource Management**: Full CRUD operations for all UniFi resources
- **Backward Compatible**: Existing code works without changes
- **Future-Proof**: Easy to extend for new UniFi versions

## 📋 Table of Contents

- [UniFi API Versions](#unifi-api-versions)
- [Authentication Methods](#authentication-methods)
- [Getting Started](#getting-started)
- [API Key Setup (UniFi 9.5+)](#api-key-setup-unifi-95)
- [Usage Examples](#usage-examples)
- [Resource Management](#resource-management)
- [Error Handling](#error-handling)
- [Migration Guide](#migration-guide)

## 🔀 UniFi API Versions

### Legacy API (Pre-9.5)
UniFi controllers before version 9.5 used a direct REST API pattern:

```
/api/s/{site}/rest/{resource}     # Resource operations (portconf, networkconf, etc.)
/api/self/sites                   # List sites
/api/auth/login                   # Authentication
```

**Characteristics:**
- Direct URL paths without proxy prefix
- Session-based authentication only
- JSON responses with `meta.rc` status pattern
- Single API pattern for all resources

### Modern API (9.5+)
UniFi 9.5+ introduced multiple API patterns with enhanced security:

```
# Resource Operations (REST-style)
/proxy/network/api/s/{site}/rest/{resource}    # Most resources (portconf, networkconf, etc.)
/proxy/network/v2/api/site/{site}/{resource}    # New v2 resources (apgroups, etc.)

# Sites Management
/proxy/network/integration/v1/sites             # API key authentication
/proxy/network/api/self/sites                   # Session authentication  
/proxy/network/v2/api/site                       # V2 session authentication

# Authentication
/api/auth/login                                  # Enhanced login with MFA support
```

**Characteristics:**
- Proxy-based URL patterns for better security
- Multiple API patterns (REST, V2, Integration)
- Both API key and session authentication
- Enhanced MFA support
- Better error handling and response formats

## 🔐 Authentication Methods

### 1. API Key Authentication (Recommended for 9.5+)
- **Most secure** method
- **No session expiration**
- **Full API access**
- **Requires UniFi 9.5+**

### 2. Session Authentication (All Versions)
- **Username/password** with optional MFA
- **Session expires** after inactivity
- **Works with all UniFi versions**
- **Automatic session management**

## 🚀 Getting Started

### Installation

```bash
# Clone the repository
git clone https://github.com/mrzepa/unifi_config_sync.git
cd unifi_site_sync

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

```python
from unifi.unifi import Unifi
from unifi.portconf import PortConf

# Initialize with API key (UniFi 9.5+)
unifi = Unifi(
    base_url="https://unifi.example.com:8443",
    api_key="your-api-key-here"
)

# Or with username/password and MFA (all versions)
unifi = Unifi(
    base_url="https://unifi.example.com:8443", 
    username="admin",
    password="password",
    mfa_secret="your-mfa-secret" 
)

# Get sites
sites = unifi.get_sites()
print(f"Found {len(sites)} sites")

# Work with a specific site
site = unifi.site("Default")
port_conf = PortConf(unifi, site)

# Get all port profiles
profiles = port_conf.all()
print(f"Found {len(profiles)} port profiles")
```

## 🔑 API Key Setup (UniFi 9.5+)

### Step 1: Access UniFi Controller

1. Open your UniFi Controller web interface
2. Log in with administrator credentials
3. Navigate to **Settings** → **Control Plane** → **Integrations**

### Step 2: Create API Key

1. Click **Create API Key**
2. Give the API key a descriptive name (e.g., "Python Scripts")
3. Set the expiration date (e.g., 1 year)


### Step 3: Copy and Secure API Key

1. **Copy the API key immediately** - it won't be shown again
2. Store it securely (environment variables, config files, etc.)
3. Never commit API keys to version control

### Step 4: Test API Key

```python
from unifi.unifi import Unifi

# Test the API key
unifi = Unifi(
    base_url="https://unifi.example.com:8443",
    api_key="your-copied-api-key"
)

try:
    sites = unifi.get_sites()
    print(f"✅ API key works! Found {len(sites)} sites")
except Exception as e:
    print(f"❌ API key failed: {e}")
```

### Environment Variable Setup (Recommended)

```bash
# Add to your shell profile (.bashrc, .zshrc, etc.)
export UNIFI_API_KEY="your-api-key-here"
export UNIFI_BASE_URL="https://unifi.example.com:8443"

# Or use .env file
echo "UNIFI_API_KEY=your-api-key-here" > .env
echo "UNIFI_BASE_URL=https://unifi.example.com:8443" >> .env
```

```python
# Load from environment
import os
from dotenv import load_dotenv

load_dotenv()

unifi = Unifi(
    base_url=os.getenv("UNIFI_BASE_URL"),
    api_key=os.getenv("UNIFI_API_KEY")
)
```

## 📚 Usage Examples

### Port Profile Management

```python
from unifi.portconf import PortConf

# Initialize
site = unifi.site("Default")
port_conf = PortConf(unifi, site)

# Get all port profiles
profiles = port_conf.all()

# Get specific profile by name
management_profile = port_conf.get(name="Management")

# Create new port profile
new_profile = {
    "name": "New Profile",
    "port_security": {
        "mac_filter": False,
        "mac_filter_list": []
    }
}
created = port_conf.create(data=new_profile)

# Update existing profile
updated_data = {"name": "Updated Profile"}
port_conf.update(data=updated_data)

# Delete profile
port_conf.delete(item_id="profile-id-here")
```

### Network Configuration

```python
from unifi.networkconf import NetworkConf

network_conf = NetworkConf(unifi, site)

# Get all networks
networks = network_conf.all()

# Create VLAN network
vlan_network = {
    "name": "Guest VLAN 100",
    "purpose": "corporate",
    "subnet": "192.168.100.1/24",
    "vlan_id": 100,
    "dhcpd_enabled": True,
    "dhcpd_start": "192.168.100.10",
    "dhcpd_stop": "192.168.100.200"
}
network_conf.create(data=vlan_network)
```

### Device Management

```python
from unifi.device import Device

device_manager = Device(unifi, site)

# Get all devices
devices = device_manager.all()

# Find specific device
switch = device_manager.get(name="Main Switch")

# Get device by MAC
device = device_manager.get(mac="00:11:22:33:44:55")
```

## 🛠 Resource Management

### Available Resources

| Resource | Class | Legacy API | 9.5+ REST | 9.5+ V2 | Description |
|----------|-------|------------|-----------|---------|-------------|
| Port Profiles | `PortConf` | ✅ | ✅ | ❌ | Switch port configurations |
| Networks | `NetworkConf` | ✅ | ✅ | ❌ | Network/VLAN settings |
| RADIUS Profiles | `RadiusProfile` | ✅ | ✅ | ❌ | RADIUS authentication |
| User Groups | `UserGroup` | ✅ | ✅ | ❌ | User group policies |
| WiFi Settings | `WlanConf` | ✅ | ✅ | ❌ | Wireless network configs |
| System Settings | `Setting` | ✅ | ✅ | ❌ | Global controller settings |
| Devices | `Device` | ✅ | ✅ | ❌ | Switches, APs, gateways |
| AP Groups | `ApGroups` | ❌ | ❌ | ✅ | Access point groups |

### CRUD Operations

All resources support standard CRUD operations:

```python
# Create
resource.create(data=config_data)

# Read all
all_items = resource.all()

# Read specific
item = resource.get(name="Item Name")
item = resource.get(id="item-id")

# Update
resource.update(data=updated_config)

# Delete
resource.delete(item_id="item-id")
```

## ⚠️ Error Handling

The module provides comprehensive error handling:

```python
from unifi.unifi import Unifi
from unifi.exceptions import AuthenticationError, EndpointNotFoundError

try:
    unifi = Unifi(base_url, api_key="invalid-key")
    sites = unifi.get_sites()
except AuthenticationError as e:
    print(f"Authentication failed: {e}")
except EndpointNotFoundError as e:
    print(f"Endpoint not available: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

### Common Error Scenarios

1. **401 Unauthorized**: Check API key or credentials
2. **404 Not Found**: Controller doesn't support that endpoint
3. **Connection Error**: Network connectivity or SSL issues
4. **JSON Decode Error**: Invalid API response

## 🔄 Migration Guide

### From Legacy to 9.5+

**No code changes required!** The module automatically detects the UniFi version and uses appropriate endpoints.

```python
# This works on ALL UniFi versions
unifi = Unifi(base_url, username, password)
sites = unifi.get_sites()  # Automatic endpoint detection
```

### Recommended: Upgrade to API Keys

For UniFi 9.5+, consider upgrading to API key authentication:

```python
# Old way (still works)
unifi = Unifi(base_url, username, password, mfa_secret)

# New way (recommended for 9.5+)
unifi = Unifi(base_url, api_key="your-api-key")
```

**Benefits of API Keys:**
- No session expiration
- More secure (no password in scripts)
- Better performance
- Full API access

## 🔧 Advanced Configuration

### Custom Timeout and Retry

```python
unifi = Unifi(
    base_url="https://unifi.example.com:8443",
    api_key="your-api-key",
    timeout=30,  # Connection timeout in seconds
    max_retries=5  # Number of retry attempts
)
```

### SSL Verification

```python
# Disable SSL verification (not recommended for production)
unifi = Unifi(
    base_url="https://unifi.example.com:8443",
    api_key="your-api-key",
    verify_ssl=False
)

# Custom SSL certificate
unifi = Unifi(
    base_url="https://unifi.example.com:8443", 
    api_key="your-api-key",
    verify_ssl="/path/to/cert.pem"
)
```

### Debug Logging

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("unifi")

# Now all API calls will be logged
unifi = Unifi(base_url, api_key="your-api-key")
```

## 📝 Troubleshooting

### Common Issues

**Q: Getting "401 Unauthorized" with API key**
- Verify the API key is correct
- Check that the key has sufficient permissions
- Ensure you're using UniFi 9.5+

**Q: Sites endpoint returns 404**
- The module automatically tries multiple endpoints
- Check the debug logs to see which endpoints were tried
- Older controllers may not support all endpoint patterns

**Q: SSL certificate errors**
- Use `verify_ssl=False` for testing (not recommended for production)
- Provide proper SSL certificate path
- Check controller certificate validity

**Q: MFA authentication fails**
- Ensure MFA secret is correct (Base32 format)
- Check that system time is synchronized
- Verify MFA is enabled for the admin account

### Debug Mode

Enable detailed logging to troubleshoot issues:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# This will show:
# - Which endpoints are being tried
# - Authentication attempts
# - Response status codes
# - API version detection
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

### Adding New Resources

To add support for a new UniFi resource:

1. Create resource class in `unifi/newresource.py`
2. Add endpoint mappings to `unifi/endpoints.py`
3. Implement resource-specific methods if needed

```python
# unifi/newresource.py
from unifi.resources import BaseResource

class NewResource(BaseResource):
    def __init__(self, unifi, site, **kwargs):
        super().__init__(unifi, endpoint='newresource', site=site, **kwargs)
    
    def custom_method(self):
        # Resource-specific functionality
        pass
```

```python
# unifi/endpoints.py
RESOURCE_ENDPOINTS = {
    'newresource': {
        APIVersion.LEGACY_REST: '/api/s/{site}/rest/newresource',
        APIVersion.PROXY_REST: '/proxy/network/api/s/{site}/rest/newresource',
        APIVersion.PROXY_V2: '/proxy/network/v2/api/site/{site}/newresource',
    },
}
```

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

If you encounter issues:

1. Check the troubleshooting section above
2. Enable debug logging and review the output
3. Search existing issues on GitHub
4. Create a new issue with:
   - UniFi controller version
   - Python version
   - Debug logs
   - Error messages

## 🔗 Related Resources

- [UniFi API Documentation](https://ui.com/ui-api)
- [UniFi Network Controller Downloads](https://www.ui.com/download/unifi)
- [Python Requests Library](https://docs.python-requests.org/)
- [UniFi Community Forums](https://community.ui.com/)
