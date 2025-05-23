import logging
import requests
import warnings
import json
from icecream import ic
import os
import json
from urllib3.exceptions import InsecureRequestWarning
import pyotp
import threading
from .sites import Sites

file_lock = threading.Lock()

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
    _session_data = {}  # Class-level session storage by base_url

    def __init__(self, base_url=None, username=None, password=None, mfa_secret=None):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.mfa_secret = mfa_secret
        self.udm_pro = ''
        self.session_cookie = None
        self.csrf_token = None

        if not all([self.base_url, self.username, self.password, self.mfa_secret]):
            raise ValueError("Missing required environment variables: BASE_URL, USERNAME, PASSWORD, or MFA_SECRET")

        self.load_session_from_file()
        self.authenticate()
        self.sites = self.get_sites()

    def save_session_to_file(self):
        """Save session data to file, grouped by base_url."""
        # Ensure session data for the current base_url is saved

        self._session_data[self.base_url] = {
            "session_cookie": self.session_cookie,
            "csrf_token": self.csrf_token
        }
        with file_lock:
            with open(self.SESSION_FILE, "w") as f:
                json.dump(self._session_data, f)
            logger.info(f"Session data for {self.base_url} saved to file.")

    def load_session_from_file(self):
        """Load session data from file for the current base_url."""
        if os.path.exists(self.SESSION_FILE):
            with open(self.SESSION_FILE, "r") as f:
                self._session_data = json.load(f)

            # Load session data specific to this base_url, if it exists
            if self.base_url in self._session_data:
                session_info = self._session_data[self.base_url]
                self.session_cookie = session_info.get("session_cookie")
                self.csrf_token = session_info.get("csrf_token")
                logger.info(f"Loaded session data for {self.base_url} from file.")

    def authenticate(self, retry_count=0, max_retries=3):
        """Logs in and retrieves a session cookie and CSRF token."""
        if retry_count >= max_retries:
            logger.error("Max authentication retries reached. Aborting authentication.")
            raise Exception("Authentication failed after maximum retries.")

        login_endpoint = f"{self.base_url}/api/{self.udm_pro}login"
        if not self.mfa_secret:
            raise ValueError("MFA_SECRET is missing or invalid.")

        otp = pyotp.TOTP(self.mfa_secret)
        payload = {
            "username": self.username,
            "password": self.password,
            "ubic_2fa_token": otp.now(),
        }

        session = requests.Session()
        session.timeout = 10

        try:
            response = session.post(login_endpoint, json=payload, verify=False)
            response_data = response.json()
            # response.raise_for_status()
            if response_data.get("meta", {}).get("rc") == "ok":
                logger.info("Logged in successfully.")

                self.session_cookie = session.cookies.get("unifises")
                # self.csrf_token = session.cookies.get("csrf_token")
                self.save_session_to_file()
                return
            elif response_data.get("meta", {}).get("msg") == "api.err.Invalid2FAToken":
                logger.warning("Invalid 2FA token detected. Waiting for the next token...")
                # Wait for the current TOTP token to expire (~30 seconds for most TOTP systems)
                import time
                time_remaining = otp.interval - (int(time.time()) % otp.interval)
                logger.warning(f"Invalid 2FA token detected. Next token available in {time_remaining}s.")
                # Countdown for user clarity
                while time_remaining > 0:
                    print(f"\rRetrying authentication in {time_remaining} seconds...", end="")
                    time.sleep(1)
                    time_remaining -= 1
                print("\nRetrying now!")

                # Retry authentication with the next token
                return self.authenticate(retry_count=retry_count + 1, max_retries=max_retries)
            elif response_data.get("meta", {}).get("msg") == "api.err.Invalid":
                logger.error(f'Login failed, invalid credentials.')
                return None
            else:
                logger.error(f"Login failed: {response_data.get('meta', {}).get('msg')}")
                raise Exception("Login failed.")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication error: {e}. Retrying ({retry_count + 1}/{max_retries})...")
            return self.authenticate(retry_count=retry_count + 1, max_retries=max_retries)
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode JSON response: {json_err}")
            return None

    def make_request(self, endpoint, method="GET", data=None, retry_count=0, max_retries=3):
        """Makes an authenticated request to the UniFi API."""
        # if not self.session_cookie or not self.csrf_token:
        if not self.session_cookie:
            logger.info("No valid session. Authenticating...")
            self.authenticate()

        headers = {
            # "X-CSRF-Token": self.csrf_token,
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
                    elif response_data.get('meta', {}).get('msg') == 'api.err.LoginRequired':
                        self.authenticate()
                        return self.make_request(endpoint, method, data, retry_count=0)
                    else:
                        logger.error(f"Request failed with 401: {response_data.get('meta', {}).get('msg')}")
                        return response_data
            elif response.status_code == 400:
                # Log API errors for debugging
                response_data = response.json()
                logger.error(f"Request failed with 400: {response_data.get('meta', {}).get('msg')}")
                return response_data

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"An error occurred: {e}")
            return None

    def get_sites(self) -> dict:
        """
        Fetches the list of sites from the Unifi controller.

        This method sends a GET request to the "/api/self/sites" endpoint of the
        Unifi controller to retrieve a list of available sites. The method returns
        a dictionary where the keys are the site descriptions and the values are
        `Sites` objects initialized with the retrieved data.

        :raises ValueError: When no sites are found in the response or an invalid
            response is received from the controller.
        :raises KeyError: When the expected data or metadata is missing in the
            response.
        :raises Exception: If the request to the controller fails or another
            unexpected condition occurs.

        :return: A dictionary mapping site descriptions to `Sites` objects.
        :rtype: dict
        """

        logger.debug(f'Fetching sites from Unifi controller.')
        response = self.make_request("/api/self/sites", "GET")

        if not response:
            raise ValueError(f'No sites found.')
        if response.get('meta', {}).get('rc') == 'ok':
            sites = response.get("data", [])
            return {site["desc"]: Sites(self, site) for site in sites}
        else:
            logger.error(response.get('meta', {}).get('msg'))

    def site(self, name):
        """Get a single site by name."""
        return self.sites.get(name)

    def __getitem__(self, name):
        """Shortcut for accessing a site."""
        return self.site(name)
