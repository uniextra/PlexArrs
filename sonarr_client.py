import logging
import requests
import json
from config import (
    SONARR_URL,
    SONARR_API_KEY,
    SONARR_ROOT_FOLDER_ID,
    SONARR_QUALITY_PROFILE_ID,
    DEFAULT_TIMEOUT,
)
from utils import make_api_request, http_session

logger = logging.getLogger(__name__)


def search_sonarr(query: str) -> list:
    """Searches Sonarr for a series."""
    if not SONARR_URL or not SONARR_API_KEY:
        logger.error("Sonarr URL or API Key not configured.")
        return []
    result = make_api_request(SONARR_URL, SONARR_API_KEY, 'series/lookup', {'term': query})
    return result if isinstance(result, list) else []


def add_series_to_sonarr(series_info: dict) -> bool | str:
    """Adds a series to Sonarr."""
    if not SONARR_URL or not SONARR_API_KEY:
        logger.error("Sonarr URL or API Key not configured.")
        return False

    payload = {
        "title": series_info.get('title'),
        "tvdbId": series_info.get('tvdbId'),
        "qualityProfileId": SONARR_QUALITY_PROFILE_ID,
        "rootFolderPath": "/data/tv",
        "seasons": series_info.get('seasons', []),
        "monitored": True,
        "monitor": "all",
        "addOptions": {
            "searchForMissingEpisodes": True
        }
    }

    # Get the correct root folder path using the configured ID
    root_folders = make_api_request(SONARR_URL, SONARR_API_KEY, 'rootfolder')
    if isinstance(root_folders, list) and root_folders:
        target_folder = next((rf['path'] for rf in root_folders if rf.get('id') == SONARR_ROOT_FOLDER_ID), None)
        if target_folder:
            payload['rootFolderPath'] = target_folder
        else:
            logger.error(f"Sonarr Root Folder ID {SONARR_ROOT_FOLDER_ID} not found in Sonarr API response.")
            return False
    else:
        logger.error("Could not retrieve Sonarr root folders via API.")
        return False

    headers = {'X-Api-Key': SONARR_API_KEY, 'Content-Type': 'application/json'}
    url = f"{SONARR_URL}/api/v3/series"
    response = None
    try:
        response = http_session.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        logger.info(f"Series '{series_info.get('title')}' added successfully to Sonarr.")
        return True
    except requests.exceptions.RequestException as e:
        log_message = f"Failed to add series '{series_info.get('title')}' to Sonarr."
        error_code = 'unknown_error'
        if response is not None:
            log_message += f" Sonarr response: {response.text}"
            try:
                error_response = response.json()
                if isinstance(error_response, list) and error_response:
                    first_error = error_response[0]
                    if isinstance(first_error, dict) and 'errorCode' in first_error:
                        error_code = first_error['errorCode']
            except json.JSONDecodeError:
                logger.warning("Failed to decode Sonarr error response JSON.")
            except Exception as json_e:
                logger.warning(f"Unexpected error parsing Sonarr error response: {json_e}")

        logger.exception(log_message)
        return error_code
