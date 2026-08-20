import logging
import requests
import json
from functools import wraps
from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from config import ALLOWED_USER_IDS, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

# Shared HTTP Session with Connection Pooling
http_session = requests.Session()


def is_user_allowed(user_id: int) -> bool:
    """Checks if the user is allowed to use the bot based on configured allowed IDs."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def restricted(func):
    """Decorator to restrict handler execution to authorized Telegram users only."""
    @wraps(func)
    async def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user = update.effective_user
        if not user or not is_user_allowed(user.id):
            logger.warning(f"Unauthorized access attempt by user {user.id if user else 'Unknown'}")
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Sorry, you are not authorized to use this bot.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Unauthorized.", show_alert=True)
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapped


def make_api_request(base_url: str, api_key: str, endpoint: str, params: dict | None = None) -> list | dict | None:
    """Makes a generic API GET request using the shared session."""
    headers = {'X-Api-Key': api_key}
    url = f"{base_url}/api/v3/{endpoint}"
    logger.info(f"Attempting API request to: {url} with params: {params}")
    try:
        response = http_session.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        logger.debug(f"API request successful for {url}. Status: {response.status_code}")
        return response.json()
    except requests.exceptions.RequestException:
        logger.exception(f"API request failed for {url}.")
        return None
    except json.JSONDecodeError:
        logger.exception(f"Failed to decode JSON response from {url}")
        return None
