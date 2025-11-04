import logging
import os
from requests.exceptions import HTTPError
from datetime import datetime, timedelta
import json
import threading

from unifi.endpoints import get_resource_candidate_urls, APIVersion
logger = logging.getLogger(__name__)

file_lock = threading.Lock()

class BaseResource:

    def __init__(self, unifi, site, endpoint, **kwargs):
        self.unifi = unifi
        self.endpoint: str = endpoint
        self.data: dict = {}  # Dict that contains all the info about this resource.
        self._id: int = None  # The resource ID
        self.name: str = kwargs.get('name', None)
        self.site = site
        self.output_dir: str = kwargs.get('output_dir', None)

    def __str__(self):
        return f"{self.__class__.__name__}: {self.name}"

    def __repr__(self):
        return f"{self.__class__.__name__}(endpoint={self.endpoint!r}, _id={self._id!r})"

    def __eq__(self, other):
        return self._id == other._id

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value: str):
        if value:
            if not isinstance(value, str):
                raise ValueError(f'The attribute [name] must be of type str, not {type(value)}.')
        self._name = value

    def get(self, **filters):
        """
        Fetches and returns a single resource from the API based on the specified filters. The method
        retrieves all items available through the API endpoint and filters them according to the given
        parameters. If no items match the filters or if more than one item matches, an error is raised.

        :param filters: Key-value arguments representing the filters to apply to the API response.
                        The filters should match specific attributes of the resources.
        :type filters: dict
        :return: An instance of the class initialized with the data of the matching resource.
        :rtype: object
        :raises ValueError: When the resource retrieval fails or if the filters result in either no
                            matching resources or multiple matches.
        """
        site_name = self.site.name
        site_id = getattr(self.site, '_id', None)
        site_tokens = [t for t in [site_name, site_id] if t]
        
        # Use endpoint registry to get candidate URLs
        candidates = get_resource_candidate_urls(self.endpoint, site_tokens)
        
        matching_items = []
        all_items = None
        for url, api_version in candidates:
            logger.debug(f"Trying {self.endpoint} endpoint: {url} (API version: {api_version})")
            all_items = self.unifi.make_request(url, 'GET')
            if all_items:
                logger.debug(f"Successfully fetched {self.endpoint} from {api_version}")
                break
        if all_items.get("meta", {}).get('rc') == 'ok':
            for item in all_items.get('data', []):
                if all(item.get(key) == value for key, value in filters.items()):
                    matching_items.append(item)
            if len(matching_items) == 0:
                raise ValueError(f"No resource found for filters: {filters}")
            elif len(matching_items) > 1:
                raise ValueError(
                    f"Multiple resources found for filters: {filters}. Filters must return exactly one result.")

            # Exactly one item is retrieved; set it as the instance's data
            data = matching_items[0]
            instance = self.__class__(self.unifi, self.site, **data)
            instance._id = data.get("_id", None)  # Set the item's ID if available
            instance.name = data.get("name", None)
            instance.data = data  # Populate data
            return instance
        else:
            raise ValueError(f"Failed to retrieve resource: {all_items.get('meta', {}).get('msg')}")

    def all(self) -> list:
        """
        Fetches all available items from the endpoint.

        This method constructs the request URL using the attributes of the class,
        sends a GET request to retrieve data from the specified endpoint, and
        returns the items if the response indicates success. If the response
        does not indicate success, an empty list is returned.

        :return: A list of items retrieved from the endpoint.
        :rtype: list
        """
        site_name = self.site.name
        site_id = getattr(self.site, '_id', None)
        site_tokens = [t for t in [site_name, site_id] if t]
        
        # Use endpoint registry to get candidate URLs
        candidates = get_resource_candidate_urls(self.endpoint, site_tokens)
        
        all_items = None
        for url, api_version in candidates:
            logger.debug(f"Trying {self.endpoint} endpoint: {url} (API version: {api_version})")
            all_items = self.unifi.make_request(url, 'GET')
            if all_items is not None:
                logger.debug(f"Successfully fetched {self.endpoint} from {api_version}")
                break
        if not all_items:
            logger.error(f'Could not get data for {self.endpoint}.')
            return []
        if isinstance(all_items, list):
            return all_items
        if all_items.get("meta", {}).get('rc') == 'ok':
            return all_items.get('data', [])
        else:
            logger.warning(f'Could not get data for {self.endpoint}. {all_items.get("meta", {}).get("msg")}')
            return []

    def get_id(self, name: str) -> int:
        """
        Retrieves the unique identifier of a given endpoint by its name. The method matches the
        specified name with the set of data returned from the predefined endpoint's data
        retrieval process.

        If successful, it returns the unique identifier (_id) of the matching endpoint. If there
        is any issue, such as the name not being found or the response being invalid, it logs
        an error or warning and returns None.

        :param name: The name of the endpoint used to search for its unique identifier.
        :type name: str
        :raises ValueError: If the provided name is empty or None.
        :return: The unique identifier (_id) of the endpoint if found, otherwise None.
        :rtype: int or None
        """
        if not name:
            raise ValueError(f'Name required to get the endpoint id.')

        response = self.all()
        if response:
            for item in response:
                if item.get('name') == name:
                    return item.get('_id')
        else:
            logger.error(f'Could not find {self.endpoint} ID for {name}.')
            return None

        logger.warning(f'Could not find {self.endpoint} ID for {name}.')
        return None

    def create(self, data: dict = None):
        """
        Creates a new resource using the provided data, or default data if none is
        explicitly supplied. This method constructs the appropriate API endpoint
        URL using the site's name and other instance-specific attributes, then sends
        a POST request to the URL with the given data. If the API call is successful,
        it logs a success message and returns the created resource's data. If the
        request fails, it logs an error message and returns None.

        :param data: The data payload to send in the POST request. Defaults to
            the instance's existing `data` attribute if not explicitly provided.
            If both are absent, a `ValueError` is raised.
        :type data: dict, optional
        :return: Data of the created resource if the request is successful, or None
            otherwise.
        :rtype: dict or None
        :raises ValueError: If no data is provided to create the resource.
        """
        site_name = self.site.name
        site_id = getattr(self.site, '_id', None)
        site_tokens = [t for t in [site_name, site_id] if t]
        if not data:
            data = self.data
        if not data:
            raise ValueError(f'No data to create {self.endpoint}.')
        
        # Use endpoint registry to get candidate URLs
        candidates = get_resource_candidate_urls(self.endpoint, site_tokens)
        
        response = {}
        for url, api_version in candidates:
            logger.debug(f"Trying {self.endpoint} create endpoint: {url} (API version: {api_version})")
            # Check if this is UniFi 9.5+ and filter fields accordingly
            create_data = data
            if hasattr(self.unifi, 'http_session') and self.unifi.http_session:
                # UniFi 9.5+ uses session-based auth - filter to browser-like fields
                if self.endpoint == 'networkconf':
                    essential_fields = [
                        'vlan_enabled', 'purpose', 'name', 'vlan', 
                        'enabled', 'is_nat', 'igmp_snooping', 'dhcpguard_enabled', 
                        'network_isolation_enabled', 'ip_subnet', 'dhcpd_enabled', 
                        'dhcpd_start', 'dhcpd_stop', 'domain_name', 'mdns_enabled'
                    ]
                    filtered_data = {}
                    for key, value in data.items():
                        # Only include essential fields that the browser sends
                        if key in essential_fields:
                            filtered_data[key] = value
                    create_data = filtered_data
            
            resp_try = self.unifi.make_request(url, 'POST', data=create_data)
            if resp_try is not None:
                response = resp_try
                logger.debug(f"Successfully created {self.endpoint} using {api_version}")
                break
            else:
                logger.debug(f"API returned None response for {url}")
        
        if response is None:
            logger.warning(f"Unable to create {self.endpoint}: Admin account lacks write permissions")
            return {}
        
        # Debug: Log the actual response structure
        logger.debug(f"Create response type: {type(response)}")
        logger.debug(f"Create response content: {response}")
        
        if not isinstance(response, dict):
            logger.error(f"Failed to create {self.endpoint}: Unexpected response type {type(response)} - Response: {response}")
            return {}
        
        if response.get("meta", {}).get('rc') == 'ok':
            logger.info(f"Successfully created {self.endpoint} at site '{self.site.desc}'")
            return response.get('data', {})
        else:
            meta = response.get('meta', {})
            error_msg = meta.get('msg', 'Unknown error')
            error_rc = meta.get('rc', 'Unknown rc')
            
            # Handle specific error cases with friendly messages
            if error_msg == 'api.err.TooManyWirelessNetwork':
                device_mac = meta.get('device_mac', 'Unknown')
                wlan_count = meta.get('wlan_count', 'Unknown')
                max_wlan = meta.get('max_wlan', 'Unknown')
                logger.error(f"Too Many Wireless Networks for device {device_mac} ({wlan_count}/{max_wlan} networks).")
                return {'meta': {'rc': 'error', 'msg': 'api.err.TooManyWirelessNetwork'}}
            else:
                logger.error(f"Failed to create {self.endpoint}: rc={error_rc}, msg={error_msg}")
                logger.error(f"Full response: {response}")
                return response.get('meta', {})

    def update(self, data: dict, path: str = None):
        """Updates an existing item on the UniFi Controller."""
        site_name = self.site.name
        site_id = getattr(self.site, '_id', None)
        site_tokens = [t for t in [site_name, site_id] if t]
        if not data:
            data = self.data
        if not data:
            raise ValueError(f'No data to create {self.endpoint}.')
        
        # Build URLs for update (add path or _id to endpoint)
        base_endpoint = self.endpoint
        logger.debug(f"Base endpoint: {base_endpoint}")
        logger.debug(f"Data _id: {data.get('_id')}")
        logger.debug(f"Self _id: {self._id}")
        logger.debug(f"Path parameter: {path}")
        
        # For UniFi 9.5+, networkconf still needs ID in URL path despite session auth
        is_unifi_95_plus = hasattr(self.unifi, 'http_session') and self.unifi.http_session
        
        # Store the ID for later URL construction
        item_id = None
        if path:
            item_id = path
        elif data.get('_id'):
            item_id = data.get('_id')
        elif self._id:
            item_id = self._id
        
        if not item_id:
            raise ValueError(f"No ID found in data or object for updating {base_endpoint}")
        
        # Always use base endpoint for registry lookup
        self.endpoint = base_endpoint
        logger.debug(f"Base endpoint for registry lookup: {self.endpoint}")
        
        # Use endpoint registry to get candidate URLs
        candidates = get_resource_candidate_urls(self.endpoint, site_tokens)
        
        # Append ID to candidate URLs if needed
        if base_endpoint == 'networkconf' or base_endpoint == 'wlanconf' or not is_unifi_95_plus:
            # For networkconf, wlanconf (all versions) and legacy endpoints, append ID to URL
            candidates = [(f"{url}/{item_id}", api_version) for url, api_version in candidates]
        
        logger.debug(f"Final candidates after ID processing: {candidates}")
        
        response = {}
        for url, api_version in candidates:
            logger.debug(f"Trying {base_endpoint} update endpoint: {url} (API version: {api_version})")
            # Check if this is UniFi 9.5+ and filter fields accordingly
            update_data = data
            if hasattr(self.unifi, 'http_session') and self.unifi.http_session:
                # UniFi 9.5+ uses session-based auth - filter to browser-like fields
                if base_endpoint == 'networkconf':

                    # Ensure _id is in data for networkconf updates
                    if '_id' not in data:
                        data = dict(data)  # Make a copy
                        if path:
                            data['_id'] = path
                        elif hasattr(self, '_id') and self._id:
                            data['_id'] = self._id
                    
                    essential_fields = [
                        'vlan_enabled', 'purpose', '_id', 'site_id', 'name', 'vlan', 
                        'enabled', 'is_nat', 'igmp_snooping', 'dhcpguard_enabled', 
                        'network_isolation_enabled', 'ip_subnet', 'dhcpd_enabled', 
                        'dhcpd_start', 'dhcpd_stop', 'domain_name', 'mdns_enabled'
                    ]
                    filtered_data = {}
                    for key, value in data.items():
                        # Only include essential fields that the browser sends
                        if key in essential_fields:
                            filtered_data[key] = value
                    update_data = filtered_data
                elif base_endpoint == 'wlanconf':
                    # For wlanconf, include all fields but ensure _id is present
                    if '_id' not in data:
                        data = dict(data)  # Make a copy
                        if path:
                            data['_id'] = path
                        elif hasattr(self, '_id') and self._id:
                            data['_id'] = self._id
                    update_data = data
                    
            logger.debug(f"Update data being sent: {update_data}")
            
            resp_try = self.unifi.make_request(url, 'PUT', data=update_data)
            logger.debug(f"Raw response from API: {resp_try}")
            if resp_try is not None:
                response = resp_try
                logger.debug(f"Successfully updated {base_endpoint} using {api_version}")
                break
            else:
                logger.debug(f"API returned None response for {url}")
        
        # Restore original endpoint
        self.endpoint = base_endpoint
        
        if response is None:
            logger.warning(f"Unable to update {base_endpoint}: Admin account lacks write permissions")
            return None
        
        # Debug: Log the actual response structure
        logger.debug(f"Update response type: {type(response)}")
        logger.debug(f"Update response content: {response}")
        
        if not isinstance(response, dict):
            actual_id = data.get('_id') or self._id or path
            logger.error(f"Failed to update {base_endpoint} with ID {actual_id}: Unexpected response type {type(response)} - Response: {response}")
            return None
        
        if response.get("meta", {}).get('rc') == 'ok':
            actual_id = data.get('_id') or self._id or path
            logger.info(f"Successfully updated {base_endpoint} with ID {actual_id} at site '{self.site.desc}'")
            return response.get('data', {})
        else:
            meta = response.get('meta', {})
            error_msg = meta.get('msg', 'Unknown error')
            error_rc = meta.get('rc', 'Unknown rc')
            actual_id = data.get('_id') or self._id or path
            logger.error(f"Failed to update {base_endpoint} with ID {actual_id}: rc={error_rc}, msg={error_msg}")
            logger.error(f"Full response: {response}")
            return None
        
    def delete(self, item_id: int = None):
        """
        Delete an item from a specific endpoint using its ID. This method sends a DELETE request
        to the appropriate URL and logs the success of the deletion operation.

        :param item_id: The ID of the item to delete. If omitted, attempts to use
                        the _id attribute of the object.
        :type item_id: int, optional

        :return: The response data from the delete operation if successful.
        :rtype: dict

        :raises ValueError: If no `item_id` is provided and the `_id` attribute is also not set.
        """
        site_name = self.site.name
        site_id = getattr(self.site, '_id', None)
        site_tokens = [t for t in [site_name, site_id] if t]
        if not item_id:
            item_id = self._id
        if not item_id:
            raise ValueError(f'Item ID required to delete {self.endpoint}.')
        
        # Build URLs for delete (add item_id to endpoint)
        base_endpoint = self.endpoint
        
        # Use endpoint registry to get base URLs, then add item_id
        base_candidates = get_resource_candidate_urls(base_endpoint, site_tokens)
        candidates = [(f"{url}/{item_id}", api_version) for url, api_version in base_candidates]
        
        response = {}
        for url, api_version in candidates:
            logger.debug(f"Trying {base_endpoint} delete endpoint: {url} (API version: {api_version})")
            resp_try = self.unifi.make_request(url, 'DELETE')
            if resp_try:
                response = resp_try
                logger.debug(f"Successfully deleted {base_endpoint} using {api_version}")
                break
        
        if response is None:
            logger.warning(f"Unable to delete {base_endpoint}: Admin account lacks write permissions")
            return False
        
        if response.get("meta", {}).get('rc') == 'ok':
            logger.info(f"Successfully deleted {base_endpoint} with ID {item_id} at site '{site_name}'")
            return True
        else:
            meta = response.get('meta', {})
            error_msg = meta.get('msg', 'Unknown error')
            
            # Handle specific error cases with friendly messages
            if error_msg == 'api.err.NoDelete' and self.endpoint == 'radiusprofile':
                # Check if this is the Default radius profile by looking it up
                try:
                    # Try to get the item name to check if it's Default
                    existing_items = self.all()
                    for item in existing_items:
                        if item.get('_id') == item_id and item.get('name', '').lower() == 'default':
                            logger.info(f'Cannot delete "Default" radius profile. This is expected, ignoring error message.')
                            return False
                except:
                    pass  # If we can't check, fall through to normal error handling
            
            logger.error(f"Failed to delete {base_endpoint} with ID {item_id} at site {site_name}: {error_msg}")
            return False

    def backup(self, backup_dir: str):
        """
        Backup the configuration of the given resource and clean up older backups.

        Each backup file is named after `Site.desc` and stores the configuration in the following structure:
        - object.endpoint:
            - date and time:
                - data

        Files older than 4 months are deleted automatically.

        :param resource: The resource object to back up. Must have `site` and `endpoint` attributes.
        :param backup_dir: Path to the directory where backups will be stored.
        """
        # Ensure the backup directory exists
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            logger.info(f"Backup directory created: {backup_dir}")

        # Get the site description and endpoint
        site_desc = self.site.desc
        endpoint = self.endpoint
        item_id = self._id

        # Current date and time for backup categorization
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")

        # Backup file path
        backup_file_path = os.path.join(backup_dir, f"{site_desc}.json")

        # Prepare the backup data structure
        backup_data = {}
        if os.path.exists(backup_file_path):
            try:
                with open(backup_file_path, "r") as f:
                    backup_data = json.load(f)  # Load existing backup
            except json.JSONDecodeError:
                logger.warning(f"Backup file {backup_file_path} is corrupted. A new backup will be created.")

        if endpoint not in backup_data:
            backup_data[endpoint] = {}

        # Retrieve configuration to be backed up
        data = self.data

        # Add the new backup at the current timestamp and item_id
        if timestamp not in backup_data[endpoint]:
            backup_data[endpoint][timestamp] = {}

        backup_data[endpoint][timestamp][item_id] = data

        # Write back to the backup file
        with file_lock:
            with open(backup_file_path, "w") as f:
                json.dump(backup_data, f, indent=4)
                logger.info(f"Configuration backed up for site '{site_desc}' at endpoint '{endpoint}'.")

        # Clean up old backups (older than 4 months)
        cutoff_date = now - timedelta(days=4 * 30)  # Approximate 4 months as 120 days

        for date_str in list(backup_data[endpoint].keys()):
            backup_date = datetime.strptime(date_str, "%Y-%m-%d_%H-%M-%S")
            if backup_date < cutoff_date:
                del backup_data[endpoint][date_str]
                logger.info(f"Deleted old backup from {date_str} for '{endpoint}'.")

        # Save cleaned data back to the backup file
        with open(backup_file_path, "w") as f:
            json.dump(backup_data, f, indent=4)