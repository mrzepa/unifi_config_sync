import json
from dotenv import load_dotenv
import os
import sys
import logging
import warnings
import requests
from icecream import ic
import argparse
from urllib3.exceptions import InsecureRequestWarning
from unifi.unifi import Unifi
import config
import utils
from utils import setup_logging
import glob
import csv

# Suppress only the InsecureRequestWarning
warnings.simplefilter("ignore", InsecureRequestWarning)

logger = logging.getLogger(__name__)

def read_json_files(directory):
    json_files = glob.glob(os.path.join(directory, '*.json'))
    data_list = []

    for file in json_files:
        with open(file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            data_list.append(data)

    return data_list

def vlan_report(unifi, site_name: str, context: dict = None):
    ui_site = unifi.sites[site_name]
    # get the list of items for the site
    site_vlans = ui_site.network_conf.all()
    template_vlans = context.get('template_vlans')
    if not template_vlans:
        logger.error(f'Could not get vlans from base site.')
        return None, None

    # convert VLAN lists to dictionaries indexed by VLAN ID
    template_lookup = {vlan["vlan"]: vlan for vlan in template_vlans if vlan["name"] != "Default"}
    site_lookup = {vlan["vlan"]: vlan for vlan in site_vlans if vlan["name"] != "Default"}

    report = []

    for vlan_id, template_vlan in template_lookup.items():
        site_vlan = site_lookup.get(vlan_id)
        if not site_vlan:
            report.append(f"VLAN ID {vlan_id}: ('{template_vlan['name']}') is Missing from site.")
        else:
            template_vlan_name = template_vlan["name"]
            site_vlan_name = site_vlan["name"]
            if template_vlan_name != site_name:
                if template_vlan_name.lower() == site_vlan_name.lower():
                    report.append(
                        f"VLAN ID {vlan_id}: Name differs by case ('{template_vlan_name}' != '{site_vlan_name}').")
                else:
                    report.append(f"VLAN ID {vlan_id}: Different name ('{template_vlan_name}' != '{site_vlan_name}').")

    return report


def structured_vlan_comparison(unifi, site_name: str, context: dict = None,):
    ui_site = unifi.sites[site_name]
    # get the list of items for the site
    site_vlans = ui_site.network_conf.all()
    template_vlans = context.get('template_vlans')
    # Create lookup dicts indexed by VLAN ID
    template_lookup = {vlan["vlan"]: vlan for vlan in template_vlans if vlan["name"] != "Default"}
    try:
        site_lookup = {vlan["vlan"]: vlan for vlan in site_vlans if vlan["name"] != "Default"}
    except KeyError:
        # If site has no VLANs after excluding "Default", report all template VLANs as missing.
        vlan_status = {vlan_id: 'Missing' for vlan_id in template_lookup}
        return vlan_status

    # Stores per-VLAN status
    vlan_status = {}

    for vlan_id, template_vlan in template_lookup.items():
        site_vlan = site_lookup.get(vlan_id)
        if not site_vlan:
            vlan_status[vlan_id] = 'Missing'
        else:
            template_vlan_name = template_vlan["name"]
            site_vlan_name = site_vlan["name"]
            if template_vlan_name != site_vlan_name:
                if template_vlan_name.lower() == site_vlan_name.lower():
                    vlan_status[vlan_id] = f"Name differs by case ('{template_vlan_name}' != '{site_vlan_name}')"
                else:
                    vlan_status[vlan_id] = f"Different name ('{template_vlan_name}' != '{site_vlan_name}')"
            else:
                vlan_status[vlan_id] = 'Match'  # optional: report exact matches explicitly or leave blank

    return vlan_status

def generate_vlan_csv_report(report_data, output_csv_path):
    # Gather unique VLAN IDs across all sites for CSV headers
    all_vlan_ids = sorted({vlan_id for data in report_data.values() for vlan_id in data.keys()})

    headers = ['site_name'] + [f'vlan_{vlan_id}' for vlan_id in all_vlan_ids]

    with open(output_csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()

        for site_name, vlan_data in report_data.items():
            row = {'site_name': site_name}
            for vlan_id in all_vlan_ids:
                status = vlan_data.get(vlan_id, 'Not Present in Template')
                row[f'vlan_{vlan_id}'] = status
            writer.writerow(row)


if __name__ == "__main__":
    env_path = os.path.join(os.path.expanduser("~"), ".env")
    load_dotenv()
    ENDPOINT = 'Network Vlan Report'

    parser = argparse.ArgumentParser(description=f"{ENDPOINT} Management Script")

    # Add the verbose flag
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output (debug level logging)"
    )

    # Parse the arguments
    args = parser.parse_args()

    # Set up logging based on the verbose flag
    if args.verbose:
        setup_logging(logging.DEBUG)
    else:
        setup_logging(logging.INFO)

    # Read in the environment variables
    try:
        ui_username = os.getenv("UI_USERNAME")
        ui_password = os.getenv("UI_PASSWORD")
        ui_mfa_secret = os.getenv("UI_MFA_SECRET")

    except KeyError as e:
        logger.critical("Unifi username or password is missing from environment variables.")
        raise SystemExit(1)

    # get the list of controllers
    controller_list = config.CONTROLLERS
    logger.info(f'Found {len(controller_list)} controllers.')

    endpoint_dir = 'network_conf'
    if os.path.exists(endpoint_dir):
        template_vlans = read_json_files(endpoint_dir)
    else:
        logger.error(f'Could not get vlans from base site.')
        raise SystemExit(1)

    if 'Default' in template_vlans:
        template_vlans.remove('Default')

    process_fucntion = vlan_report
    report = {}
    # go through each controller
    for controller in controller_list:
        ui = Unifi(controller, ui_username, ui_password, ui_mfa_secret)

        all_sites = ui.get_sites()
        # get the report for each site on the controller
        for site_name in all_sites:

            context = {'template_vlans': template_vlans,}

            if site_name not in report:
                report[site_name] = {}
            else:
                logger.warning(f'Site name {site_name} on controller {controller} is a duplicate site name.')
                continue
            # group the reports by site name
            report[site_name] = structured_vlan_comparison(ui, site_name, context)

    generate_vlan_csv_report(report, 'vlan_comparison.csv')

