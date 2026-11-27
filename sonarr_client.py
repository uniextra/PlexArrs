import logging
import requests
import json
import config
from config import (
    SONARR_ROOT_FOLDER_ID,
    SONARR_QUALITY_PROFILE_ID,
    DEFAULT_TIMEOUT,
    get_sonarr_endpoint,
)
from utils import make_api_request, get_http_session, extract_error_detail

logger = logging.getLogger(__name__)


def search_sonarr(query: str) -> list | None:
    """Searches Sonarr for a series."""
    sonarr_url, sonarr_api_key = get_sonarr_endpoint()
    if not sonarr_url or not sonarr_api_key:
        logger.error("Sonarr URL or API Key not configured.")
        return None
    result = make_api_request(sonarr_url, sonarr_api_key, 'series/lookup', {'term': query})
    if result is None or not isinstance(result, list):
        return None
    return result


def _parse_positive_int(value) -> int:
    """Safely converts an ID value to a positive int, or 0 if invalid/missing."""
    try:
        parsed = int(value)
        return parsed if parsed > 0 else 0
    except (TypeError, ValueError):
        return 0


def _first_external_lookup_term(series_info: dict) -> str | None:
    """Builds a Sonarr/HolyArrs lookup term from alternative external IDs."""
    tmdb_id = _parse_positive_int(series_info.get('tmdbId'))
    if tmdb_id:
        return f"tmdb:{tmdb_id}"
    imdb_id = str(series_info.get('imdbId') or '').strip()
    if imdb_id:
        return f"imdb:{imdb_id}"
    tvmaze_id = _parse_positive_int(series_info.get('tvMazeId'))
    if tvmaze_id:
        return f"tvmaze:{tvmaze_id}"
    return None


def _resolve_series_tvdb(sonarr_url: str, sonarr_api_key: str, series_info: dict) -> dict:
    """Resolves full series details via external ID lookup when tvdbId is missing or 0."""
    if _parse_positive_int(series_info.get('tvdbId')):
        return series_info

    term = _first_external_lookup_term(series_info)
    if not term:
        return series_info

    logger.info(f"Series '{series_info.get('title')}' has no tvdbId; resolving via lookup '{term}'.")
    lookup_results = make_api_request(sonarr_url, sonarr_api_key, 'series/lookup', {'term': term})
    if isinstance(lookup_results, list) and lookup_results:
        resolved = lookup_results[0]
        if isinstance(resolved, dict) and _parse_positive_int(resolved.get('tvdbId')):
            merged = dict(series_info)
            merged['tvdbId'] = resolved['tvdbId']
            if resolved.get('titleSlug'):
                merged['titleSlug'] = resolved['titleSlug']
            if not merged.get('seasons') and resolved.get('seasons'):
                merged['seasons'] = resolved['seasons']
            return merged
    return series_info


def _add_show_via_holyarrs_native(
    sonarr_url: str,
    sonarr_api_key: str,
    series_info: dict,
    folder_id: int | None,
) -> bool | str:
    """Fallback to HolyArrs native POST /api/v1/shows when a show has no TVDB ID."""
    ext_term = _first_external_lookup_term(series_info)
    if not ext_term:
        logger.error(f"Cannot add series '{series_info.get('title')}': no tvdbId or external ID available.")
        return "Missing TvdbId (show has no TVDB ID in metadata)"

    base_url = sonarr_url.rstrip('/')
    if base_url.endswith('/sonarr'):
        base_url = base_url[:-len('/sonarr')]
    url = f"{base_url}/api/v1/shows"
    payload = {
        "id": ext_term,
        "pick_rules_id": SONARR_QUALITY_PROFILE_ID,
        "keep_up_to_date": True,
        "seasons": "all",
        "search_on_add": True,
    }
    if folder_id is not None:
        payload["library_folder_id"] = folder_id

    headers = {'X-Api-Key': sonarr_api_key, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    session = get_http_session()
    response = None
    try:
        response = session.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        logger.info(f"Series '{series_info.get('title')}' added successfully via HolyArrs native API ({ext_term}).")
        return True
    except requests.exceptions.RequestException as e:
        if response is None:
            logger.error(f"Network error adding series '{series_info.get('title')}' via HolyArrs native API ({ext_term}): {e}")
            return False
        detail = extract_error_detail(response)
        logger.error(
            f"Failed to add series '{series_info.get('title')}' via HolyArrs native API ({ext_term}). "
            f"Response: {response.text[:300]}"
        )
        if 'already' in detail.lower():
            return 'AlreadyInLibrary'
        return detail


def add_series_to_sonarr(series_info: dict) -> bool | str:
    """Adds a series to Sonarr."""
    sonarr_url, sonarr_api_key = get_sonarr_endpoint()
    if not sonarr_url or not sonarr_api_key:
        logger.error("Sonarr URL or API Key not configured.")
        return False

    resolved_info = _resolve_series_tvdb(sonarr_url, sonarr_api_key, series_info)

    # Get the correct root folder path using the configured ID or fallback to the first available
    root_folders = make_api_request(sonarr_url, sonarr_api_key, 'rootfolder')
    selected_folder_id = None
    if isinstance(root_folders, list) and root_folders:
        target_rf = next((rf for rf in root_folders if rf.get('id') == SONARR_ROOT_FOLDER_ID), None)
        if target_rf:
            root_folder_path = target_rf.get('path')
            selected_folder_id = target_rf.get('id')
        else:
            fallback = root_folders[0].get('path')
            selected_folder_id = root_folders[0].get('id')
            available = [f"ID {rf.get('id')}: {rf.get('path')}" for rf in root_folders]
            logger.warning(
                f"Configured Sonarr Root Folder ID {SONARR_ROOT_FOLDER_ID} not found. "
                f"Available root folders: {available}. Falling back to: {fallback}"
            )
            root_folder_path = fallback
    else:
        logger.error("Could not retrieve Sonarr root folders via API.")
        return False

    tvdb_id = _parse_positive_int(resolved_info.get('tvdbId'))
    if not tvdb_id:
        if config.active_media_stack.get("mode") == "holyarrs":
            return _add_show_via_holyarrs_native(sonarr_url, sonarr_api_key, resolved_info, selected_folder_id)
        logger.error(f"Cannot add series '{resolved_info.get('title')}' to Sonarr: missing valid tvdbId.")
        return "Missing TvdbId (show has no TVDB ID in metadata)"

    payload = {
        "title": resolved_info.get('title'),
        "tvdbId": tvdb_id,
        "titleSlug": resolved_info.get('titleSlug', ''),
        "qualityProfileId": SONARR_QUALITY_PROFILE_ID,
        "rootFolderPath": root_folder_path,
        "seasons": resolved_info.get('seasons', []),
        "monitored": True,
        "addOptions": {
            "monitor": "all",
            "searchForMissingEpisodes": True
        }
    }

    headers = {'X-Api-Key': sonarr_api_key, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    clean_base = sonarr_url.rstrip('/')
    url = f"{clean_base}/api/v3/series"
    response = None
    session = get_http_session()
    try:
        response = session.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        logger.info(f"Series '{resolved_info.get('title')}' added successfully to Sonarr.")
        return True
    except requests.exceptions.RequestException as e:
        if response is None:
            logger.error(f"Network error adding series '{resolved_info.get('title')}' to Sonarr: {e}")
            return False
        log_message = f"Failed to add series '{resolved_info.get('title')}' to Sonarr. Sonarr response: {response.text[:300]}"
        error_code = extract_error_detail(response)
        logger.error(log_message)
        return error_code


def unmonitor_series(series_id: int) -> bool:
    """Unmonitors a series in Sonarr."""
    sonarr_url, sonarr_api_key = get_sonarr_endpoint()
    if not sonarr_url or not sonarr_api_key:
        logger.error("Sonarr URL or API Key not configured.")
        return False

    headers = {'X-Api-Key': sonarr_api_key, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    clean_base = sonarr_url.rstrip('/')
    url = f"{clean_base}/api/v3/series/editor"
    payload = {
        "seriesIds": [int(series_id)],
        "monitored": False
    }
    session = get_http_session()
    try:
        response = session.put(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and len(data) == 0:
            logger.info(f"Series ID {series_id} was not found in Sonarr (empty response list).")
            return False
        logger.info(f"Series ID {series_id} successfully unmonitored in Sonarr.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to unmonitor series ID {series_id} in Sonarr: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error unmonitoring series ID {series_id} in Sonarr: {e}")
        return False
