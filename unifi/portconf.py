from unifi.resources import BaseResource
import logging
logger = logging.getLogger(__name__)

class PortConf(BaseResource):
    BASE_PATH = 'rest'
    API_PATH = "/api/s"

    def __init__(self, unifi, site, **kwargs):
        self.unifi = unifi
        self.site = site
        self.output_dir: str = kwargs.get('output_dir', "port_profiles")
        super().__init__(unifi, endpoint='portconf', site=self.site, api_path=self.API_PATH, base_path=self.BASE_PATH, **kwargs)


