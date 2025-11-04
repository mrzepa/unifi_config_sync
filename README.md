# UniFi Configuration Sync Manager

This project is designed to manage common configuration bits on UniFi network controllers. It reads configurations from a directory, compares them to existing configurations on the UniFi site to keep them in sync.

## Features
- Fetch existing configurations from a UniFi controller
- Add new configurations from a JSON file directory to specified sites
- Replace configurations from a JSON file directory to specified sites
- Delete configurations from specified sites
- Support multiple UniFi controllers and sites handled concurrently for performance
- **UniFi 9.5+ compatibility** with modern authentication and API endpoints
- **Automatic session management** with retry logic for expired sessions
- **Enhanced error handling** for common UniFi API errors
- **Backward compatibility** with older UniFi versions
- **🆕 Configuration dependency management** - Ensures proper deployment order and validates dependencies
- **🆕 Manual rollback system** - Automatic backups before changes with manual rollback capability

---

### Currently Supported Configs to Sync
- **Networks (VLANs)** - Network configuration with VLAN support
- **Port Profiles** - Switch port configuration profiles
- **RADIUS Profiles** - Authentication profiles with automatic IP/secret management
- **WLANs** - Wireless network configurations with AP group handling
- **Global Settings** - Global switch settings (UniFi 9.5+ and legacy support)

---

## Requirements
- Python 3.12+
- Dependencies:
  - `requests`
  - `pyyaml`
  - `pyotp`
  - `python-dotenv`

---

## Setup

### 1. Clone the Repository
Clone this repository to your local machine:
```bash
git clone https://github.com/mrzepa/unifi_config_sync.git
cd unifi_config_sync
```

---

### 2. Set Up Your Environment Variables
#### Obtaining the UniFi OTP Seed (MFA Secret)

The OTP seed (also referred to as the MFA Secret) is required for Multi-Factor Authentication and must be added to the `.env` file. Follow these steps to obtain it:

1. **Log in to your UniFi account**:
   Go to [https://account.ui.com](https://account.ui.com) and log in with your UniFi credentials.

2. **Access your profile**:
   Once logged in, select your profile in the top-right corner of the page.

3. **Manage security settings**:
   In the profile menu, select **Manage Security**.

4. **Retrieve the MFA Secret**:
   Under the "Multi-Factor Authentication" section:
   - Click: Add New Method.
   - Select App authentication.
   - Select "Enter code manually", or use a QR code scanner.
   - The text output will contain the OTP seed (a base32 string). This is your `UI_MFA_SECRET`.
   - Make sure to select App authentication as your primary MFA.

If you do not have 2FA enabled, you will need to set it up to generate a new OTP seed.

Create a `.env` file in the root directory of the project or your home directory to include your UniFi credentials and other configuration options.

Example `.env` file:
```plaintext
UI_USERNAME=your_unifi_username
UI_PASSWORD=your_unifi_password
UI_MFA_SECRET=your_mfa_secret_key
```

- Replace `your_unifi_username`, `your_unifi_password`, and `your_mfa_secret_key` with your UniFi credentials.

---

### 3. Set Up the `config.py` File
The base site is the name of the site that contains the port profiles that are to be copied to all other sites.

The `config.py` file contains configuration data for the controllers, base site, and the directory and filenames. Follow these steps to set it up:
1. Copy the sample file `config.py.SAMPLE` to `config.py`:
   ```bash
   cp config.py.SAMPLE config.py
   ```
2. Open `config.py` and update it with your details (e.g., controller IP addresses, site name, and directories):
   ```python
   INPUT_DIR = 'input'
   BACKUP_DIR = 'backup'
   
   CONTROLLERS = [
    'https://192.168.1.1:8443',
    'https://192.168.1.2:8443',
   ]

   MAX_THREADS = 8
   
   RADIUS_SERVERS = {
    '10.1.1.10': 'abc123',
    '10.2.2.10': '123abc'
   }
   ```
* Since the radius server secrets can't be copied from the base site, they need to be supplied here in a dict with the radius server IP address as the key and the secret as the value.

---

### Setup The Include Sites list
- Create a text file, e.g. `sites.txt` and place it in the `input` directory.
- Add one site name per line.
- The site name must match the Unifi descriptive name of the site.

---

### 4. Install Python Dependencies
Set up a Python virtual environment and install the required dependencies:
```bash
python3 -m venv venv    # Create a virtual environment
source venv/bin/activate    # Activate it (use `venv\Scripts\activate` for Windows)
pip install -r requirements.txt    # Install dependencies
```

---

## Running the Script(s)
The script provides several options for syncing configuration items across UniFi sites. These include fetching configuration items like port profiles from the base site and applying them to other sites, while also allowing for explicit control over which items to include or exclude.

### Script Descriptions
- **global_settings.py**: Syncs Global Settings for the site, currently supports Global Switch settings with automatic UniFi version detection
- **network_conf.py**: Syncs the VLANs for the site with UniFi 9.5+ compatibility
- **port_profiles.py**: Syncs the Port Profiles for the site
- **radius_profiles.py**: Syncs the Radius Profiles with automatic IP/secret management and incomplete profile detection
- **wlan_conf.py**: Syncs the WLANs with AP group handling and fallback logic
- **run.py**: Executes all the above scripts with intelligent module handling

### General Workflow:

#### 1. **Fetch Items from the Base Site**  
Retrieve the port profiles or other configuration items from the site designated as the base site (aka template site):
```bash
python3 port_profiles.py --get --base-site-name Default
```

Alternatively, if you already have the configuration items in a JSON format, you can directly place them into the directory specified by `endpoint_dir` in the script.

#### 2. **Sync Items to Target Sites**  
Apply the items from the base site to other sites:
```bash
python3 port_profiles.py --add
```

To specify a limited number of sites use `--site-names-file sites.txt`. This file includes a list of UniFi site names where the configuration will be applied.

#### 3. **Sync All Configs at Once**
If you want to apply all configuration changes at the same time:
```bash
python3 run.py --add
```

#### 4. **Process Specific Modules**
To work with specific configuration types:
```bash
# Sync only global settings
python3 run.py --add --module global_settings --include-names global_switch

# Sync only WLAN configurations
python3 run.py --add --module wlan_conf --include-names "Corporate WiFi"

# Sync multiple specific modules
python3 run.py --add --module radius_profiles --include-names "RADIUS Auth"
```

#### 5. **Backup Device Port Configuration**
```bash
python3 backup_ports.py
```
Note, the backup will run automatically as part of the `run.py` script before any changes are made.

---

## Advanced Usage Examples

### Global Settings Management
Global settings require special handling since they don't support "add" operations:

```bash
# Fetch global switch settings
python3 global_settings.py --get --base-site-name Default

# Replace global switch settings (works with both -a and -r)
python3 global_settings.py --replace --include-names global_switch

# Or use run.py (automatically handles global_settings correctly)
python3 run.py --add --module global_settings --include-names global_switch
```

### RADIUS Profile Management
The system automatically handles incomplete RADIUS profiles:

```bash
# Sync RADIUS profiles (incomplete profiles are automatically skipped)
python3 run.py --add --module radius_profiles

# The system will:
# - Skip profiles without auth_servers defined
# - Skip profiles with incomplete auth_servers (missing IP)
# - Update secrets for existing IP addresses
```

### WLAN Configuration with AP Group Handling
```bash
# Sync WLAN configurations with automatic AP group fallback
python3 run.py --add --module wlan_conf --include-names "Corporate WiFi"

# System will:
# - Map AP group names to IDs automatically
# - Use default AP group if specified group not found
# - Handle both UniFi 9.5+ and legacy versions
```

### Network Configuration (VLANs)
```bash
# Sync network configurations
python3 run.py --add --module network_conf

# System handles:
# - UniFi 9.5+ field filtering
# - Automatic ID inclusion for updates
# - Legacy version compatibility
```

---

## Using Include/Exclude Options

You can customize the behavior of the script using the `--include-names` or `--exclude-names` options, which allow you to specify the exact configuration items to process by name. 

For example, to sync only the port profile named `8021x`:
```bash
python3 port_profiles.py --add --include-names 8021x
```

To exclude profiles named `guest` and `default`:
```bash
python3 port_profiles.py --add --exclude-names guest,default
```

---

## Using the `--replace` Option

The `--replace` option ensures that existing configuration items on target sites are replaced with the new data from the base site. This action requires the `--include-names` option to explicitly define the items you want to replace. 

**Example: Replace Only Specific Port Profiles**  
Suppose you want to replace the port profiles named `8021x` and `AdminLAN` on target sites:
```bash
python3 port_profiles.py --replace --include-names 8021x,AdminLAN
```

**Global Settings Example:**
```bash
python3 global_settings.py --replace --include-names global_switch
```

**Why This Is Required:**  
When using `--replace`, the script avoids unintentional data loss by requiring you to specify exactly which items should be overwritten with `--include-names`. This ensures precision and prevents accidental replacement across all items.

---

## Using the `--delete` Option

The `--delete` option allows you to remove specific configuration items from the target sites. As with `--replace`, this feature requires the `--include-names` option so that you can explicitly define which items to delete.

**Important Note:** Before executing a delete operation, the script automatically creates a backup for the item(s) being deleted. These backups are stored in the directory defined as `BACKUP_DIR` in your `config.py`, and each backup is saved as a JSON file for easy restoration if needed.

**Example: Delete Specific Port Profiles**  
Suppose you want to delete the port profiles named `oldProfile` and `GuestAccess`:
```bash
python3 port_profiles.py --delete --include-names oldProfile,GuestAccess
```

**Why This Is Required:**  
The `--include-names` option ensures you explicitly select which configuration items to delete, providing a safeguard against accidentally removing items.

**Backup Details:**  
- Each delete operation triggers an automatic backup of the configuration items being removed.  
- Backups are saved as JSON files in the directory specified by `BACKUP_DIR`, named after the item being deleted.  
- These backups ensure you can restore deleted items if necessary.

---

## UniFi Version Compatibility

This tool supports both **UniFi 9.5+** and **legacy versions** with automatic detection:

### UniFi 9.5+ Features:
- **Modern Authentication**: Session-based authentication with automatic retry
- **Enhanced Security**: CSRF token handling and secure session management
- **Optimized API Calls**: Field filtering for browser-compatible requests
- **Global Settings Support**: Special endpoint handling for global switch settings

### Legacy Version Support:
- **Backward Compatibility**: Full support for older UniFi controllers
- **Automatic Fallback**: Detects legacy versions and uses appropriate endpoints
- **Consistent Interface**: Same commands work across all versions

### Automatic Version Detection:
```bash
# Works on both UniFi 9.5+ and legacy versions
python3 run.py --add
```

The tool automatically detects the UniFi version and uses the appropriate API endpoints and authentication methods.

---

## Error Handling and Troubleshooting

### Enhanced Error Handling:
- **Session Expiry**: Automatic re-authentication with retry logic
- **API Rate Limiting**: Built-in protection against rate limits
- **Friendly Error Messages**: Clear, actionable error descriptions
- **Graceful Degradation**: Continues processing other items if one fails

### Common Issues and Solutions:

#### 1. **Authentication Issues**
```bash
# Enable debug logging for detailed authentication info
python3 run.py --add -v
```
- Verify your UniFi credentials and ensure the `.env` file is set correctly
- Check that MFA is properly configured for UniFi 9.5+

#### 2. **Session Expiry**
- **Automatic Retry**: The tool automatically re-authenticates when sessions expire
- **Rate Limit Protection**: Only retries once to avoid getting locked out

#### 3. **RADIUS Profile Issues**
```
Skipping radius profile 'Default' - auth servers incomplete (missing IP addresses)
```
- This is normal behavior for incomplete RADIUS profiles
- The tool automatically skips profiles that aren't fully configured

#### 4. **AP Group Not Found**
```
AP group 'devices_ap_group' not found in target site. Using default AP group.
```
- The tool automatically falls back to the default AP group
- This is a warning, not an error

#### 5. **Global Settings Errors**
- Use `--replace` instead of `--add` for global settings
- The tool handles this automatically when using `run.py --add`

#### 6. **Enable Debug Logging**
```bash
python3 run.py --add -v
```

---

## Best Practices

### Before Making Changes:
- **Always Backup**: Use `--get` to back up existing configurations before making changes
- **Test in Staging**: Test configurations in a non-production environment first
- **Use Include/Exclude**: Limit scope with `--include-names` and `--exclude-names` in production

### During Operations:
- **Monitor Logs**: Use `-v` flag for detailed operation logs
- **Check Backups**: Ensure `BACKUP_DIR` is properly configured and backed up

### Configuration Management:
- **Version Control**: Keep your JSON configuration files in version control
- **Document Changes**: Maintain changelogs for configuration modifications
- **Regular Backups**: Schedule regular backups of your UniFi configurations

---

## 🆕 Configuration Dependency Management

The system now automatically manages dependencies between configuration types to ensure proper deployment order:

### Dependency Chain
```
1. Networks (VLANs) - No dependencies
2. RADIUS Profiles - No dependencies  
3. Global Settings - No dependencies
4. Port Profiles - Depends on Networks
5. WLANs - Depends on Networks + RADIUS Profiles
```

### 🧠 Smart Dependency Validation
**NEW**: The system now uses intelligent dependency checking that validates whether required resources already exist on the target controller, rather than requiring you to deploy everything at once.

- **🔍 Existing Resource Detection**: Automatically detects if VLANs, RADIUS profiles, and other dependencies already exist on your UniFi controller
- **⚡ Selective Deployment**: Only deploys configurations that don't already exist, saving time and reducing unnecessary changes
- **🎯 Site-Specific Validation**: Checks each target site individually for existing dependencies
- **📋 Clear Reporting**: Shows exactly which dependencies exist and which are missing

### How It Works
```bash
# Scenario: VLAN-10 already exists on controller, but you want to deploy a new WLAN
# OLD WAY: Required deploying VLAN-10 + WLAN together
# NEW WAY: Just deploy WLAN - system validates VLAN-10 already exists

python run.py -a --module wlan_conf --include-names "Corporate-WiFi"

# System will:
# ✅ Check if VLAN-10 exists on target site (it does!)
# ✅ Check if RADIUS profile exists (it does!)
# ✅ Deploy only the WLAN configuration
# ✅ Skip unnecessary VLAN deployment
```

### Validation Examples
```bash
# ✅ This works when VLANs already exist on the controller:
python run.py -a --module wlan_conf --include-names "Corporate-WiFi"

# ✅ This works when deploying everything fresh:
python run.py -a --include-names "VLAN-10,Radius-Profile,WLAN-Corporate"

# ❌ This fails when dependencies don't exist:
python run.py -a --module wlan_conf --include-names "New-WiFi"
# Error: VLAN 'Corporate-VLAN' not found in site 'MainOffice'
```

### 🔧 Troubleshooting Dependencies

**Q: Why am I getting "VLAN not found" errors?**
A: The smart validation checks if the VLAN actually exists on your UniFi controller. Make sure:
- The VLAN is created on your controller (via UniFi UI or previous deployment)
- The VLAN name in your JSON file exactly matches the name on the controller
- You're targeting the correct site where the VLAN exists

**Q: Can I disable smart dependency validation?**
A: Yes! Use strict validation if you want to ensure all dependencies are deployed together:
```python
# In code, use check_existing_resources=False
validate_config_dependencies(configs, check_existing_resources=False)
```

**Q: What happens if I have multiple sites with different VLANs?**
A: The system checks each target site individually. A WLAN deployment will succeed on sites where the VLAN exists and fail on sites where it doesn't, with clear error messages.

### Automatic Validation
- **Pre-deployment validation**: Ensures all dependencies exist on target sites
- **Smart ordering**: Automatically reorders operations based on dependencies
- **Site reference checking**: Validates that VLANs, RADIUS profiles, etc. exist in each target site
- **Selective deployment**: Skips resources that already exist, deploys only what's needed

---

## 🆕 Manual Rollback System

Automatic backups are created before making changes, with manual rollback capability:

### Automatic Backups
- **Pre-change backups**: Created before any add/replace/delete operation
- **Comprehensive data**: Includes full configuration state
- **Unique IDs**: Each backup has a timestamped identifier
- **Organized storage**: Stored in `rollbacks/` directory

### Rollback CLI
```bash
# List available backups
python rollback.py list

# List backups for specific config type
python rollback.py list --config-type wlan_conf

# Show backup details
python rollback.py info wlan_conf_MainOffice_20241104_143022_replace

# Perform rollback (dry run first)
python rollback.py rollback wlan_conf_MainOffice_20241104_143022_replace --dry-run

# Execute actual rollback
python rollback.py rollback wlan_conf_MainOffice_20241104_143022_replace

# Delete old backup
python rollback.py delete wlan_conf_MainOffice_20241104_143022_replace

# Clean up old backups (older than 30 days)
python rollback.py cleanup --days 30
```

### Rollback Safety Features
- **Pre-rollback backup**: Creates backup before rolling back
- **Validation**: Checks backup integrity before restoration
- **Dry run mode**: Preview changes without executing
- **Detailed logging**: Complete audit trail of operations

---

## Command Reference

### Basic Commands:
```bash
# Fetch configurations
python3 run.py --get --base-site-name Default

# Deploy configurations with automatic dependency ordering and smart validation
python run.py -a --include-names "VLAN-10,VLAN-20,WLAN-Corporate"

# Deploy only WLAN when VLANs already exist on controller (smart validation)
python run.py -a --module wlan_conf --include-names "WLAN-Corporate"

# Replace specific configurations with automatic backup creation
python run.py -r --include-names "WLAN-Corporate"

# Delete configurations (with backup)
python run.py -d --include-names "Old-VLAN"

# Rollback to previous configuration if needed
python rollback.py rollback network_conf_MainOffice_20241104_143022_replace

# Process specific modules
python3 run.py --add --module global_settings
python3 run.py --add --module wlan_conf --include-names "Corporate WiFi"
```

### Module-Specific Commands:
```bash
# Global Settings (requires --include-names)
python3 global_settings.py --replace --include-names global_switch

# RADIUS Profiles
python3 radius_profiles.py --add --include-names "Corporate Auth"

# WLAN Configuration
python3 wlan_conf.py --add --include-names "Guest WiFi"

# Network Configuration
python3 network_conf.py --add --include-names "VLAN100"

# Port Profiles
python3 port_profiles.py --add --include-names "802.1X Profile"
```

### Options:
- `-v, --verbose`: Enable debug logging
- `-m, --module`: Process specific module only
- `--include-names`: Specify specific configuration names to process
- `--exclude-names`: Exclude specific configuration names
- `--site-names-file`: File containing list of site names to process
- `--base-site-name`: Name of the base/template site

---

## Logging

The script outputs logs to the console by default. You can add additional file logging or customize log levels by modifying the `setup_logging` function in the code if needed.

### Log Levels:
- **INFO**: Standard operation information
- **DEBUG**: Detailed request/response data (use `-v` flag)
- **WARNING**: Non-critical issues (e.g., AP group not found)
- **ERROR**: Critical errors that stop operations

---

## License

This project is licensed under [MIT License](LICENSE).

Feel free to contribute or raise a GitHub issue for feature requests or bug reports!
