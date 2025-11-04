from unifi.resources import BaseResource
import logging
logger = logging.getLogger(__name__)

class NetworkConf(BaseResource):
    def __init__(self, unifi, site, **kwargs):
        self.unifi = unifi
        self.site = site
        self.output_dir: str = kwargs.get('output_dir', "network_configs")
        super().__init__(unifi, endpoint='networkconf', site=site, **kwargs)


