from unifi.resources import BaseResource
import logging
logger = logging.getLogger(__name__)

class ApGroups(BaseResource):
    API_PATH = '/v2/api/site'

    def __init__(self, unifi, site, **kwargs):
        self.unifi = unifi
        self.site = site
        self.output_dir: str = kwargs.get('output_dir', "ap_groups")
        super().__init__(unifi, endpoint='apgroups', site=self.site, api_path=self.API_PATH, **kwargs)


