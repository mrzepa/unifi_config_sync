# UniFi Configuration Sync Manager

This project is designed to manage common configuration bits on UniFi network controllers. It reads configurations from a directory, compares them to existing configurations on the UniFi site to keep them in sync.
## Features
- Fetch existing configurations from a UniFi controller.
- Add new configurations from a JSON file directory to specified sites.
- Replace configurations from a JSON file directory to specified sites.
- Deletes configurations from specified sites.
- Support multiple UniFi controllers and sites handled concurrently for performance.

---
### Currently Supported Configs to Sync
- Networks (vlans)
- Port Profiles
- Radius Profiles
- WLANs
- Global Settings for `global_switch`

---
## Requirements
- Python 3.12+
- Dependencies:
  - `requests`
  - `pyyaml`
  - `pyotp`
  - Other standard libraries included with Python.

---

## Setup

### 1. Clone the Repository
Clone this repository to your local machine:
```bash
git clone https://github.com/yourusername/unifi-profile-manager.git
cd unifi-profile-manager
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

Create a `.env` file in the root directory of the project to include your UniFi credentials and other configuration options.

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
   BASE_SITE = 'Default'
   
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

### 4. Install Python Dependencies
Set up a Python virtual environment and install the required dependencies:
```bash
python3 -m venv venv    # Create a virtual environment
source venv/bin/activate    # Activate it (use `venv\Scripts\activate` for Windows)
pip install -r requirements.txt    # Install dependencies
```

---

## Running the Script
The script provides several options for syncing configuration items across UniFi sites. These include fetching configuration items like port profiles from the base site and applying them to other sites, while also allowing for explicit control over which items to include or exclude.

### General Workflow:

1. **Fetch Items from the Base Site**  
   Retrieve the port profiles or other configuration items from the site designated as the base site:
   ```bash
   python3 port_profiles.py --get
   ```
   Alternatively, if you already have the configuration items in a JSON format, you can directly place them into the directory specified by `endpoint_dir` in the script.

2. **Sync Items to Target Sites**  
   Apply the items from the base site to other sites:
   ```bash
   python3 port_profiles.py --add
   ```

   To specify a limited number of sites use `--site-name` or `--site-names-file sites.txt`. This file includes a list of UniFi site names where the configuration will be applied.

---

### Using Include/Exclude Options

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

### Using the `--replace` Option

The `--replace` option ensures that existing configuration items on target sites are replaced with the new data from the base site. This action requires the `--include-names` option to explicitly define the items you want to replace. 

**Example: Replace Only Specific Port Profiles**  
Suppose you want to replace the port profiles named `8021x` and `AdminLAN` on target sites:
```bash
python3 port_profiles.py --replace --include-names 8021x,AdminLAN
```

**Why This Is Required:**  
When using `--replace`, the script avoids unintentional data loss by requiring you to specify exactly which items should be overwritten with `--include-names`. This ensures precision and prevents accidental replacement across all items.

---

### Using the `--delete` Option

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

### Best Practices
- 
- Always use the `--get` option to back up the existing configuration before making changes or deletions.
- Use `--include-names` and `--exclude-names` to limit the scope of operations, especially when working in production environments.
- Test the script in a staging environment before applying changes or deletions to live controllers.
- Ensure the `BACKUP_DIR` is properly configured and the backups are periodically secured to prevent data loss.

By following these examples and guidelines, you can confidently manage UniFi configurations, whether you're scaling network setups, restructuring configurations, or cleaning up obsolete profiles.

---

## Troubleshooting

### Common Issues:
1. **"Profile directory does not exist":**
   Ensure the directory specified in `PROFILE_DIR` exists and contains valid JSON files.

2. **Authentication Issues:**
   Verify your UniFi credentials and ensure the `.env` file is set correctly.

3. **Duplicate Profile Names:**
   The script automatically avoids uploading profiles with names that already exist on the specified site.

4. **UniFi API Errors:**
   Check the logs (`ERROR` messages) for details such as `400` or invalid payload issues.
5. **Enable Debug Logging:**
    ```bash
   python3 main.py -v --add
   ```

---

## Logging
The script outputs logs to the console by default. You can add additional file logging or customize log levels by modifying the `setup_logging` function in the code if needed.

---

## License
This project is licensed under [MIT License](LICENSE).

Feel free to contribute or raise a GitHub issue for feature requests or bug reports!