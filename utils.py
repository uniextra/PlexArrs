import logging
import requests
import json
import re # Ensure re is imported
# sys and os imports are not strictly needed here anymore if logger.exception is used without manual traceback parsing
from config import ALLOWED_USER_IDS # For is_user_allowed

logger = logging.getLogger(__name__)

def is_user_allowed(user_id: int) -> bool:
    """Checks if the user is allowed to use the bot based on environment variable."""
    if not ALLOWED_USER_IDS: # Check the loaded list
        return True  # Allow all users if the list is empty or not set correctly
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
    except requests.exceptions.RequestException as e:
        error_details = f"API request failed for {url}."
        if hasattr(e, 'response') and e.response is not None:
            error_details += f" Status Code: {e.response.status_code}. Response: {e.response.text}"
        logger.exception(error_details)
        return None
    except json.JSONDecodeError: # Removed 'as e' since logger.exception handles it
        logger.exception(f"Failed to decode JSON response from {url}")
        return None

def escape_markdown_v2(text: str) -> str:
    """Escapes text for Telegram MarkdownV2."""
    # The characters to escape for Telegram MarkdownV2
    escape_chars = r'_*\[\]()~`>#+\-=|{}.!'
    # Use a lambda function for the replacement to ensure
    # a literal backslash is prepended to the matched character.
    # The '\\' in the lambda becomes a single backslash string.
    return re.sub(f'([{re.escape(escape_chars)}])', lambda m: '\\' + m.group(1), text)
