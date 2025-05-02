import logging
import requests
import json
import sys, os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler
import re
import qbittorrentapi # Use the new library
#import config

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d - %(funcName)s()] %(message)s', level=logging.WARNING
)
logger = logging.getLogger(__name__)

# Conversation states
SEARCH_TYPE, SEARCH_QUERY, CHOOSE_ITEM, CONFIRM_ADD = range(4)

# --- Environment Variable Loading & Validation ---

# Load configuration from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SONARR_URL = os.getenv('SONARR_URL')
SONARR_API_KEY = os.getenv('SONARR_API_KEY')
RADARR_URL = os.getenv('RADARR_URL')
RADARR_API_KEY = os.getenv('RADARR_API_KEY')
QBITTORRENT_URL = os.getenv('QBITTORRENT_URL')
QBITTORRENT_USERNAME = os.getenv('QBITTORRENT_USERNAME')
QBITTORRENT_PASSWORD = os.getenv('QBITTORRENT_PASSWORD')


# Load and convert integer variables with defaults or error handling
try:
    SONARR_ROOT_FOLDER_ID = int(os.getenv('SONARR_ROOT_FOLDER_ID', '1')) # Default to 1 if not set
    SONARR_QUALITY_PROFILE_ID = int(os.getenv('SONARR_QUALITY_PROFILE_ID', '1')) # Default to 1 if not set
    RADARR_ROOT_FOLDER_ID = int(os.getenv('RADARR_ROOT_FOLDER_ID', '1')) # Default to 1 if not set
    RADARR_QUALITY_PROFILE_ID = int(os.getenv('RADARR_QUALITY_PROFILE_ID', '1')) # Default to 1 if not set
except ValueError as e:
    logger.error(f"Error converting numeric environment variable to int: {e}. Please check values.")
    exc_type, exc_obj, exc_tb = sys.exc_info()
    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
    logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
    # Decide how to handle: exit, use default, raise error? Let's log and potentially fail later.
    # For now, we'll let the defaults above stand, but a production app might exit here.
    pass # Or raise SystemExit("Invalid numeric environment variable.")

# Load allowed user IDs (comma-separated string)
allowed_user_ids_str = os.getenv('ALLOWED_USER_IDS', '') # Default to empty string
ALLOWED_USER_IDS = []
if allowed_user_ids_str:
    try:
        ALLOWED_USER_IDS = [int(user_id.strip()) for user_id in allowed_user_ids_str.split(',') if user_id.strip()]
    except ValueError as e: # Added 'as e' to capture the exception for logging
        logger.error(f"Invalid format for ALLOWED_USER_IDS environment variable. Should be comma-separated integers. Value: '{allowed_user_ids_str}'")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        # Decide how to handle: ignore, allow all, exit? Let's log and proceed with an empty list (no restrictions).
        ALLOWED_USER_IDS = [] # Reset to empty on error

# --- Helper Functions ---

def is_user_allowed(user_id: int) -> bool:
    """Checks if the user is allowed to use the bot based on environment variable."""
    if not ALLOWED_USER_IDS: # Check the loaded list
        return True  # Allow all users if the list is empty or not set correctly
    return user_id in ALLOWED_USER_IDS

def make_api_request(base_url: str, api_key: str, endpoint: str, params: dict = None) -> dict | None:
    """Makes a generic API request."""
    headers = {'X-Api-Key': api_key}
    url = f"{base_url}/api/v3/{endpoint}"
    # Log the full URL being requested, including parameters
    full_url = url
    if params:
        # Manually construct the query string for logging, ensuring proper encoding
        query_string = '&'.join([f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()])
        full_url += f"?{query_string}"
    logger.info(f"Attempting API request to: {full_url}") # Log the URL
    try:
        # Use the original 'params' dict for the actual request
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()  # Raise an exception for bad status codes
        logger.debug(f"API request successful for {url}. Status: {response.status_code}")
        return response.json()
    except requests.exceptions.RequestException as e:
        # Log more details on request failure
        error_details = f"API request failed for {url}. Error: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_details += f" Status Code: {e.response.status_code}. Response: {e.response.text}"
        logger.error(error_details)
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from {url}: {e}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        return None

async def _restart_conversation(update: Update, context: CallbackContext, message: str) -> int:
    """Cleans up user data and sends the initial prompt, restarting the conversation."""
    logger.info(f"Restarting conversation: {message}")
    
    # Clean up user data defensively
    for key in ['search_type', 'search_results', 'chosen_item']:
        context.user_data.pop(key, None)

    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Operation cancelled.")
    else:
        await update.message.reply_text("Operation cancelled.")

    await context.bot.send_message(chat_id=update.effective_chat.id,text="Envia el comando cancel",reply_markup=reply_markup)

    return ConversationHandler.END # Return the correct state to handle button clicks

def escape_markdown_v2(text: str) -> str:
    escape_chars = r'_*\[\]()~`>#+\-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# --- Sonarr Functions ---

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
        logger.error(f"Failed to add series '{series_info['title']}' to Sonarr: {e}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        if response is not None:
            # Cannot get traceback here easily as no exception is caught
            logger.error(f"Sonarr response: {response.text}")
        return False


# --- Radarr Functions ---

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
        logger.error(f"Failed to add movie '{movie_info['title']}' to Radarr: {e}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        if response is not None:
            # Cannot get traceback here easily as no exception is caught
            logger.error(f"Radarr response: {response.text}")
        return False

# --- qBittorrent Functions ---

def get_qbittorrent_downloads() -> tuple[str | None, str | None]:
    """Connects to qBittorrent using qbittorrent-api and fetches the list of active downloads."""
    if not QBITTORRENT_URL:
        # Cannot get traceback here easily as no exception is caught
        logger.error("QBITTORRENT_URL not configured.")
        return None, "qBittorrent URL not configured."

    # Initialize client
    client = qbittorrentapi.Client(
        host=QBITTORRENT_URL,
        username=QBITTORRENT_USERNAME,
        password=QBITTORRENT_PASSWORD,
        REQUESTS_ARGS={'timeout': (10, 20)} # connect timeout, read timeout
    )

    try:
        # Log in
        client.auth_log_in()
        logger.info(f"Successfully logged in to qBittorrent at {QBITTORRENT_URL}")

        # Get torrents info
        # Filter can be added here, e.g., filter='downloading' or 'active'
        torrents = client.torrents_info() # Gets all torrents by default

        if not torrents:
            return "No active downloads found\.", None

        message_lines = ["*Current Downloads:*\n"]
        bar_len = 10  # Longitud visual de la barra

        for torrent in torrents:
            name = torrent.name[:26]  # Truncate to 26 characters
            progress = torrent.progress  # 0.0 to 1.0
            percent = int(progress * 100)
            size_gb = round(torrent.size / (1024 ** 3), 2)

            filled_len = int(progress * bar_len)
            empty_len = bar_len - filled_len
            bar = '█' * filled_len + '░' * empty_len

            line = f"{name} [{bar}] {percent}% - {size_gb} GB"
            line = escape_markdown_v2(line)
            message_lines.append(line)

        return "\n".join(message_lines), None

    except qbittorrentapi.LoginFailed as e:
        logger.error(f"qBittorrent login failed for user '{QBITTORRENT_USERNAME}'. Check credentials. Error: {e}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        return None, "qBittorrent login failed. Check credentials."
    except qbittorrentapi.APIConnectionError as e:
        logger.error(f"Could not connect to qBittorrent at {QBITTORRENT_URL}: {e}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        return None, f"Could not connect to qBittorrent: {e}"
    except qbittorrentapi.exceptions.NotFound404Error as e:
         logger.error(f"qBittorrent API endpoint not found (possibly wrong URL or API version mismatch?): {e}")
         exc_type, exc_obj, exc_tb = sys.exc_info()
         fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
         logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
         return None, "qBittorrent API endpoint not found. Check URL/version."
    except Exception as e:
        # Catching potential requests exceptions as well if timeout occurs during API calls
        if isinstance(e, requests.exceptions.RequestException):
             logger.error(f"Network error communicating with qBittorrent at {QBITTORRENT_URL}: {e}")
             exc_type, exc_obj, exc_tb = sys.exc_info()
             fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
             logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
             return None, f"Network error connecting to qBittorrent: {e}"
        else:
             # Changed from logger.exception to logger.error + manual traceback
             logger.error(f"An unexpected error occurred while fetching qBittorrent downloads: {e}")
             exc_type, exc_obj, exc_tb = sys.exc_info()
             fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
             logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
             return None, f"An unexpected error occurred: {e}"
    finally:
        # Logout (optional, client might handle session closure)
        try:
            if client.is_logged_in:
                client.auth_log_out()
                logger.info("Logged out from qBittorrent.")
        except Exception as e:
            logger.warning(f"Failed to log out from qBittorrent: {e}")


# --- Telegram Bot Handlers ---

async def downloads_command(update: Update, context: CallbackContext) -> None:
    """Handles the /downloads command."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    await update.message.reply_text("Fetching download status from qBittorrent...")

    message, error = get_qbittorrent_downloads()
    
    print('--------------------------',message)

    if error:
        await update.message.reply_text(f"Error: {error}")
    elif message:
        # Split message if too long for Telegram
        max_len = 4096
        if len(message) == 0:
            await update.message.reply_text('No active Downloads', parse_mode='MarkdownV2')
        if len(message) > max_len:
             for i in range(0, len(message), max_len):
                  await update.message.reply_text(message[i:i+max_len], parse_mode='MarkdownV2')
        else:
            try:
                await update.message.reply_text(message, parse_mode='MarkdownV2')
            except Exception as e:
                logger.error(f"Failed to send message: {e} {message}")
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
                await update.message.reply_text("Failed to send download status. Check logs for details.")
    else:
        # This case should ideally be handled by get_qbittorrent_downloads returning a specific message
        await update.message.reply_text("Could not retrieve download status.")


async def start(update: Update, context: CallbackContext) -> int:
    """Sends a welcome message and asks what to search for."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return ConversationHandler.END

    # Initial prompt without the Cancel button
    keyboard = [
        [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        [InlineKeyboardButton("📺 Series", callback_data='series')],
        # [InlineKeyboardButton("❌ Cancel", callback_data='cancel')], # Removed initial cancel button
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Hi {user.mention_html()}! What would you like to search for?",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    return SEARCH_TYPE

async def help_command(update: Update, context: CallbackContext) -> None:
    """Displays help information."""
    await update.message.reply_text(
        "Use /start to begin searching for movies or series.\n"
        "I will ask you for the title, show you the results, and you can choose one to add to Radarr or Sonarr."
    )

async def search_type_chosen(update: Update, context: CallbackContext) -> int:
    """Stores the chosen search type (movie/series) and asks for the search query."""
    query = update.callback_query
    await query.answer()
    search_type = query.data

    if search_type == 'cancel':
        # Use the restart helper
        return await _restart_conversation(update, context, "Search cancelled.")

    context.user_data['search_type'] = search_type
    await query.edit_message_text(f"Okay, searching for a {search_type}. Please enter the title:")
    return SEARCH_QUERY

#######################
async def _render_search_results(update: Update, context: CallbackContext, results: list) -> int:
    try:
        """Displays search results with inline buttons."""
        context.user_data['search_results'] = results

        keyboard = []
        for i, item in enumerate(results[:10]):  # Limit to 10 results
            title = item.get('title', 'N/A')
            year = item.get('year', '')
            button_text = f"{title} ({year})" if year else title
            
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f'choose_{i}')])

        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel')])
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.message.reply_text(
                "Here's what I found:", reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "Here's what I found:", reply_markup=reply_markup
            )


        return CHOOSE_ITEM
    except (ValueError, IndexError) as e:
        # This block already had the manual traceback logging, ensuring it remains
        logger.error(f"Error _render_search_results: {e}")
        # Use the restart helper on error
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error("Error: {} {} {} {}".format(str(e),exc_type, fname, exc_tb.tb_lineno))
##########################



async def search_query_received(update: Update, context: CallbackContext) -> int:
    """Performs the search based on the type and query, then displays results."""
    query = update.message.text
    search_type = context.user_data.get('search_type')
    user_id = update.effective_user.id

    if not is_user_allowed(user_id): # Re-check authorization
        await update.message.reply_text("Sorry, you are not authorized.")
        return ConversationHandler.END

    await update.message.reply_text(f"Searching for {search_type}: '{query}'...")

    results = []
    if search_type == 'movie':
        results = search_radarr(query)
    elif search_type == 'series':
        results = search_sonarr(query)

    # Handle API errors explicitly if make_api_request returned None
    if results is None: # Check for None which indicates an API error
        # Use the restart helper
        return await _restart_conversation(update, context, "Sorry, there was an error communicating with the service.")

    # Handle case where API worked but found no results
    if not results:
        await update.message.reply_text("Sorry, I couldn't find anything matching that title.")
        # Use the restart helper to ask again
        return await _restart_conversation(update, context, "Let's try again.")


    context.user_data['search_results'] = results
    keyboard = []
    for i, item in enumerate(results[:10]): # Limit to 10 results
        title = item.get('title', 'N/A')
        year = item.get('year', '')
        button_text = f"{title} ({year})" if year else title
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f'choose_{i}')])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    # await update.message.reply_text("Here's what I found:", reply_markup=reply_markup)
    # return CHOOSE_ITEM
    return await _render_search_results(update, context, results)


async def item_chosen(update: Update, context: CallbackContext) -> int:
    """Handles the user's choice from the search results and asks for confirmation."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    # Handle 'backtosearch' from the results list explicitly
    # if callback_data == 'back_to_results':
    #     return await search_query_received(update, context)
    ##########################
    if callback_data == 'back_to_results':
        results = context.user_data.get('search_results')
        if results:
            return await _render_search_results(update, context, results)
        else:
            return await _restart_conversation(update, context, "No results to go back to.")
    ##########################

    # Keep handling 'cancel' just in case, though fallbacks might catch it too
    if callback_data == 'cancel':
        # Use the restart helper
        return await _restart_conversation(update, context, "Operation cancelled.")


    if not callback_data.startswith('choose_'):
        # Use the restart helper for invalid selection
        return await _restart_conversation(update, context, "Invalid selection.")

    try:
        choice_index = int(callback_data.split('_')[1])
        results = context.user_data.get('search_results', [])
        if not 0 <= choice_index < len(results):
            raise ValueError("Index out of bounds")

        chosen_item = results[choice_index]
        context.user_data['chosen_item'] = chosen_item

        title = chosen_item.get('title', 'N/A')
        year = chosen_item.get('year', '')
        overview = chosen_item.get('overview', 'No description available.')
        poster_url = None
        # Find poster URL (structure differs slightly between Sonarr/Radarr lookup)
        images = chosen_item.get('images', [])
        if images:
            poster_info = next((img for img in images if img.get('coverType') == 'poster'), None)
            if poster_info:
                poster_url = poster_info.get('remoteUrl') or poster_info.get('url') # Radarr uses remoteUrl, Sonarr uses url

        message_text = f"<b>{title} ({year})</b>\n\n{overview}"

        keyboard = [
            [InlineKeyboardButton("✅ Add this", callback_data='confirm_add')],
            # Add the "Back" button
            [InlineKeyboardButton("⬅️ Back to search results", callback_data='back_to_results')],
            [InlineKeyboardButton("❌ Cancel Search", callback_data='cancel_add')], # This cancel now restarts the whole search
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if poster_url:
            try:
                await query.message.reply_photo(
                    photo=poster_url,
                    caption=message_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                # Delete the previous message with the list
                #await query.delete_message()
            except Exception as e:
                logger.warning(f"Failed to send photo {poster_url}: {e}. Sending text instead.")
                await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='HTML')

        return CONFIRM_ADD

    except (ValueError, IndexError) as e:
        # This block already had the manual traceback logging, ensuring it remains
        logger.error(f"Error processing item choice: {e}")
        # Use the restart helper on error
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error("Error: {} {} {} {}".format(str(e), exc_type, fname, exc_tb.tb_lineno)) # Corrected syntax: removed extra '}'
        return await _restart_conversation(update, context, "Sorry, there was an error processing your choice.")


async def add_item_confirmed(update: Update, context: CallbackContext) -> int:
    """Adds the chosen item to Sonarr/Radarr."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    update_message = update.effective_message # Use effective_message for replies

    # Handle "Back to search results"
    # # if callback_data == 'back_to_results':
    # #     try:
    # #         # Delete the confirmation message
    # #         await query.delete_message()
    # #         if update_message: # Check if message context exists
    # #              await update_message.reply_text("Okay, I won't add it. Operation cancelled.")
    if callback_data == 'back_to_results':
        try:
            results = context.user_data.get('search_results')
            if results:
                return await _render_search_results(update, context, results)
            else:
                return await _restart_conversation(update, context, "No results to go back to.")

        except Exception as e:
            logger.warning(f"Could not delete message on cancel: {e}. Trying edit instead.")
            # Note: The original code logged the traceback info here using logging.error,
            # even though the primary log was logger.warning. Keeping that pattern.
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logging.error("Error: {} {} {} {}".format(str(e),exc_type, fname, exc_tb.tb_lineno))
            try:
                 # Edit using query context as fallback if delete failed
                 await query.edit_message_text("Okay, I won't add it. Operation cancelled.")
            except Exception as e2:
                 logger.error(f"Could not edit message on cancel either: {e2}")
                 # Add traceback for the inner exception
                 exc_type_inner, exc_obj_inner, exc_tb_inner = sys.exc_info()
                 fname_inner = os.path.split(exc_tb_inner.tb_frame.f_code.co_filename)[1]
                 logging.error(f"Traceback Info: Type={exc_type_inner}, File={fname_inner}, Line={exc_tb_inner.tb_lineno}")
                 # Final fallback: send new message if possible
                 if update_message:
                      await update_message.reply_text("Okay, I won't add it. Operation cancelled.")

        # Clean up user data here as well for cancellation
        context.user_data.pop('search_type', None)
        context.user_data.pop('search_results', None)
        context.user_data.pop('chosen_item', None)
        # Use the restart helper after cancelling the add
        # The previous logic sent multiple messages, let's simplify with the helper
        return await _restart_conversation(update, context, "Okay, I won't add it. Operation cancelled.")

    # Handle "Cancel Search" - this will now restart the conversation
    if callback_data == 'cancel_add':
        try:
            # Delete the confirmation message
            await query.delete_message()
        except Exception as e:
            logger.warning(f"Could not delete confirmation message on cancel_add (restart): {e}")
            # Try editing as a fallback
            try:
                 await query.edit_message_text("Cancelling search...")
            except Exception as e2:
                 logger.error(f"Could not edit message on cancel_add (restart) either: {e2}")
                 exc_type, exc_obj, exc_tb = sys.exc_info()
                 fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                 logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        # Use the restart helper to go back to the very beginning
        return await _restart_conversation(update, context, "Search cancelled.")


    if callback_data != 'confirm_add':
        # Use the restart helper for any other invalid confirmation
        return await _restart_conversation(update, context, "Invalid confirmation.")

    # --- Start: Refactored Add Confirmation Logic ---
    chosen_item = context.user_data.get('chosen_item')
    search_type = context.user_data.get('search_type')
    update_message = update.effective_message # Use effective_message for replies

    if not chosen_item or not search_type or not update_message:
        # Cannot get traceback here easily as no exception is caught
        logger.error("Missing context (chosen_item, search_type, or message) in add_item_confirmed.")
        # Try to delete the original message if query exists
        if query:
            try:
                await query.delete_message()
            except Exception:
                pass # Ignore if deletion fails
        # Send error message using update_message if available
        if update_message:
            await update_message.reply_text("Something went wrong, missing context. Please start over with /start.")
        # Use the restart helper if context is missing
        return await _restart_conversation(update, context, "Something went wrong, missing context.")

    title = chosen_item.get('title', 'N/A')

    # 1. Delete the confirmation message (photo + buttons) if query exists
    if query:
        try:
            await query.delete_message()
        except Exception as e:
            logger.warning(f"Could not delete confirmation message via query: {e}")

    # 2. Send a *new* message indicating "Adding..." using effective_message
    status_message = None
    try:
        status_message = await update_message.reply_text(
            f"⏳ Adding '{title}' to {'Sonarr' if search_type == 'series' else 'Radarr'}...",
            disable_notification=True
        )
    except Exception as e:
        logger.error(f"Failed to send 'Adding...' status message: {e}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
        # Cannot proceed without status message to update
        # Use the restart helper if sending status message fails
        return await _restart_conversation(update, context, "Failed to send status message.")


    # 3. Perform the add operation
    success = False
    if search_type == 'movie':
        success = add_movie_to_radarr(chosen_item)
    elif search_type == 'series':
        success = add_series_to_sonarr(chosen_item)

    # if success:
    #     await query.edit_message_text(f"✅ Successfully added '{title}' and started search.")
    # else:
    #     await query.edit_message_text(f"❌ Failed to add '{title}'. Check logs for details.")

    # Clean up user data after processing
    context.user_data.pop('search_type', None)
    context.user_data.pop('search_results', None)
    context.user_data.pop('chosen_item', None)

    # Go back to the start after adding
    keyboard = [
        [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        [InlineKeyboardButton("📺 Series", callback_data='series')],
        #[InlineKeyboardButton("❌ Cancel", callback_data='cancel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # 4. Edit the "Adding..." status message with the result (if status_message was sent)
    if status_message:
        result_text = ""
        if success:
            result_text = f"✅ Successfully added '{title}' and started search."
        else:
            result_text = f"❌ Failed to add '{title}'. Check logs for details."
        try:
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text=result_text
            )
        except Exception as e:
            logger.error(f"Failed to edit status message: {e}. Sending new message instead.")
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logging.error(f"Traceback Info: Type={exc_type}, File={fname}, Line={exc_tb.tb_lineno}")
            # Fallback: send result as a new message if editing fails
            await update_message.reply_text(result_text)
    else:
         # If status message failed, send result as new message
         if success:
            await update_message.reply_text(f"✅ Successfully added '{title}' and started search.")
         else:
            await update_message.reply_text(f"❌ Failed to add '{title}'. Check logs for details.")


    # 5. Send the next prompt ("What would you like to search for next?")
    await update_message.reply_text(
        "What would you like to search for next?",
        reply_markup=reply_markup
    )
    return SEARCH_TYPE # Go back to the start state
    # --- End: Refactored Add Confirmation Logic ---

async def cancel_conversation(update: Update, context: CallbackContext) -> int:
    """Cancels the current conversation."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Operation cancelled.")
    else:
        await update.message.reply_text("Operation cancelled.")

    # Clean up user data
    context.user_data.pop('search_type', None)
    context.user_data.pop('search_results', None)
    context.user_data.pop('chosen_item', None)

    return ConversationHandler.END

async def cancel_conversation_and_restart(update: Update, context: CallbackContext) -> int:
    """Handles 'cancel' button presses within the conversation, restarting it."""
    return await _restart_conversation(update, context, "Operation cancelled.")

async def unknown_command(update: Update, context: CallbackContext) -> None:
    """Handles unknown commands during the conversation."""
    await update.message.reply_text("Sorry, I didn't understand that command. Use /cancel to stop or continue the current process.")
    ConversationHandler.END
    # We don't change the state here, let the user retry or cancel.

async def unknown_state_handler(update: Update, context: CallbackContext) -> int:
    """Handles any unexpected message or callback query in any state."""
    current_state = context.user_data.get('_state')
    logger.warning(f"Unhandled update in state {current_state}: {update}")
    ConversationHandler.END # Ensure conversation state is cleared

    # Determine if it was likely an old button press
    if update.callback_query and current_state is None:
        message = "It looks like you clicked a button from a previous search. That context is gone, so let's start a new search."
    else:
        message = "Something went wrong or I received unexpected input. Let's start over."

    return await _restart_conversation(update, context, message)



def main() -> None:
    """Start the bot."""
    # --- Environment Variable Check ---
    required_vars = [
        'TELEGRAM_BOT_TOKEN', 'SONARR_URL', 'SONARR_API_KEY', 'RADARR_URL', 'RADARR_API_KEY',
        'QBITTORRENT_URL' # Add QBITTORRENT_URL check
        # Username/Password are optional depending on qBittorrent setup, so not strictly required here
    ]
    missing_vars = [var for var in required_vars if not globals().get(var)]
    if missing_vars:
        logger.critical(f"Missing required environment variables: {', '.join(missing_vars)}. Exiting.")
        return # Or raise SystemExit

    # Check if numeric IDs were loaded correctly (they have defaults, but good to be explicit)
    numeric_vars_check = {
        'SONARR_ROOT_FOLDER_ID': SONARR_ROOT_FOLDER_ID,
        'SONARR_QUALITY_PROFILE_ID': SONARR_QUALITY_PROFILE_ID,
        'RADARR_ROOT_FOLDER_ID': RADARR_ROOT_FOLDER_ID,
        'RADARR_QUALITY_PROFILE_ID': RADARR_QUALITY_PROFILE_ID
    }
    for name, value in numeric_vars_check.items():
         if value is None: # Should not happen with defaults, but check anyway
              logger.critical(f"Environment variable {name} could not be loaded correctly. Exiting.")
              return # Or raise SystemExit

    logger.info(f"Allowed user IDs loaded: {ALLOWED_USER_IDS if ALLOWED_USER_IDS else 'None (all allowed)'}")


    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build() # Use loaded env var

    # Conversation handler for the search/add process
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SEARCH_TYPE: [CallbackQueryHandler(search_type_chosen)],
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_query_received)],
            CHOOSE_ITEM: [CallbackQueryHandler(item_chosen, pattern='^choose_\\d+$|^cancel$|^backtosearch$')], # Added backtosearch pattern here too
            # Add back_to_results pattern
            CONFIRM_ADD: [CallbackQueryHandler(add_item_confirmed, pattern='^confirm_add$|^cancel_add$|^back_to_results$')],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation), # Explicit /cancel command still ends the conversation
            CallbackQueryHandler(cancel_conversation_and_restart, pattern='^cancel$'), # Inline cancel buttons restart
            # Add more robust fallbacks
            MessageHandler(filters.COMMAND, unknown_command), # Handle unknown commands within the conversation
            MessageHandler(filters.ALL, unknown_state_handler), # Handle unexpected text/messages
            CallbackQueryHandler(unknown_state_handler) # Handle unexpected callbacks
            ],
        # Let's keep per_user=True for now, it's generally safer for conversation state management.
        per_user=True # Store conversation state per user
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("downloads", downloads_command)) # Add the new command handler
    application.add_handler(CallbackQueryHandler(unknown_state_handler))

    # Set bot commands for the menu button
    commands = [
        BotCommand("start", "Iniciar una nueva búsqueda"),
        BotCommand("downloads", "Ver descargas actuales"),
        BotCommand("help", "Mostrar ayuda"),
        BotCommand("cancel", "Cancelar la operación actual"),
    ]
    # Use run_sync for potentially blocking operations if needed, but set_my_commands is usually quick
    # await application.bot.set_my_commands(commands)
    # For simplicity in this context, let's assume direct call is okay or handle potential blocking if necessary
    # Using a synchronous approach within the async main function requires care.
    # A common pattern is to run it in a separate thread or use asyncio's run_in_executor.
    # However, python-telegram-bot v20+ handles this internally more gracefully.
    # Let's try the direct await first. If it causes issues, we might need adjustment.
    import asyncio
    asyncio.get_event_loop().run_until_complete(application.bot.set_my_commands(commands))
    logger.info("Bot commands set.")


    # Run the bot until the user presses Ctrl-C
    logger.info("Starting bot...")
    application.run_polling()
    logger.info("Bot stopped.")

if __name__ == '__main__':
    # The check for placeholder tokens is removed as config.py is no longer used.
    # The check for missing environment variables is now inside main().
    main()
