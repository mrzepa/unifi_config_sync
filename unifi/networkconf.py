from unifi.resources import BaseResource
import logging
logger = logging.getLogger(__name__)

class NetworkConf(BaseResource):
    BASE_PATH = 'rest'

    def __init__(self, unifi, site, **kwargs):
        self.unifi = unifi
        self.site = site
        self.output_dir: str = kwargs.get('output_dir', "network_configs")
        super().__init__(unifi, site, endpoint='networkconf', base_path=self.BASE_PATH, **kwargs)


