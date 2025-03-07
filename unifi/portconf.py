from unifi.resources import BaseResource
from unifi.sites import Sites
import logging
logger = logging.getLogger(__name__)

class PortConf(BaseResource):
    BASE_PATH = 'rest'

    def __init__(self, unifi, site: Sites, **kwargs):
        self.unifi = unifi
        self.site: Sites = site
        super().__init__(unifi, endpoint='portconf', site=self.site, base_path=self.BASE_PATH, **kwargs)


