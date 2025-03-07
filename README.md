# UniFi Profile Manager

This project is designed to manage port profiles on UniFi network controllers. It reads profiles from a directory, compares them to existing profiles on the UniFi site, and ensures no duplicate profiles with the same name are uploaded.

## Features
- Fetch existing port profiles from a UniFi controller.
- Compare and avoid uploading duplicate profiles.
- Add new profiles from a JSON file directory to specified sites.
- Support multiple UniFi controllers and sites handled concurrently for performance.

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

Create a `.env` file in the root directory of the project to include your UniFi credentials and other configuration options.

Example `.env` file:
```plaintext
UI_USERNAME=your_unifi_username
UI_PASSWORD=your_unifi_password
UI_MFA_SECRET=your_mfa_secret_key
MAX_CONTROLLER_THREADS=2 # Number of UniFi controllers to process concurrently
MAX_THREADS=8            # Total threads available for operations
```

- Replace `your_unifi_username`, `your_unifi_password`, and `your_mfa_secret_key` with your UniFi credentials.

---
### Obtaining the UniFi OTP Seed (MFA Secret)

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

5. Add the OTP seed to your `.env` file:
   ```plaintext
   UI_MFA_SECRET=your-otp-seed
   ```

If you do not have 2FA enabled, you will need to set it up to generate a new OTP seed.
### 3. Set Up the `config.py` File
The base site is the name of the site that contains the port profiles that are to be copied to all other sites.

The `config.py` file contains configuration data for the controllers, base site, and the directory and filenames. Follow these steps to set it up:
1. Copy the sample file `config.py.SAMPLE` to `config.py`:
   ```bash
   cp config.py.SAMPLE config.py
   ```
2. Open `config.py` and update it with your details (e.g., controller IP addresses, site name, and directories):
   ```python
   PROFILE_DIR = 'profiles'
   INPUT_DIR = 'input'
   BASE_SITE = 'Default'
   
   ```

---

### 4. Install Python Dependencies
Set up a Python virtual environment and install the required dependencies:
```bash
python3 -m venv venv    # Create a virtual environment
source venv/bin/activate    # Activate it (use `venv\Scripts\activate` for Windows)
pip install -r requirements.txt    # Install dependencies
```

---

## Running the Script

1. Activate the Python virtual environment:
   ```bash
   source venv/bin/activate
   ```
2. Run the script to get the port profiles from the base site:
   ```bash
   python3 main.py --get
   ```
   Alternativly, if you already have the port profiles in json format, you can place them into the directory specified by `PROFILES_DIR`.
3. Run the script to add the port profiles to all other sites:
    ```bash
   python3 main.py --add
    ```
---

## Configuration Details

### `.env` File Configuration:
MAX_THREADS should be equal to the number of cores on the computer this is run on.
MAX_CONTROLLER_THREADS is the number of controllers to connect to concurently. This must be less than MAX_THREADS.

The `.env` file is used for sensitive data (like credentials) and runtime parameters:
- `UI_USERNAME`: Your UniFi username, e.g., `admin@domain.com`.
- `UI_PASSWORD`: Password for the UniFi account.
- `UI_MFA_SECRET`: MFA key for two-factor authentication.
- `CONFIG_FILE`: Config file path, usually `config.yaml`.
- `MAX_CONTROLLER_THREADS`: Number of UniFi controllers to handle concurrently (default: 2).
- `MAX_THREADS`: Maximum number of threads used for processing (default: 8).

### `config.yaml` Configuration:
The `config.yaml` file handles all other configuration:
- **UNIFI.PROFILE_DIR**: Directory containing the profiles in JSON format.
- **UNIFI.CONTROLLERS**: List of UniFi controllers to process.
- **UNIFI.BASE_SITE**: Site name to manage within each controller (e.g., `"default"`).

Example with a single controller:
```yaml
UNIFI:
  PROFILE_DIR: profiles
  CONTROLLERS:
  - https://192.168.1.1:8443
  BASE_SITE: default
```

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