import logging
import requests
import json
import threading
from functools import wraps
from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from config import ALLOWED_USER_IDS, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

# Thread-local storage for thread-safe requests.Session instances
_thread_local = threading.local()


def get_http_session() -> requests.Session:
    """Returns a thread-local requests.Session instance."""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
    return _thread_local.session


def is_user_allowed(user_id: int) -> bool:
    """Checks if the user is allowed to use the bot based on configured allowed IDs.
    
    Adheres to Fail-Closed security: if ALLOWED_USER_IDS is not configured, access is denied.
    """
    if not ALLOWED_USER_IDS:
        return False
    return user_id in ALLOWED_USER_IDS


def restricted(func):
    """Decorator to restrict handler execution to authorized Telegram users only."""
    @wraps(func)
    async def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user = update.effective_user
        if not user or not is_user_allowed(user.id):
            logger.warning(f"Unauthorized access attempt by user {user.id if user else 'Unknown'}")
            if update.callback_query:
                try:
                    await update.callback_query.answer("⛔ Unauthorized.", show_alert=True)
                except Exception as e:
                    logger.debug(f"Could not answer unauthorized callback query: {e}")
            elif update.effective_message:
                await update.effective_message.reply_text("⛔ Sorry, you are not authorized to use this bot.")
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapped


def make_api_request(base_url: str, api_key: str, endpoint: str, params: dict | None = None) -> list | dict | None:
    """Makes a generic API GET request using the thread-local session."""
    headers = {'X-Api-Key': api_key, 'Accept': 'application/json'}
    clean_base = base_url.rstrip('/')
    clean_endpoint = endpoint.lstrip('/')
    url = f"{clean_base}/api/v3/{clean_endpoint}"
    logger.info(f"Attempting API request to: {url} with params: {params}")
    session = get_http_session()
    try:
        response = session.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        logger.debug(f"API request successful for {url}. Status: {response.status_code}")
        return response.json()
    except requests.exceptions.RequestException:
        logger.exception(f"API request failed for {url}.")
        return None
    except json.JSONDecodeError:
        logger.exception(f"Failed to decode JSON response from {url}")
        return None
