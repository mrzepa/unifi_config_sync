from unifi.resources import BaseResource
import logging
logger = logging.getLogger(__name__)

class RadiusProfile(BaseResource):
    BASE_PATH = 'rest'

    def __init__(self, unifi, site, **kwargs):
        self.unifi = unifi
        self.site = site
        super().__init__(unifi, endpoint='radiusprofile', site=self.site, base_path=self.BASE_PATH, **kwargs)


