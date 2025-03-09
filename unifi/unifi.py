import logging
import requests
import warnings
import json
from icecream import ic
import os
import json
from urllib3.exceptions import InsecureRequestWarning
import pyotp

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

logger = logging.getLogger(__name__)

class Unifi:
    """
    Handles interactions with UniFi API, including session management, authentication,
    and making API requests.

    This class is designed to manage authentication and handle sessions for interacting
    with UniFi API endpoints. It supports saving and loading session details to and from
    a file to minimize frequent reauthentication. It also includes methods for making
    authenticated requests using various HTTP methods.

    :ivar base_url: Base URL of the UniFi API, retrieved from environment variable
    :ivar username: Username for authentication, retrieved from environment variable
    :ivar password: Password for authentication, retrieved from environment variable
    :ivar mfa_secret: Secret key for Multi-Factor Authentication, retrieved from environment variable
    :ivar udm_pro: Specific path for UDM-Pro; initialized as an empty string
    :ivar session_cookie: Cookie for managing UniFi sessions, initializes as None
    :ivar csrf_token: CSRF token for API requests, initializes as None
    :type base_url: str
    :type username: str
    :type password: str
    :type mfa_secret: str
    :type udm_pro: str
    :type session_cookie: Optional[str]
    :type csrf_token: Optional[str]
    """
    SESSION_FILE = os.path.expanduser("~/.unifi_session.json")

    def __init__(self, base_url=None, username=None, password=None, mfa_secret=None):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.mfa_secret = mfa_secret
        self.udm_pro = ''
        self.session_cookie = None
        self.csrf_token = None
        self.load_session_from_file()
        self.sites = self.get_sites()

        if not all([self.base_url, self.username, self.password, self.mfa_secret]):
            raise ValueError("Missing required environment variables: BASE_URL, USERNAME, PASSWORD, or MFA_SECRET")

    def save_session_to_file(self):
        session_data = {
            "session_cookie": self.session_cookie,
            "csrf_token": self.csrf_token
        }
        with open(self.SESSION_FILE, "w") as f:
            json.dump(session_data, f)
        logger.info("Session data saved to file.")

    def load_session_from_file(self):
        if os.path.exists(self.SESSION_FILE):
            with open(self.SESSION_FILE, "r") as f:
                session_data = json.load(f)
                self.session_cookie = session_data.get("session_cookie")
                self.csrf_token = session_data.get("csrf_token")
                logger.info("Loaded session data from file.")

    def authenticate(self, retry_count=0, max_retries=3):
        """Logs in and retrieves a session cookie and CSRF token."""
        if retry_count >= max_retries:
            logger.error("Max authentication retries reached. Aborting authentication.")
            raise Exception("Authentication failed after maximum retries.")

        login_endpoint = f"{self.base_url}/api/{self.udm_pro}login"
        if not self.mfa_secret:
            raise ValueError("MFA_SECRET is missing or invalid.")

        otp = pyotp.TOTP(self.mfa_secret).now()
        payload = {
            "username": self.username,
            "password": self.password,
            "ubic_2fa_token": otp,
        }

        session = requests.Session()
        session.timeout = 10

        try:
            response = session.post(login_endpoint, json=payload, verify=False)
            response_data = response.json()
            response.raise_for_status()
            if response_data.get("meta", {}).get("rc") == "ok":
                logger.info("Logged in successfully.")
                self.session_cookie = session.cookies.get("unifises")
                self.csrf_token = session.cookies.get("csrf_token")
                self.save_session_to_file()
                return
            elif response_data.get("meta", {}).get("msg") == "api.err.Invalid2FAToken":
                logger.warning("Invalid 2FA token detected. Waiting for the next token...")
                # Wait for the current TOTP token to expire (~30 seconds for most TOTP systems)
                # Adjust the timing based on your specific TOTP configuration.
                import time
                time.sleep(30)
                # Retry authentication with the next token
                return self.authenticate(retry_count=retry_count + 1, max_retries=max_retries)
            else:
                logger.error(f"Login failed: {response_data.get('meta', {}).get('msg')}")
                raise Exception("Login failed.")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication error: {e}. Retrying ({retry_count + 1}/{max_retries})...")
            self.authenticate(retry_count=retry_count + 1)
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode JSON response: {json_err}")
            return None

    def make_request(self, endpoint, method="GET", data=None, retry_count=0, max_retries=3):
        """Makes an authenticated request to the UniFi API."""
        if not self.session_cookie or not self.csrf_token:
            print("No valid session. Authenticating...")
            self.authenticate()

        try:
            if method.upper() not in ["GET", "POST", "PUT", "DELETE"]:
                raise ValueError(f"Unsupported HTTP method: {method}")
        except ValueError as e:
            logger.error(e)
            return None

        headers = {
            "X-CSRF-Token": self.csrf_token,
            "Content-Type": "application/json"
        }
        cookies = {
            "unifises": self.session_cookie
        }

        url = f"{self.base_url}{endpoint}"

        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, cookies=cookies, verify=False)
            elif method.upper() == "POST":
                response = requests.post(url, json=data, headers=headers, cookies=cookies, verify=False)
            elif method.upper() == "PUT":
                response = requests.put(url, json=data, headers=headers, cookies=cookies, verify=False)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers, cookies=cookies, verify=False)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # Handle session expiry
            if response.status_code == 401:
                response_data = response.json()
                if response_data.get('meta', {}).get('rc') == 'error':
                    if response_data.get('meta', {}).get('msg') == 'api.err.NoSiteContext':
                        logger.error(f'No Site Context Povided')
                        return response_data
                    elif response_data.get('meta', {}).get('msg') == 'api.err.SessionExpired':
                        logger.warning("Session expired. Re-authenticating...")
                        self.authenticate()
                        return self.make_request(endpoint, method, data, retry_count=0)
                    else:
                        logger.error(f"Request failed with 401: {response_data.get('meta', {}).get('msg')}")
                        return response_data
            elif response.status_code == 400:
                # Log API errors for debugging
                logger.error(f"Request failed with 400: {response.text}")
                return None  # Handle site context or other app-level issues.

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"An error occurred: {e}")
            return None

    def get_sites(self):
        """
        Fetches a list of site names from the Unifi controller and saves them to a JSON file.

        This method communicates with the Unifi controller through an API endpoint
        to retrieve a list of site names. The retrieved site names are then written
        to a JSON file specified by the output parameter.

        :param output: The name of the output JSON file where the site names will be saved.
                       Defaults to 'site_names.json'.
        :type output: str
        :return: A list of site names retrieved from the Unifi controller.
        :rtype: list[str]
        :raises ValueError: If no sites are found during the API request.
        """

        logger.debug(f'Fetching sites from Unifi controller.')
        response = self.make_request("/api/self/sites", "GET")

        if not response:
            raise ValueError(f'No sites found.')
        if response.get('meta', {}).get('rc') == 'ok':
            sites = response.get("data", [])
            return {site["desc"]: Site(self, site) for site in sites}
        else:
            logger.error(response.get('meta', {}).get('msg'))

    def site(self, name):
        """Get a single site by name."""
        return self.sites.get(name)

    def __getitem__(self, name):
        """Shortcut for accessing a site."""
        return self.site(name)
