import logging
import requests # For requests.post in add_series_to_sonarr
import sys, os # For traceback logging if still used
from utils import make_api_request

logger = logging.getLogger(__name__)

# Load environment variables directly
SONARR_URL = os.environ.get('SONARR_URL')
SONARR_API_KEY = os.environ.get('SONARR_API_KEY')
SONARR_ROOT_FOLDER_ID = int(os.environ.get('SONARR_ROOT_FOLDER_ID', 1)) # Default to 1 if not set
SONARR_QUALITY_PROFILE_ID = int(os.environ.get('SONARR_QUALITY_PROFILE_ID', 1)) # Default to 1 if not set


def search_sonarr(query: str) -> list:
    """Searches Sonarr for a series."""
    if not SONARR_URL or not SONARR_API_KEY:
        # Cannot get traceback here easily as no exception is caught
        logger.error("Sonarr URL or API Key not configured in environment variables.")
        return []
    return make_api_request(SONARR_URL, SONARR_API_KEY, 'series/lookup', {'term': query}) or []

def add_series_to_sonarr(series_info: dict) -> bool:
    """Adds a series to Sonarr."""
    if not SONARR_URL or not SONARR_API_KEY:
        # Cannot get traceback here easily as no exception is caught
        logger.error("Sonarr URL or API Key not configured in environment variables.")
        return False
    payload = {
        "title": series_info['title'],
        "tvdbId": series_info['tvdbId'],
        "qualityProfileId": SONARR_QUALITY_PROFILE_ID, # Use loaded env var
        "rootFolderPath": f"/data/tv", # Default path, Sonarr needs the ID mapping
        "seasons": series_info['seasons'],
        "monitored": True,
        "monitor": "all",
        "addOptions": {
            "searchForMissingEpisodes": True
        }
    }
    # Get the correct root folder path using the ID from env var
    root_folders = make_api_request(SONARR_URL, SONARR_API_KEY, 'rootfolder')
    if root_folders:
        target_folder = next((rf['path'] for rf in root_folders if rf['id'] == SONARR_ROOT_FOLDER_ID), None) # Use loaded env var
        if target_folder:
            payload['rootFolderPath'] = target_folder
        else:
            # Cannot get traceback here easily as no exception is caught
            logger.error(f"Sonarr Root Folder ID {SONARR_ROOT_FOLDER_ID} not found in Sonarr's API response.") # Use loaded env var
            return False
    else:
        # Cannot get traceback here easily as no exception is caught
        logger.error("Could not retrieve Sonarr root folders via API.")
        return False


    # Correcting the add request to be a POST with JSON payload
    headers = {'X-Api-Key': SONARR_API_KEY, 'Content-Type': 'application/json'} # Use loaded env var
    url = f"{SONARR_URL}/api/v3/series" # Use loaded env var
    response = None # Initialize response to None
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        logger.info(f"Series '{series_info['title']}' added successfully to Sonarr.")
        return True
    except requests.exceptions.RequestException as e:
        log_message = f"Failed to add series '{series_info['title']}' to Sonarr."
        if response is not None:
            log_message += f" Sonarr response: {response.text}"
        logger.exception(log_message)
        return False
