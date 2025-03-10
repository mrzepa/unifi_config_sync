import json
from dotenv import load_dotenv
import os
import sys
import logging
import warnings
import requests
from icecream import ic
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning
from utils import process_single_controller, save_dicts_to_json, read_json_file
from config import SITE_NAMES
from unifi.unifi import Unifi
import config
import utils
from utils import setup_logging, get_filtered_files, get_valid_names_from_dir, validate_names
from unifi.sites import Sites

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

load_dotenv()
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    setup_logging(logging.DEBUG)

    # Read in the environment variables
    try:
        ui_username = os.getenv("UI_USERNAME")
        ui_password = os.getenv("UI_PASSWORD")
        ui_mfa_secret = os.getenv("UI_MFA_SECRET")

    except KeyError as e:
        logger.exception("Unifi username or password is missing from environment variables.")
        raise SystemExit(1)

    vlan_dict = {}
    for controller in config.CONTROLLERS:
        unifi = Unifi(controller, ui_username, ui_password, ui_mfa_secret)

        ui_site = unifi.sites[config.BASE_SITE]

        vlans = ui_site.network_conf.all()

        for vlan in vlans:
            vlan_dict.update({vlan['name']: vlan['vlan']})

    with open('vlans.json', 'w') as f:
        json.dump(vlan_dict, f, indent=4)