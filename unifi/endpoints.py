"""
UniFi API endpoint registry for different controller versions and authentication methods.
"""

from typing import Dict, List, Optional, Tuple
from enum import Enum

class APIVersion(Enum):
    """UniFi API versions"""
    LEGACY = "legacy"           # Pre-9.5: /api/s/{site}/rest/*
    UNIFI_9_5 = "unifi_9_5"     # 9.5+: /proxy/network/api/s/{site}/rest/*
    V2 = "v2"                   # 9.5+: /proxy/network/v2/api/site/{site}/*
    INTEGRATION = "integration" # 9.5+: /proxy/network/integration/v1/*

class AuthMethod(Enum):
    """Authentication methods"""
    API_KEY = "api_key"
    SESSION = "session"

# Resource endpoint configurations
RESOURCE_ENDPOINTS = {
    'portconf': {
        APIVersion.LEGACY: '/api/s/{site}/rest/portconf',
        APIVersion.UNIFI_9_5: '/proxy/network/api/s/{site}/rest/portconf',
        APIVersion.V2: None,  # Not available in v2
    },
    'networkconf': {
        APIVersion.LEGACY: '/api/s/{site}/rest/networkconf',
        APIVersion.UNIFI_9_5: '/proxy/network/api/s/{site}/rest/networkconf',
        APIVersion.V2: None,  # Not available in v2
    },
    'radiusprofile': {
        APIVersion.LEGACY: '/api/s/{site}/rest/radiusprofile',
        APIVersion.UNIFI_9_5: '/proxy/network/api/s/{site}/rest/radiusprofile',
        APIVersion.V2: None,  # Not available in v2
    },
    'usergroup': {
        APIVersion.LEGACY: '/api/s/{site}/rest/usergroup',
        APIVersion.UNIFI_9_5: '/proxy/network/api/s/{site}/rest/usergroup',
        APIVersion.V2: None,  # Not available in v2
    },
    'wlanconf': {
        APIVersion.LEGACY: '/api/s/{site}/rest/wlanconf',
        APIVersion.UNIFI_9_5: '/proxy/network/api/s/{site}/rest/wlanconf',
        APIVersion.V2: None,  # Not available in v2
    },
    'setting': {
        APIVersion.LEGACY: '/api/s/{site}/rest/setting',
        APIVersion.UNIFI_9_5: '/proxy/network/api/s/{site}/rest/setting',
        APIVersion.V2: None,  # Not available in v2
    },
    'device': {
        APIVersion.LEGACY: '/api/s/{site}/stat/device',
        APIVersion.UNIFI_9_5: '/proxy/network/api/s/{site}/stat/device',
        APIVersion.V2: None,  # Not available in v2
    },
    'apgroups': {
        APIVersion.LEGACY: None,  # Not available in legacy
        APIVersion.UNIFI_9_5: None,  # Not available in 9.5 legacy style
        APIVersion.V2: '/proxy/network/v2/api/site/{site}/apgroups',
    },
}

# Sites endpoint configurations
SITES_ENDPOINTS = {
    AuthMethod.API_KEY: [
        (APIVersion.INTEGRATION, '/proxy/network/integration/v1/sites'),
    ],
    AuthMethod.SESSION: [
        (APIVersion.V2, '/proxy/network/v2/api/site'),
        (APIVersion.UNIFI_9_5, '/proxy/network/api/self/sites'),
        (APIVersion.LEGACY, '/api/self/sites'),
    ],
}

# Authentication endpoints
AUTH_ENDPOINTS = [
    '/api/auth/login',
    '/api/login',
]

def get_resource_endpoint(resource_name: str, api_version: APIVersion) -> Optional[str]:
    """Get the endpoint for a resource based on API version."""
    if resource_name not in RESOURCE_ENDPOINTS:
        return None
    
    return RESOURCE_ENDPOINTS[resource_name].get(api_version)

def get_resource_candidate_urls(resource_name: str, site_tokens: List[str]) -> List[Tuple[str, str]]:
    """Get all candidate URLs for a resource, trying different API versions."""
    candidates = []
    
    # Try each API version in priority order
    for api_version in [APIVersion.UNIFI_9_5, APIVersion.V2, APIVersion.LEGACY]:
        endpoint_template = get_resource_endpoint(resource_name, api_version)
        if not endpoint_template:
            continue
            
        for site_token in site_tokens:
            url = endpoint_template.format(site=site_token)
            candidates.append((url, api_version.value))
    
    return candidates

def get_sites_candidate_urls(auth_method: AuthMethod) -> List[Tuple[str, str]]:
    """Get all candidate URLs for sites endpoint based on auth method."""
    candidates = []
    
    for api_version, endpoint in SITES_ENDPOINTS.get(auth_method, []):
        candidates.append((endpoint, api_version.value))
    
    return candidates
