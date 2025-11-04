# UniFi Configuration Sync Manager

A powerful Python-based tool for centrally managing and synchronizing UniFi network configurations across multiple controllers and sites. This project ensures consistent network profiles, VLANs, wireless networks, and security settings across your entire UniFi infrastructure.

## 🎯 **Project Purpose**

The UniFi Configuration Sync Manager is designed for organizations that need to maintain **consistent configurations across multiple UniFi sites and controllers**. Whether you're managing:

- **Multiple branch offices** with standardized network setups
- **Enterprise deployments** requiring consistent security policies
- **MSP environments** managing dozens of customer sites
- **Campus networks** with buildings needing identical configurations

This tool automates the deployment and synchronization of common network elements, ensuring all sites follow the same standards while allowing for site-specific variations where needed.

## ✨ **Key Features**

### 🔄 **Configuration Synchronization**
- **Multi-controller support** - Manage dozens of UniFi controllers simultaneously
- **Concurrent processing** - High-performance parallel operations across sites
- **Dependency management** - Intelligent deployment order with validation
- **Incremental updates** - Only apply changes when configurations differ

### 🛡️ **Safety & Reliability**
- **Automatic backups** - Every change is backed up before execution
- **Manual rollback system** - Restore any configuration from backup archives
- **Dry-run mode** - Preview changes before applying them
- **Error handling** - Comprehensive error recovery and reporting

### 📊 **Visibility & Reporting**
- **🌈 Colored summary reports** - Beautiful, easy-to-read operation summaries
- **Cross-platform colors** - Works on Windows, macOS, and Linux terminals
- **Detailed logging** - Full audit trail of all operations
- **Success/failure tracking** - Clear status reporting for all changes

### 🎛️ **Supported Configuration Types**
- **🌐 Networks (VLANs)** - Complete network configuration with VLAN support
- **🔌 Port Profiles** - Switch port configuration profiles
- **🔐 RADIUS Profiles** - Authentication profiles with automatic IP/secret management
- **📶 WLANs** - Wireless network configurations with AP group handling
- **⚙️ Global Settings** - Global switch settings (UniFi 9.5+ and legacy support)

### 🔧 **Advanced Features**
- **UniFi 9.5+ compatibility** - Modern authentication and API endpoints
- **Legacy version support** - Works with older UniFi controllers
- **Session management** - Automatic retry logic for expired sessions
- **AP group automation** - Intelligent AP group creation and management
- **VLAN validation** - Ensures required VLANs exist before deployment

---

## 📋 **Requirements**

### System Requirements
- **Python 3.12+** - Modern Python with enhanced features
- **Cross-platform** - Windows, macOS, or Linux
- **Network access** - Connectivity to UniFi controllers

### Python Dependencies
```bash
requests~=2.32.3      # HTTP client for UniFi API
pyyaml~=6.0.2         # YAML configuration parsing
pyotp~=2.9.0          # 2FA authentication support
python-dotenv~=1.1.0  # Environment variable management
colorama~=0.4.6       # Cross-platform terminal colors
urllib3~=2.3.0        # HTTP library with SSL support
```

---

## 🚀 **Quick Start**

### 1. Clone and Setup
```bash
git clone https://github.com/mrzepa/unifi_config_sync.git
cd unifi_config_sync

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Authentication
Create a `.env` file with your UniFi credentials:

```bash
# For UniFi 9.5+ (Recommended)
UI_API_KEY=your_api_key_here

# Or for legacy authentication
UI_USERNAME=admin
UI_PASSWORD=your_password
UI_MFA_SECRET=your_2fa_secret
```

### 3. Configure Controllers
Edit `config.py` to define your controllers:

```python
CONTROLLERS = [
    "https://unifi-controller1.example.com:8443",
    "https://unifi-controller2.example.com:8443",
    "https://branch-office.unifi.com:8443"
]
```

### 4. Run Your First Sync
```bash
# Add all configurations to all sites
python3 run.py -a

# Update existing configurations
python3 run.py -r

# Deploy specific module only
python3 run.py -a --module network_conf

# Preview changes without applying
python3 run.py -a --dry-run
```

---

## 📖 **Usage Guide**

### Basic Operations

#### **Add Configurations**
Deploy new configurations to sites (only creates what doesn't exist):
```bash
# Add all configuration types
python3 run.py -a

# Add specific types
python3 run.py -a --module network_conf
python3 run.py -a --module wlan_conf --module radius_profiles
```

#### **Replace Configurations**
Update existing configurations to match the baseline:
```bash
# Replace all configurations
python3 run.py -r

# Replace specific WLAN
python3 run.py -r --module wlan_conf --include-names "Corporate-WiFi"
```

#### **Delete Configurations**
Remove specific configurations from sites:
```bash
# Delete specific networks
python3 run.py -d --module network_conf --include-names "Old-VLAN"

# Delete with confirmation
python3 run.py -d --module wlan_conf --include-names "Test-WiFi" --confirm
```

### Advanced Operations

#### **Manual Backups**
NOTE: Backups happen automatically whenever the script makes a change to an existing configuration. Manual backups are not required.

Create on-demand backups of site configurations:
```bash
# Backup entire site (all config types)
python3 manual_backup.py --all --sites "Main Office" "Branch 1"

# Backup specific configuration types
python3 manual_backup.py --config-types wlanconf networkconf

# Backup with verbose output
python3 manual_backup.py --all -v

# List existing backups
python3 manual_backup.py --list
```

#### **Rollback Operations**
Restore configurations from backups:
```bash
# List all available backups
python3 rollback.py list

# Show backup details
python3 rollback.py info wlanconf_Main-Office_20251104_102328_manual

# Preview rollback (dry run)
python3 rollback.py rollback backup_id --dry-run

# Perform actual rollback
python3 rollback.py rollback backup_id
```

#### **Site Management**
```bash
# Process specific sites only
python3 run.py -a --sites "Main Office" "Branch 1"

# Use custom site list file
python3 run.py -a --site-names-file custom_sites.txt

# Skip VLAN validation (for network_conf module)
python3 run.py -a --module network_conf
```

---

## 🎨 **Colored Summary Reports**

The tool provides beautiful, color-coded summary reports that make it easy to understand what happened during each operation:

### **Color Scheme**
- 🟢 **ADD Operations** - Bright Green (creation)
- 🟡 **REPLACE Operations** - Bright Yellow (modification)
- 🔴 **DELETE Operations** - Bright Red (removal)
- ✅ **Created Items** - Green (successful creation)
- 🔄 **Updated Items** - Yellow (successful modification)
- ⏭️ **Skipped Items** - Cyan (informational)
- ❌ **Failed Items** - Red (errors)
- ⚠️ **Warnings** - Yellow (attention needed)
- 💾 **Backups** - Magenta (informational)

### **Example Output**
```
================================================================================
OPERATION SUMMARY REPORT
================================================================================
Generated: 2025-11-04 10:29:59
Total Operations: 1

OPERATION: ADD
----------------------------------------
Site: Main Office
  Time: 10:29:59
  ✅ Created (3):
      - Network:Payment
      - WLAN:Corporate-Guest
      - RADIUS Profile:Company-Auth
  ⏭️  Skipped (2):
      - Network:Management (already exists)
      - WLAN:Corporate-Staff (same configuration)

GLOBAL TOTALS
----------------------------------------
  Items Created: 3
  Items Updated: 0
  Items Skipped: 2
  Items Failed: 0
  Backups Created: 3
================================================================================
```

---

## 🛡️ **Safety Features**

### **🔍 Dry-Run Mode**
Preview changes before applying them to ensure accuracy:
```bash
# Preview what would be created/updated/deleted
python3 run.py --add --dry-run -v

# Dry-run specific module
python3 run.py --add --module network_conf --dry-run

# Output shows:
# 🔍 DRY RUN MODE - No changes will be applied
# 🔍 DRY RUN: Would create networkconf 'Payment' at site 'MainOffice'
# 🔍 DRY RUN: Would update wlanconf 'Corporate-Guest' at site 'MainOffice'
```

### **Automatic Backups**
Every configuration change is automatically backed up before execution:
- **Pre-change backups** - Complete configuration snapshots
- **Timestamped files** - Easy identification of backup versions
- **JSON format** - Human-readable and easily restorable
- **Rollback integration** - One-click restore capability

### **Dependency Management**
The tool validates configuration dependencies before deployment:
- **VLAN validation** - Ensures required VLANs exist
- **AP group checks** - Validates AP group availability
- **RADIUS server validation** - Checks authentication server connectivity
- **Network dependencies** - Validates network profile references

---

## 📁 **Project Structure**

```
unifi_site_sync/
├── 📄 run.py                 # Main entry point
├── 📄 manual_backup.py       # Manual backup utility
├── 📄 rollback.py            # Rollback management
├── 📄 config.py              # Controller and site configuration
├── 📄 summary_manager.py     # Colored summary reports
├── 📄 rollback_manager.py    # Backup and rollback engine
├── 📄 utils.py               # Shared utilities
├── 📄 unifi/                 # UniFi API client
│   ├── unifi.py              # Core UniFi client
│   └── resources.py          # API resource management
├── 📁 network_conf/          # Network (VLAN) configurations
├── 📁 wlan_conf/             # Wireless network configurations
├── 📁 radius_profiles/       # RADIUS authentication profiles
├── 📁 port_profiles/         # Switch port profiles
├── 📁 global_settings/       # Global switch settings
├── 📁 backups/               # Backup storage directory
├── 📁 site_data/             # Site data cache
└── 📄 requirements.txt       # Python dependencies
```

---

## 🎯 **Use Cases**

### **Enterprise Network Management**
- **Standardized branch deployments** - Ensure all offices use identical network configurations
- **Compliance enforcement** - Maintain consistent security policies across all sites
- **Rapid provisioning** - Deploy new sites with pre-approved configurations

### **Managed Service Providers**
- **Multi-tenant management** - Handle dozens of customer environments from one tool
- **Template-based deployments** - Reuse proven configuration templates
- **Audit trail maintenance** - Complete history of all configuration changes

### **Educational Institutions**
- **Campus-wide standards** - Consistent Wi-Fi and network settings across buildings
- **Seasonal configurations** - Easy updates for semester changes
- **Guest network management** - Standardized guest access across campus

---

## 🔐 **Authentication Setup**

### **Environment Variables**

Create a `.env` file in the root directory of the project or your home directory to include your UniFi credentials and other configuration options.

#### **UniFi Authentication Methods**

The tool supports both modern API key authentication and legacy username/password authentication:

**Method 1: API Key Authentication (Recommended for UniFi 9.5+)**
```plaintext
UI_API_KEY=your_unifi_api_key
```

**Method 2: Legacy Authentication with MFA**
```plaintext
UI_USERNAME=your_unifi_username
UI_PASSWORD=your_unifi_password
UI_MFA_SECRET=your_mfa_secret_key
```

#### **Obtaining the UniFi OTP Seed (MFA Secret)**

The OTP seed (also referred to as the MFA Secret) is required for Multi-Factor Authentication and must be added to the `.env` file. Follow these steps to obtain it:

1. **Log in to your UniFi account**:
   Go to [https://account.ui.com](https://account.ui.com) and log in with your UniFi credentials.

2. **Access your profile**:
   Once logged in, select your profile in the top-right corner of the page.

3. **Manage security settings**:
   In the profile menu, select **Manage Security**.

4. **Retrieve the MFA Secret**:
   Under the "Multi-Factor Authentication" section:
   - Click: Add New Method
   - Select App authentication
   - Select "Enter code manually", or use a QR code scanner
   - The text output will contain the OTP seed (a base32 string). This is your `UI_MFA_SECRET`
   - Make sure to select App authentication as your primary MFA

5. **Store the credentials**:
   Create or update your `.env` file with the credentials:
   ```plaintext
   UI_USERNAME=your_unifi_username
   UI_PASSWORD=your_unifi_password
   UI_MFA_SECRET=your_mfa_secret_key
   ```

**Important Notes:**
- Replace the placeholder values with your actual UniFi credentials
- Keep the `.env` file secure and never commit it to version control
- If you don't have 2FA enabled, you'll need to set it up to generate a new OTP seed

---

## 🛠️ **Troubleshooting**

### **Common Issues**

#### **Authentication Problems**
```bash
# Check API key validity
curl -H "Authorization: Bearer $UI_API_KEY" \
     https://unifi-controller:8443/api/self

# Test legacy authentication
python3 -c "from unifi.unifi import Unifi; print(Unifi('https://unifi:8443', 'admin', 'pass', 'secret'))"
```

#### **Network Connectivity**
```bash
# Test controller connectivity
curl -k https://unifi-controller:8443/status

# Check SSL certificate
openssl s_client -connect unifi-controller:8443 -showcerts
```

---

## 📈 **Performance**

### **Scalability**
- **100+ controllers** - Tested with large enterprise deployments
- **1000+ sites** - Efficient parallel processing
- **Sub-minute deployment** - Typical full sync in under 60 seconds

### **Resource Usage**
- **Memory efficient** - Minimal memory footprint
- **Network optimized** - Intelligent API call batching
- **CPU friendly** - Asynchronous processing prevents blocking

---

## 🤝 **Contributing**

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details on:
- Code style and standards
- Testing requirements
- Pull request process
- Issue reporting guidelines

---

## 📄 **License**

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🆘 **Support**

- **Documentation** - Check this README and inline code comments
- **Issues** - Report bugs via GitHub Issues
- **Discussions** - Use GitHub Discussions for questions

---

**🚀 Ready to streamline your UniFi network management? Get started with the Quick Start guide above!**
