import logging
import requests # For requests.post in add_movie_to_radarr
import sys, os # For traceback logging if still used
from utils import make_api_request

logger = logging.getLogger(__name__)

# Load environment variables directly
RADARR_URL = os.environ.get('RADARR_URL')
RADARR_API_KEY = os.environ.get('RADARR_API_KEY')
RADARR_ROOT_FOLDER_ID = int(os.environ.get('RADARR_ROOT_FOLDER_ID', 1)) # Default to 1 if not set
RADARR_QUALITY_PROFILE_ID = int(os.environ.get('RADARR_QUALITY_PROFILE_ID', 1)) # Default to 1 if not set


def search_radarr(query: str) -> list:
    """Searches Radarr for a movie."""
    if not RADARR_URL or not RADARR_API_KEY:
        # Cannot get traceback here easily as no exception is caught
        logger.error("Radarr URL or API Key not configured in environment variables.")
        return []
    return make_api_request(RADARR_URL, RADARR_API_KEY, 'movie/lookup', {'term': query}) or []

def add_movie_to_radarr(movie_info: dict) -> bool:
    """Adds a movie to Radarr."""
    if not RADARR_URL or not RADARR_API_KEY:
        # Cannot get traceback here easily as no exception is caught
        logger.error("Radarr URL or API Key not configured in environment variables.")
        return False
    payload = {
        "title": movie_info['title'],
        "tmdbId": movie_info['tmdbId'],
        "qualityProfileId": RADARR_QUALITY_PROFILE_ID, # Use loaded env var
        "rootFolderPath": f"/data/movies", # Default path, Radarr needs the ID mapping
        "monitored": True,
        "addOptions": {
            "searchForMovie": True
        }
    }
    # Get the correct root folder path using the ID from env var
    root_folders = make_api_request(RADARR_URL, RADARR_API_KEY, 'rootfolder')
    if root_folders:
        target_folder = next((rf['path'] for rf in root_folders if rf['id'] == RADARR_ROOT_FOLDER_ID), None) # Use loaded env var
        if target_folder:
            payload['rootFolderPath'] = target_folder
        else:
            # Cannot get traceback here easily as no exception is caught
            logger.error(f"Radarr Root Folder ID {RADARR_ROOT_FOLDER_ID} not found in Radarr's API response.") # Use loaded env var
            return False
    else:
        # Cannot get traceback here easily as no exception is caught
        logger.error("Could not retrieve Radarr root folders via API.")
        return False

    # Correcting the add request to be a POST with JSON payload
    headers = {'X-Api-Key': RADARR_API_KEY, 'Content-Type': 'application/json'} # Use loaded env var
    url = f"{RADARR_URL}/api/v3/movie" # Use loaded env var
    response = None # Initialize response to None
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        logger.info(f"Movie '{movie_info['title']}' added successfully to Radarr.")
        return True
    except requests.exceptions.RequestException as e:
        log_message = f"Failed to add movie '{movie_info['title']}' to Radarr."
        if response is not None:
            log_message += f" Radarr response: {response.text}"
        logger.exception(log_message)
        return False
