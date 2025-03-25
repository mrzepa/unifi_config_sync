import logging
from icecream import ic
import os
from requests.exceptions import HTTPError
from datetime import datetime, timedelta
import json
import threading

file_lock = threading.Lock()

logger = logging.getLogger(__name__)

class BaseResource:

    def __init__(self, unifi, site, endpoint, **kwargs):
        self.unifi = unifi
        self.endpoint: str = endpoint
        self.data: dict = {}  # Dict that contains all the info about this resource.
        self._id: int = None  # The resource ID
        self.name: str = kwargs.get('name', None)
        self.site = site
        self.base_path: str = kwargs.get('base_path', None)
        self.api_path: str = kwargs.get('api_path', None)

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
        if self.base_path:
            url = f"{self.api_path}/{site_name}/{self.base_path}/{self.endpoint}"
        else:
            url = f"{self.api_path}/{site_name}/{self.endpoint}"
        matching_items = []
        all_items = self.unifi.make_request(url, 'GET')
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
        if self.base_path:
            url = f"{self.api_path}/{site_name}/{self.base_path}/{self.endpoint}"
        else:
            url = f"{self.api_path}/{site_name}/{self.endpoint}"
        all_items = self.unifi.make_request(url, 'GET')
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
        if not data:
            data = self.data
        if not data:
            raise ValueError(f'No data to create {self.endpoint}.')
        if self.base_path:
            url = f"{self.api_path}/{site_name}/{self.base_path}/{self.endpoint}"
        else:
            url = f"{self.api_path}/{site_name}/{self.endpoint}"
        response = self.unifi.make_request(url, 'POST', data=data)
        if response.get("meta", {}).get('rc') == 'ok':
            logger.info(f"Successfully created {self.endpoint} at site '{self.site.desc}'")
            return response.get('data', {})
        else:
            return response.get('meta', {})

    def update(self, data: dict = None, path: str = None):
        site_name = self.site.name
        if not data:
            data = self.data
        if not data:
            raise ValueError(f'No data to create {self.endpoint}.')
        if path:
            if self.base_path:
                url = f"{self.api_path}/{site_name}/{self.base_path}/{self.endpoint}/{path}"
            else:
                url = f"{self.api_path}/{site_name}/{self.endpoint}/{path}"
        else:
            if self.base_path:
                url = f"{self.api_path}/{site_name}/{self.base_path}/{self.endpoint}/{self._id}"
            else:
                url = f"{self.api_path}/{site_name}/{self.endpoint}/{self._id}"
            path = None
        response = self.unifi.make_request(url, 'PUT', data=data)
        if response.get("meta", {}).get('rc') == 'ok':
            logger.info(f"Successfully updated {self.endpoint} with ID {self._id if self._id else path} at site '{self.site.desc}'")
            return response.get('data', {})
        else:
            logger.error(f"Failed to update {self.endpoint} with ID {self._id}: {response}")
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
        if not item_id:
            item_id = self._id
        if not item_id:
            raise ValueError(f'Item ID required to delete {self.endpoint}.')
        if self.base_path:
            url = f"{self.api_path}/{site_name}/{self.base_path}/{self.endpoint}/{item_id}"
        else:
            url = f"{self.api_path}/{site_name}/{self.endpoint}/{item_id}"
        response = self.unifi.make_request(url, 'DELETE')
        if response.get("meta", {}).get('rc') == 'ok':
            logger.info(f"Successfully deleted {self.endpoint} with ID {item_id} at site '{site_name}'")
            return True
        else:
            logger.error(f"Failed to delete {self.endpoint} with ID {item_id} at site {site_name}: {response}")
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