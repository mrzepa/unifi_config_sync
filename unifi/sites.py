from icecream import ic
import logging
from .portconf import PortConf
from .device import Device
from .radiusprofile import RadiusProfile
from .setting import Setting
logger = logging.getLogger(__name__)

class Sites:

    def __init__(self, unifi, data):
        """
        :param unifi: Unifi instance
        :param data: Dictionary with site data (name, description, etc.)
        """

        self.unifi = unifi
        self.name: str = data.get("name")
        self.desc = data.get("desc")
        self._id = data.get("_id")

        # Initialize resource classes
        self.port_conf = PortConf(self.unifi, self)
        self.device = Device(self.unifi, self)
        self.radius_profile = RadiusProfile(self.unifi, self)
        self.setting = Setting(self.unifi, self)

    def __str__(self):
        return f"{self.__class__.__name__}: {self.desc}"

    def __repr__(self):
        return f"<Site(name={self.name}, desc={self.desc})>"

    def __eq__(self, other):
        return self._id == other._id
