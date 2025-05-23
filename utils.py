import logging
import requests
import json
import re

from config import ALLOWED_USER_IDS

logger = logging.getLogger(__name__)

def is_user_allowed(user_id: int) -> bool:
    """Checks if the user is allowed to use the bot based on environment variable."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

def make_api_request(base_url: str, api_key: str, endpoint: str, params: dict = None) -> dict | None:
    """Makes a generic API request."""
    headers = {'X-Api-Key': api_key}
    url = f"{base_url}/api/v3/{endpoint}"
    full_url = url
    if params:
        query_string = '&'.join([f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()])
        full_url += f"?{query_string}"
    logger.info(f"Attempting API request to: {full_url}")
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        logger.debug(f"API request successful for {url}. Status: {response.status_code}")
        return response.json()
    except requests.exceptions.RequestException:
        logger.exception(f"API request failed for {url}.")
        return None
    except json.JSONDecodeError:
        logger.exception(f"Failed to decode JSON response from {url}")
        return None
