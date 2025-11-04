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
    _failed_auth_count = {}  # Class-level failed auth counter by base_url

    def __init__(self, base_url=None, username=None, password=None, mfa_secret=None, api_key=None, mfa_field=None, permission_callback=None, force_modern_auth=False):
        # Allow direct parameters OR environment variables
        self.base_url = base_url or os.getenv('BASE_URL')
        self.username = username or os.getenv('USERNAME')
        self.password = password or os.getenv('PASSWORD')
        self.mfa_secret = mfa_secret or os.getenv('MFA_SECRET')
        self.api_key = api_key or os.getenv('UNIFI_API_KEY')
        self.mfa_field = mfa_field or 'auto'
        self.force_modern_auth = force_modern_auth
        self.udm_pro = ''
        self.session_cookie = None
        self.csrf_token = None
        self.http_session = None
        self.permission_error_count = 0  # Track 403 errors for graceful exit
        self.permission_callback = permission_callback  # Callback to notify on permission error

        if not self.base_url:
            raise ValueError("Missing required parameter: base_url (or BASE_URL environment variable)")
        if not self.api_key and not all([self.username, self.password]):
            raise ValueError("Missing required parameters: either api_key OR username and password")

        self.load_session_from_file()
        if not self.api_key and not (self.session_cookie or self.http_session):
            self.authenticate()
        self.sites = self.get_sites()

    def save_session_to_file(self):
        """Save session data to file, grouped by base_url."""
        # Ensure session data for the current base_url is saved

        # Extract cookies from http_session for UniFi 9.5+
        session_cookies = {}
        if self.http_session:
            for cookie_name, cookie_value in self.http_session.cookies.items():
                session_cookies[cookie_name] = cookie_value

        self._session_data[self.base_url] = {
            "session_cookie": self.session_cookie,
            "csrf_token": self.csrf_token,
            "session_cookies": session_cookies  # Save all cookies for UniFi 9.5+
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
                session_cookies = session_info.get("session_cookies", {})
                
                # Recreate the http_session if we have session cookies (for UniFi 9.5+)
                if session_cookies:
                    self.http_session = requests.Session()
                    for cookie_name, cookie_value in session_cookies.items():
                        self.http_session.cookies.set(cookie_name, cookie_value)
                    logger.info(f"Loaded session data for {self.base_url} from file ({len(session_cookies)} cookies).")
                elif self.session_cookie:
                    # Fallback to legacy session cookie
                    self.http_session = requests.Session()
                    self.http_session.cookies.set("unifises", self.session_cookie)
                    if self.csrf_token:
                        self.http_session.cookies.set("csrf_token", self.csrf_token)
                    logger.info(f"Loaded session data for {self.base_url} from file (legacy cookie).")
                else:
                    logger.info(f"Loaded session data for {self.base_url} from file (no session cookies).")

    def authenticate(self, retry_count=0, max_retries=3):
        """Logs in and retrieves a session cookie and CSRF token."""
        if retry_count >= max_retries:
            logger.error("Max authentication retries reached. Aborting authentication.")
            raise Exception("Authentication failed after maximum retries.")

        if self.force_modern_auth:
            # Force modern UniFi 9.5+ authentication only
            logger.debug(f"Force modern authentication enabled for {self.base_url}")
            login_endpoints = [
                f"{self.base_url}/api/auth/login",
            ]
        else:
            # Try both legacy and modern endpoints (default behavior)
            logger.debug(f"Trying both legacy and modern authentication endpoints for {self.base_url}")
            login_endpoints = [
                f"{self.base_url}/api/auth/login",
                f"{self.base_url}/api/{self.udm_pro}login",
            ]
        # MFA is optional - try without first, then with if needed
        if self.mfa_secret:
            otp = pyotp.TOTP(self.mfa_secret)
            otp_value = otp.now()
            fields = ["token", "ubic_2fa_token"] if self.mfa_field == 'auto' else [self.mfa_field]
        else:
            otp_value = None
            fields = []

        last_error = None
        for endpoint in login_endpoints:
            session = requests.Session()
            session.timeout = 10
            headers = {"Content-Type": "application/json"}

            # Try authentication with different MFA field combinations
            auth_attempts = []
            
            if not fields:
                # No MFA - try basic login
                auth_attempts.append([None])
            else:
                # Try each MFA field
                auth_attempts = [[field] for field in fields]
            
            for fields_to_try in auth_attempts:
                payload = {
                    "username": self.username,
                    "password": self.password,
                }
                
                # Add MFA token if available
                if fields_to_try and fields_to_try[0] and otp_value:
                    payload[fields_to_try[0]] = otp_value
                
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
                    
                    # Check for authentication rate limiting
                    if isinstance(response_data, dict):
                        # Check multiple possible rate limit indicators
                        rate_limit_indicators = [
                            response_data.get("meta", {}).get("msg"),
                            response_data.get("code"),
                            response_data.get("message")
                        ]
                        
                        if any(indicator in ["authentication_failed_limit_reached", "AUTHENTICATION_FAILED_LIMIT_REACHED", "rate.limit.exceeded", "too.many.requests", "authentication.limit.reached", "You've reached the login attempt limit"] for indicator in rate_limit_indicators):
                            logger.error("UniFi controller authentication rate limit reached!")
                            logger.error("Please wait 5-10 minutes before trying again.")
                            raise Exception("AUTHENTICATION_FAILED_LIMIT_REACHED: UniFi controller rate limit. Please wait before retrying.")
                    
                    # Log response for debugging
                    field_name = fields_to_try[0] if fields_to_try and fields_to_try[0] else "no_mfa"
                    logger.debug(f"Auth attempt endpoint={endpoint} field={field_name} status={response.status_code} has_cookie={bool(cookie)}")
                    if response_data:
                        logger.debug(f"Response data keys: {list(response_data.keys()) if isinstance(response_data, dict) else 'not a dict'}")

                    # UniFi 9.5 /api/auth/login returns 200 with session in cookies and no JSON body
                    if "/api/auth/login" in endpoint and response.status_code == 200:
                        logger.info("Logged in successfully (UniFi 9.5+ auth).")
                        self.session_cookie = cookie
                        self.http_session = session
                        self.save_session_to_file()
                        # Reset failed auth counter on successful login
                        if self.base_url in self._failed_auth_count:
                            self._failed_auth_count[self.base_url] = 0
                        return
                    # Legacy: Check for meta.rc == "ok"
                    if isinstance(response_data, dict) and response_data.get("meta", {}).get("rc") == "ok":
                        logger.info("Logged in successfully (legacy auth).")
                        self.session_cookie = cookie
                        self.http_session = session
                        self.save_session_to_file()
                        # Reset failed auth counter on successful login
                        if self.base_url in self._failed_auth_count:
                            self._failed_auth_count[self.base_url] = 0
                        return
                    # Fallback: Accept 200 with cookie
                    if response.status_code == 200 and cookie:
                        logger.info("Logged in successfully (cookie-based auth).")
                        self.session_cookie = cookie
                        self.http_session = session
                        self.save_session_to_file()
                        # Reset failed auth counter on successful login
                        if self.base_url in self._failed_auth_count:
                            self._failed_auth_count[self.base_url] = 0
                        return
                    elif isinstance(response_data, dict) and response_data.get("meta", {}).get("msg") == "api.err.Invalid2FAToken":
                        if self.mfa_secret:
                            logger.warning("Invalid 2FA token detected. Waiting for the next token...")
                            import time
                            time_remaining = otp.interval - (int(time.time()) % otp.interval)
                            logger.warning(f"Invalid 2FA token detected. Next token available in {time_remaining}s.")
                            while time_remaining > 0:
                                logger.debug(f"\rRetrying authentication in {time_remaining} seconds...", end="")
                                time.sleep(1)
                                time_remaining -= 1
                            logger.debug("\nRetrying now!")
                            return self.authenticate(retry_count=retry_count + 1, max_retries=max_retries)
                        else:
                            logger.error("2FA token required but MFA_SECRET not provided")
                            continue  # Try next auth method
                    else:
                        # Minimal debug for failures
                        snippet = None
                        try:
                            snippet = json.dumps(response_data)[:200]
                        except Exception:
                            snippet = str(response.text)[:200] if hasattr(response, 'text') else str(response_data)
                        logger.debug(f"Auth failed endpoint={endpoint} field={field_name} status={response.status_code} body_snippet={snippet}")
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
            error_msg = last_error.get('meta', {}).get('msg')
            
            # Check for authentication rate limiting
            if error_msg == "authentication_failed_limit_reached":
                logger.error("UniFi controller authentication rate limit reached!")
                logger.error("Please wait 5-10 minutes before trying again.")
                raise Exception("AUTHENTICATION_FAILED_LIMIT_REACHED: UniFi controller rate limit. Please wait before retrying.")
            
            if error_msg == "api.err.Invalid":
                logger.error(f'Login failed, invalid credentials.')
                return None
            
            # Track failed authentication attempts across calls
            if self.base_url not in self._failed_auth_count:
                self._failed_auth_count[self.base_url] = 0
            
            self._failed_auth_count[self.base_url] += 1
            
            # If we're getting repeated login failures with no specific error, it might be rate limiting
            if error_msg is None:
                if self._failed_auth_count[self.base_url] == 1:
                    logger.error(f"Login failed (attempt {self._failed_auth_count[self.base_url]})")
                else:
                    logger.error(f"Login failed - detecting rate limit pattern (attempt {self._failed_auth_count[self.base_url]})")
                # Debug: Show the actual response structure
                logger.debug(f"Full error response: {last_error}")
                if self._failed_auth_count[self.base_url] >= 2:  # After 2+ attempts with no specific error - likely rate limiting
                    logger.error("UniFi controller rate limit detected!")
                    logger.error("Please wait 5-10 minutes before trying again.")
                    raise Exception("AUTHENTICATION_FAILED_LIMIT_REACHED: UniFi controller rate limit. Please wait before retrying.")
                else:
                    # First time failure - minimal logging
                    raise Exception("Login failed.")
            else:
                # We have a specific error message - check for rate limiting in multiple formats
                rate_limit_indicators = [
                    error_msg,  # meta.msg format
                    last_error.get("code"),  # Direct code format
                    last_error.get("message")  # Direct message format
                ]
                
                rate_limit_messages = [
                    "authentication_failed_limit_reached",
                    "AUTHENTICATION_FAILED_LIMIT_REACHED",
                    "rate.limit.exceeded", 
                    "too.many.requests",
                    "authentication.limit.reached",
                    "You've reached the login attempt limit"
                ]
                
                if any(indicator in rate_limit_messages for indicator in rate_limit_indicators if indicator):
                    logger.error("UniFi controller rate limit detected!")
                    logger.error("Please wait 5-10 minutes before trying again.")
                    raise Exception("AUTHENTICATION_FAILED_LIMIT_REACHED: UniFi controller rate limit. Please wait before retrying.")
                
                logger.error(f"Login failed: {error_msg}")
                raise Exception("Login failed.")

    def make_request(self, endpoint, method="GET", data=None, params=None, retry_count=0, max_retries=3):
        """Makes an authenticated request to the UniFi API."""
        
        
        # Check if permission error was detected in another thread
        from .permission_flag import is_permission_error_detected
        if is_permission_error_detected():
            raise PermissionError("Permission error detected in another thread - stopping this thread.")
        # if not self.session_cookie or not self.csrf_token:
        logger.debug(f"Session check - api_key: {bool(self.api_key)}, session_cookie: {bool(self.session_cookie)}, http_session: {bool(self.http_session)}")
        if not self.api_key and not (self.session_cookie or self.http_session):
            logger.info("No valid session. Authenticating...")
            self.authenticate()
        else:
            logger.debug("Using existing session")

        headers = {
            "Content-Type": "application/json"
        }
        
        # Add CSRF token if available (required for UniFi 9.5+)
        if self.http_session:
            # Try to get CSRF token from cookies first
            csrf_token = self.http_session.cookies.get("csrf_token") or self.http_session.cookies.get("X-CSRF-Token")
            if csrf_token:
                headers["X-CSRF-Token"] = csrf_token
            elif hasattr(self, 'csrf_token') and self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
            else:
                # Extract CSRF token from JWT TOKEN cookie
                token_cookie = self.http_session.cookies.get("TOKEN")
                if token_cookie:
                    try:
                        import base64
                        import json
                        # Decode JWT payload (middle part)
                        payload = token_cookie.split('.')[1]
                        # Add padding if needed
                        payload += '=' * (4 - len(payload) % 4)
                        decoded = base64.b64decode(payload)
                        token_data = json.loads(decoded)
                        csrf_token = token_data.get('csrfToken')
                        if csrf_token:
                            headers["X-CSRF-Token"] = csrf_token
                    except Exception as e:
                        logger.debug(f"Failed to extract CSRF token from JWT: {e}")
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
                # Only retry authentication once to avoid rate limiting
                if retry_count == 0 and not self.api_key:
                    logger.warning("Session expired or unauthorized. Re-authenticating...")
                    self.authenticate()
                    return self.make_request(endpoint, method, data, retry_count=1)
                else:
                    logger.error(f"Authentication failed after retry attempt for {url}")
                    return response.json() if response.content else {}
            elif response.status_code == 400:
                # Log API errors for debugging
                response_data = response.json()
                logger.error(f"Request failed with 400: {response_data.get('meta', {}).get('msg')}")
                return response_data
            elif response.status_code == 403:
                # Log permission issues as warnings, not errors
                self.permission_error_count += 1
                logger.warning(f"Permission denied (403) for {url} - admin account lacks write permissions")
                
                # If we've seen multiple permission errors, suggest using API key
                if self.permission_error_count >= 2:
                    logger.warning("=" * 80)
                    logger.warning("PERMISSION ISSUE DETECTED")
                    logger.warning("Your admin account can read data but cannot modify configuration.")
                    logger.warning("SOLUTIONS:")
                    logger.warning("1. Ensure admin account has 'Device Configuration' permissions")
                    logger.warning("2. Or use API key authentication with Full Admin access")
                    logger.warning("=" * 80)
                    
                    # Set the global permission error flag
                    from .permission_flag import set_permission_error
                    set_permission_error()
                    
                    # Call the permission callback if provided
                    if self.permission_callback:
                        self.permission_callback()
                    
                    raise PermissionError("Admin account lacks write permissions. See logged solutions above.")
                
                return None

            response.raise_for_status()
            try:
                response_data = response.json()
                if "networkconf" in endpoint:
                    logger.debug(f"API RESPONSE - Status: {response.status_code}")
                    logger.debug(f"RESPONSE DATA: {response_data}")
                return response_data
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
