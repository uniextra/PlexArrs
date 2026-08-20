import logging
import requests
import json
from config import (
    RADARR_URL,
    RADARR_API_KEY,
    RADARR_ROOT_FOLDER_ID,
    RADARR_QUALITY_PROFILE_ID,
    DEFAULT_TIMEOUT,
)
from utils import make_api_request, http_session

logger = logging.getLogger(__name__)


def search_radarr(query: str) -> list:
    """Searches Radarr for a movie."""
    if not RADARR_URL or not RADARR_API_KEY:
        logger.error("Radarr URL or API Key not configured.")
        return []
    result = make_api_request(RADARR_URL, RADARR_API_KEY, 'movie/lookup', {'term': query})
    return result if isinstance(result, list) else []


def add_movie_to_radarr(movie_info: dict) -> bool | str:
    """Adds a movie to Radarr."""
    if not RADARR_URL or not RADARR_API_KEY:
        logger.error("Radarr URL or API Key not configured.")
        return False

    payload = {
        "title": movie_info.get('title'),
        "tmdbId": movie_info.get('tmdbId'),
        "qualityProfileId": RADARR_QUALITY_PROFILE_ID,
        "rootFolderPath": "/data/movies",
        "monitored": True,
        "addOptions": {
            "searchForMovie": True
        }
    }

    # Get the correct root folder path using the configured ID
    root_folders = make_api_request(RADARR_URL, RADARR_API_KEY, 'rootfolder')
    if isinstance(root_folders, list) and root_folders:
        target_folder = next((rf['path'] for rf in root_folders if rf.get('id') == RADARR_ROOT_FOLDER_ID), None)
        if target_folder:
            payload['rootFolderPath'] = target_folder
        else:
            logger.error(f"Radarr Root Folder ID {RADARR_ROOT_FOLDER_ID} not found in Radarr API response.")
            return False
    else:
        logger.error("Could not retrieve Radarr root folders via API.")
        return False

    headers = {'X-Api-Key': RADARR_API_KEY, 'Content-Type': 'application/json'}
    url = f"{RADARR_URL}/api/v3/movie"
    response = None
    try:
        response = http_session.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        logger.info(f"Movie '{movie_info.get('title')}' added successfully to Radarr.")
        return True
    except requests.exceptions.RequestException as e:
        log_message = f"Failed to add movie '{movie_info.get('title')}' to Radarr."
        error_code = 'unknown_error'
        if response is not None:
            log_message += f" Radarr response: {response.text}"
            try:
                error_response = response.json()
                if isinstance(error_response, list) and error_response:
                    first_error = error_response[0]
                    if isinstance(first_error, dict) and 'errorCode' in first_error:
                        error_code = first_error['errorCode']
            except json.JSONDecodeError:
                logger.warning("Failed to decode Radarr error response JSON.")
            except Exception as json_e:
                logger.warning(f"Unexpected error parsing Radarr error response: {json_e}")

        logger.exception(log_message)
        return error_code
