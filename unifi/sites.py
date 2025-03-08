from icecream import ic
import logging
from .portconf import PortConf
from .device import Device
from .radiusprofile import RadiusProfile
logger = logging.getLogger(__name__)

class Sites:
    BASE_PATH = 'self'
    API_PATH = 'api'

    def __init__(self, unifi, desc, **kwargs):
        self.unifi = unifi
        self.desc: str = desc
        self.name: str = kwargs.get('name', None)
        self._id: int = kwargs.get('_id', None)
        self.data: dict = kwargs.get('data', None)
        if not self.data:
            self.data = self.get()
        if not self._id:
            self._id = self.data.get('_id')
        if not self.name:
            self.name = self.data.get('name')

        # Initialize resource classes
        self.port_conf = PortConf(self.unifi, self)
        self.device = Device(self.unifi, self)
        self.radius_profile = RadiusProfile(self.unifi, self)

    def get(self):
        """
        Fetches information about a specific site associated with the Unifi API, based on the
        `name` attribute specified in the instance. Retrieves all available sites via a GET
        request to the API endpoint and filters for the matching site. If the site is not
        found, an error is logged. Logs an error as well if the request does not return a
        successful response.

        :raises KeyError: If the response data does not include the expected keys.
        :param self: The instance of the class calling this method.

        :return: A dictionary with the details of the site matching the instance's `name`
                 attribute, or `None` if the site is not found or if the response is not
                 successful.
        :rtype: dict | None
        """
        url = f'/{self.API_PATH}/{self.BASE_PATH}/sites'

        all_sites = self.unifi.make_request(url, 'GET')
        if all_sites.get('meta', {}).get('rc') == 'ok':
            for site in all_sites.get('data', []):
                if site.get('desc') == self.desc:
                    return site
            logger.error(f'Site {self.name} not found in {self.unifi.base_url}')
        else:
            logger.error(f'Could not get sites list: {all_sites.get("meta", {}).get("msg")}')

    def __str__(self):
        return f"{self.__class__.__name__}: {self.name}"

    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name!r}, _id={self._id!r})"

    def __eq__(self, other):
        return self._id == other._id
