from unifi.resources import BaseResource
import logging
logger = logging.getLogger(__name__)

class UserGroup(BaseResource):
    def __init__(self, unifi, site, **kwargs):
        self.unifi = unifi
        self.site = site
        self.output_dir: str = kwargs.get('output_dir', "user_groups")
        super().__init__(unifi, endpoint='usergroup', site=site, **kwargs)


