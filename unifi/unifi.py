import logging
import os
import requests
import json
import pyotp
import time
import warnings
from datetime import datetime, timedelta
from unifi.sites import Sites
from unifi.endpoints import get_sites_candidate_urls, AuthMethod
from urllib3.exceptions import InsecureRequestWarning
import threading

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

    def __init__(self, base_url=None, username=None, password=None, mfa_secret=None, api_key=None, mfa_field=None):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.mfa_secret = mfa_secret
        self.api_key = api_key
        self.mfa_field = mfa_field or 'auto'
        self.udm_pro = ''
        self.session_cookie = None
        self.csrf_token = None
        self.http_session = None

        if not self.base_url:
            raise ValueError("Missing required environment variable: BASE_URL")
        if not self.api_key and not all([self.username, self.password, self.mfa_secret]):
            raise ValueError("Missing required environment variables: BASE_URL, USERNAME, PASSWORD, or MFA_SECRET")

        self.load_session_from_file()
        if not self.api_key:
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

        login_endpoints = [
            f"{self.base_url}/api/auth/login",
            f"{self.base_url}/api/{self.udm_pro}login",
        ]
        if not self.mfa_secret:
            raise ValueError("MFA_SECRET is missing or invalid.")

        otp = pyotp.TOTP(self.mfa_secret)
        otp_value = otp.now()
        fields = ["token", "ubic_2fa_token"] if self.mfa_field == 'auto' else [self.mfa_field]

        last_error = None
        for endpoint in login_endpoints:
            session = requests.Session()
            session.timeout = 10
            headers = {"Content-Type": "application/json"}

            for field in fields:
                payload = {
                    "username": self.username,
                    "password": self.password,
                }
                payload[field] = otp_value
                # UniFi 9.5 requires rememberMe field for /api/auth/login
                if "/api/auth/login" in endpoint:
                    payload["rememberMe"] = False

                # Log payload structure (without sensitive data)
                payload_keys = list(payload.keys())
                logger.debug(f"Login payload fields: {payload_keys}")

                try:
                    response = session.post(endpoint, json=payload, headers=headers, verify=False)
                    response_data = None
                    try:
                        response_data = response.json()
                    except ValueError:
                        response_data = {"status_code": response.status_code}

                    cookie = session.cookies.get("unifises")
                    
                    # Log response for debugging
                    logger.debug(f"Auth attempt endpoint={endpoint} field={field} status={response.status_code} has_cookie={bool(cookie)}")
                    if response_data:
                        logger.debug(f"Response data keys: {list(response_data.keys()) if isinstance(response_data, dict) else 'not a dict'}")

                    # UniFi 9.5 /api/auth/login returns 200 with session in cookies and no JSON body
                    if "/api/auth/login" in endpoint and response.status_code == 200:
                        logger.info("Logged in successfully (UniFi 9.5+ auth).")
                        self.session_cookie = cookie
                        self.http_session = session
                        self.save_session_to_file()
                        return
                    # Legacy: Check for meta.rc == "ok"
                    if isinstance(response_data, dict) and response_data.get("meta", {}).get("rc") == "ok":
                        logger.info("Logged in successfully (legacy auth).")
                        self.session_cookie = cookie
                        self.http_session = session
                        self.save_session_to_file()
                        return
                    # Fallback: Accept 200 with cookie
                    if response.status_code == 200 and cookie:
                        logger.info("Logged in successfully (cookie-based auth).")
                        self.session_cookie = cookie
                        self.http_session = session
                        self.save_session_to_file()
                        return
                    elif isinstance(response_data, dict) and response_data.get("meta", {}).get("msg") == "api.err.Invalid2FAToken":
                        logger.warning("Invalid 2FA token detected. Waiting for the next token...")
                        import time
                        time_remaining = otp.interval - (int(time.time()) % otp.interval)
                        logger.warning(f"Invalid 2FA token detected. Next token available in {time_remaining}s.")
                        while time_remaining > 0:
                            print(f"\rRetrying authentication in {time_remaining} seconds...", end="")
                            time.sleep(1)
                            time_remaining -= 1
                        print("\nRetrying now!")
                        return self.authenticate(retry_count=retry_count + 1, max_retries=max_retries)
                    else:
                        # Minimal debug for failures
                        snippet = None
                        try:
                            snippet = json.dumps(response_data)[:200]
                        except Exception:
                            snippet = str(response.text)[:200] if hasattr(response, 'text') else str(response_data)
                        logger.debug(f"Auth failed endpoint={endpoint} field={field} status={response.status_code} body_snippet={snippet}")
                        last_error = response_data or {"status_code": response.status_code}
                        continue
                except requests.exceptions.HTTPError as http_err:
                    logger.error(f"HTTP error occurred: {http_err}")
                    return None
                except requests.exceptions.RequestException as e:
                    logger.error(f"Authentication error: {e}. Retrying ({retry_count + 1}/{max_retries})...")
                    return self.authenticate(retry_count=retry_count + 1, max_retries=max_retries)
                except json.JSONDecodeError as json_err:
                    logger.error(f"Failed to decode JSON response: {json_err}")
                    return None

        if last_error:
            if last_error.get("meta", {}).get("msg") == "api.err.Invalid":
                logger.error(f'Login failed, invalid credentials.')
                return None
            logger.error(f"Login failed: {last_error.get('meta', {}).get('msg')}")
            raise Exception("Login failed.")

    def make_request(self, endpoint, method="GET", data=None, params=None, retry_count=0, max_retries=3):
        """Makes an authenticated request to the UniFi API."""
        # if not self.session_cookie or not self.csrf_token:
        if not self.api_key and not (self.session_cookie or self.http_session):
            logger.info("No valid session. Authenticating...")
            self.authenticate()

        headers = {
            # "X-CSRF-Token": self.csrf_token,
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
            headers["Accept"] = "application/json"
        cookies = {
            "unifises": self.session_cookie
        } if (not self.api_key and self.session_cookie) else None

        url = f"{self.base_url}{endpoint}"

        try:
            sess = self.http_session if (self.http_session and not self.api_key) else requests
            if method.upper() == "GET":
                response = sess.get(url, headers=headers, cookies=cookies, params=params, verify=False)
            elif method.upper() == "POST":
                response = sess.post(url, json=data, headers=headers, cookies=cookies, params=params, verify=False)
            elif method.upper() == "PUT":
                response = sess.put(url, json=data, headers=headers, cookies=cookies, params=params, verify=False)
            elif method.upper() == "DELETE":
                response = sess.delete(url, headers=headers, cookies=cookies, params=params, verify=False)
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
                        if not self.api_key:
                            self.authenticate()
                            return self.make_request(endpoint, method, data, retry_count=0)
                        return response_data
                    elif response_data.get('meta', {}).get('msg') == 'api.err.LoginRequired':
                        if not self.api_key:
                            self.authenticate()
                            return self.make_request(endpoint, method, data, retry_count=0)
                        return response_data
                    else:
                        logger.error(f"Request failed with 401: {response_data.get('meta', {}).get('msg')}")
                        return response_data
            elif response.status_code == 400:
                # Log API errors for debugging
                response_data = response.json()
                logger.error(f"Request failed with 400: {response_data.get('meta', {}).get('msg')}")
                return response_data

            response.raise_for_status()
            try:
                return response.json()
            except json.JSONDecodeError as json_err:
                # Log snippet of non-JSON response for debugging
                snippet = response.text[:200] if hasattr(response, 'text') else ''
                logger.debug(f"JSON decode failed for {url}: {snippet}")
                return None
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
        
        # Determine auth method and get candidate URLs from registry
        auth_method = AuthMethod.API_KEY if self.api_key else AuthMethod.SESSION
        candidates = get_sites_candidate_urls(auth_method)
        
        # Try each endpoint from the registry
        for endpoint, api_version in candidates:
            logger.debug(f"Trying sites endpoint: {endpoint} (API version: {api_version})")
            
            if api_version == "proxy_integration":
                # Integration API with pagination
                all_sites = []
                limit = 100
                offset = 0
                total = None
                while True:
                    response = self.make_request(endpoint, "GET", params={"limit": limit, "offset": offset})
                    if not response:
                        break
                    data = []
                    if isinstance(response, dict):
                        data = response.get("data") or []
                        total = response.get("totalCount", total)
                    elif isinstance(response, list):
                        data = response
                    if not isinstance(data, list):
                        data = []
                    all_sites.extend(data)
                    if total is not None:
                        if len(all_sites) >= int(total):
                            break
                    if len(data) < limit:
                        break
                    offset += limit
                
                if all_sites:
                    # Successfully retrieved sites from Integration API
                    mapped = []
                    for item in all_sites:
                        name = item.get("internalReference") or item.get("name") or item.get("site") or item.get("short_name") or item.get("desc") or ""
                        desc = item.get("name") or item.get("desc") or item.get("description") or name
                        _id = item.get("_id") or item.get("id") or item.get("site_id") or item.get("unique_id")
                        mapped.append({"name": name, "desc": desc, "_id": _id})
                    if mapped:
                        logger.debug(f"Successfully retrieved {len(mapped)} sites from {api_version}")
                        return {site["desc"]: Sites(self, site) for site in mapped if site.get("desc")}
            else:
                # Simple GET request for v2 and legacy endpoints
                response = self.make_request(endpoint, "GET")
                if response:
                    sites_data = []
                    
                    # Handle different response formats
                    if isinstance(response, list):
                        sites_data = response
                    elif isinstance(response, dict):
                        if response.get('meta', {}).get('rc') == 'ok':
                            sites_data = response.get('data', [])
                        elif 'data' in response:
                            sites_data = response['data']
                        elif api_version == "proxy_v2":
                            # v2 might return sites directly in response
                            sites_data = [response] if '_id' in response or 'id' in response else []
                    
                    if sites_data:
                        # Map to standard format
                        if api_version in ["proxy_integration", "proxy_v2"]:
                            mapped = []
                            for item in sites_data:
                                name = item.get("internalReference") or item.get("name") or item.get("site") or item.get("short_name") or item.get("desc") or ""
                                desc = item.get("name") or item.get("desc") or item.get("description") or name
                                _id = item.get("_id") or item.get("id") or item.get("site_id") or item.get("unique_id")
                                mapped.append({"name": name, "desc": desc, "_id": _id})
                            if mapped:
                                logger.debug(f"Successfully retrieved {len(mapped)} sites from {api_version}")
                                return {site["desc"]: Sites(self, site) for site in mapped if site.get("desc")}
                        else:
                            # Legacy format
                            logger.debug(f"Successfully retrieved {len(sites_data)} sites from {api_version}")
                            return {site.get("desc", site.get("name")): Sites(self, site) for site in sites_data}
        
        # No endpoint worked
        raise ValueError(f'No sites found after trying all available endpoints.')

    def site(self, name):
        """Get a single site by name."""
        return self.sites.get(name)

    def __getitem__(self, name):
        """Shortcut for accessing a site."""
        return self.site(name)
