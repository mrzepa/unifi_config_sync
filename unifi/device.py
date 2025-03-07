from unifi.resources import BaseResource
import logging

logger = logging.getLogger(__name__)


class Device(BaseResource):
    BASE_PATH = 'stat'

    def __init__(self, unifi, site, **kwargs):
        self.unifi = unifi
        self.site = site
        super().__init__(unifi, endpoint='device', site=self.site, base_path=self.BASE_PATH, **kwargs)


