from unifi.resources import BaseResource
import logging
logger = logging.getLogger(__name__)

class Device(BaseResource):
    BASE_PATH = 'stat'

    def __init__(self, unifi, site, **kwargs):
        self.unifi = unifi
        self.site = site
        self.output_dir: str = kwargs.get('output_dir', "devices")
        super().__init__(unifi, site, endpoint='device', base_path=self.BASE_PATH, **kwargs)


