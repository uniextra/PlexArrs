import logging
import requests
import json
import os # Import os module
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler
# import config # Remove config import

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.WARNING
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

# Load and convert integer variables with defaults or error handling
try:
    SONARR_ROOT_FOLDER_ID = int(os.getenv('SONARR_ROOT_FOLDER_ID', '1')) # Default to 1 if not set
    SONARR_QUALITY_PROFILE_ID = int(os.getenv('SONARR_QUALITY_PROFILE_ID', '1')) # Default to 1 if not set
    RADARR_ROOT_FOLDER_ID = int(os.getenv('RADARR_ROOT_FOLDER_ID', '1')) # Default to 1 if not set
    RADARR_QUALITY_PROFILE_ID = int(os.getenv('RADARR_QUALITY_PROFILE_ID', '1')) # Default to 1 if not set
except ValueError as e:
    logger.error(f"Error converting numeric environment variable to int: {e}. Please check values.")
    # Decide how to handle: exit, use default, raise error? Let's log and potentially fail later.
    # For now, we'll let the defaults above stand, but a production app might exit here.
    pass # Or raise SystemExit("Invalid numeric environment variable.")

# Load allowed user IDs (comma-separated string)
allowed_user_ids_str = os.getenv('ALLOWED_USER_IDS', '') # Default to empty string
ALLOWED_USER_IDS = []
if allowed_user_ids_str:
    try:
        ALLOWED_USER_IDS = [int(user_id.strip()) for user_id in allowed_user_ids_str.split(',') if user_id.strip()]
    except ValueError:
        logger.error(f"Invalid format for ALLOWED_USER_IDS environment variable. Should be comma-separated integers. Value: '{allowed_user_ids_str}'")
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
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from {url}: {e}")
        return None

async def _restart_conversation(update: Update, context: CallbackContext, message: str) -> int:
    """Cleans up user data and sends the initial prompt, restarting the conversation."""
    logger.info(f"Restarting conversation: {message}")
    # Clean up user data defensively
    for key in ['search_type', 'search_results', 'chosen_item']:
        context.user_data.pop(key, None)

    keyboard = [
        [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        [InlineKeyboardButton("📺 Series", callback_data='series')],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel')], # This cancel button will now restart
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Determine how to send the message (edit or new)
    query = update.callback_query
    if query:
        try:
            # Try editing the existing message first
            await query.edit_message_text(f"{message}\nWhat would you like to search for?", reply_markup=reply_markup)
        except Exception as e:
            logger.warning(f"Could not edit message on restart: {e}. Sending new message.")
            # If editing fails (e.g., message too old), send a new message via the original message context
            try:
                await query.message.reply_text(f"{message}\nWhat would you like to search for?", reply_markup=reply_markup)
            except Exception as e2:
                 logger.error(f"Could not send new message on restart either: {e2}")

    elif update.message:
        await update.message.reply_text(f"{message}\nWhat would you like to search for?", reply_markup=reply_markup)
    else:
        # Fallback if no context is available (should be rare)
        logger.error("Could not send restart message: No query or message context.")

    return SEARCH_TYPE


async def _display_search_results(update: Update, context: CallbackContext) -> int:
    """Displays the search results stored in context.user_data."""
    results = context.user_data.get('search_results', [])
    message_context = update.callback_query.message if update.callback_query else update.message

    if not results:
        # This case should ideally be handled before calling this function,
        # but as a fallback, restart if results are somehow empty.
        logger.warning("_display_search_results called with empty results.")
        return await _restart_conversation(update, context, "No results found to display.")

    keyboard = []
    for i, item in enumerate(results[:10]): # Limit to 10 results
        title = item.get('title', 'N/A')
        year = item.get('year', '')
        button_text = f"{title} ({year})" if year else title
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f'choose_{i}')])

    keyboard.append([InlineKeyboardButton("❌ Cancel Search", callback_data='cancel')]) # Use the restart cancel
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message_context.reply_text("Here's what I found:", reply_markup=reply_markup)
    return CHOOSE_ITEM


# --- Sonarr Functions ---

def search_sonarr(query: str) -> list:
    """Searches Sonarr for a series."""
    if not SONARR_URL or not SONARR_API_KEY:
        logger.error("Sonarr URL or API Key not configured in environment variables.")
        return []
    return make_api_request(SONARR_URL, SONARR_API_KEY, 'series/lookup', {'term': query}) or []

def add_series_to_sonarr(series_info: dict) -> bool:
    """Adds a series to Sonarr."""
    if not SONARR_URL or not SONARR_API_KEY:
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
            logger.error(f"Sonarr Root Folder ID {SONARR_ROOT_FOLDER_ID} not found in Sonarr's API response.") # Use loaded env var
            return False
    else:
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
        if response is not None:
            logger.error(f"Sonarr response: {response.text}")
        return False


# --- Radarr Functions ---

def search_radarr(query: str) -> list:
    """Searches Radarr for a movie."""
    if not RADARR_URL or not RADARR_API_KEY:
        logger.error("Radarr URL or API Key not configured in environment variables.")
        return []
    return make_api_request(RADARR_URL, RADARR_API_KEY, 'movie/lookup', {'term': query}) or []

def add_movie_to_radarr(movie_info: dict) -> bool:
    """Adds a movie to Radarr."""
    if not RADARR_URL or not RADARR_API_KEY:
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
            logger.error(f"Radarr Root Folder ID {RADARR_ROOT_FOLDER_ID} not found in Radarr's API response.") # Use loaded env var
            return False
    else:
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
        if response is not None:
            logger.error(f"Radarr response: {response.text}")
        return False

# --- Telegram Bot Handlers ---

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
        # The original code resent buttons here, but _restart_conversation does that now.
        # keyboard = [
        #    [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        #    [InlineKeyboardButton("📺 Series", callback_data='series')],
        #    [InlineKeyboardButton("❌ Cancel", callback_data='cancel')],
        # ]
        # reply_markup = InlineKeyboardMarkup(keyboard)
        # await update.message.reply_text(
        #     "What would you like to search for?",
        #     reply_markup=reply_markup
        # )
        # Go back to the state where the user chooses movie/series
        # return SEARCH_TYPE # Now handled by _restart_conversation

    context.user_data['search_results'] = results
    keyboard = []
    for i, item in enumerate(results[:10]): # Limit to 10 results
        title = item.get('title', 'N/A')
        year = item.get('year', '')
        button_text = f"{title} ({year})" if year else title
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f'choose_{i}')])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Here's what I found:", reply_markup=reply_markup)
    return CHOOSE_ITEM

async def item_chosen(update: Update, context: CallbackContext) -> int:
    """Handles the user's choice from the search results and asks for confirmation."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == 'cancel':
        # Use the restart helper
        return await _restart_conversation(update, context, "Selection cancelled.")

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
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_add')],
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
                await query.delete_message()
            except Exception as e:
                logger.warning(f"Failed to send photo {poster_url}: {e}. Sending text instead.")
                await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='HTML')

        return CONFIRM_ADD

    except (ValueError, IndexError) as e:
        logger.error(f"Error processing item choice: {e}")
        # Use the restart helper on error
        return await _restart_conversation(update, context, "Sorry, there was an error processing your choice.")


async def add_item_confirmed(update: Update, context: CallbackContext) -> int:
    """Adds the chosen item to Sonarr/Radarr."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    update_message = update.effective_message # Use effective_message for replies

    if callback_data == 'cancel_add':
        # --- Start: Refactored Cancel Confirmation Logic ---
        try:
            # Try deleting the message with the photo/confirmation
            await query.delete_message()
            if update_message: # Check if message context exists
                 await update_message.reply_text("Okay, I won't add it. Operation cancelled.")
        except Exception as e:
            logger.warning(f"Could not delete message on cancel: {e}. Trying edit instead.")
            try:
                 # Edit using query context as fallback if delete failed
                 await query.edit_message_text("Okay, I won't add it. Operation cancelled.")
            except Exception as e2:
                 logger.error(f"Could not edit message on cancel either: {e2}")
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
        # --- End: Refactored Cancel Confirmation Logic ---

    if callback_data != 'confirm_add':
        # Use the restart helper for invalid confirmation
        return await _restart_conversation(update, context, "Invalid confirmation.")

    # --- Start: Refactored Add Confirmation Logic ---
    chosen_item = context.user_data.get('chosen_item')
    search_type = context.user_data.get('search_type')
    update_message = update.effective_message # Use effective_message for replies

    if not chosen_item or not search_type or not update_message:
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
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel')],
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
    # We don't change the state here, let the user retry or cancel.

async def unknown_state_handler(update: Update, context: CallbackContext) -> int:
    """Handles any unexpected message or callback query in any state."""
    logger.warning(f"Unhandled update in state {context.user_data.get('_state')}: {update}")
    return await _restart_conversation(update, context, "Something went wrong or I received unexpected input. Let's start over.")


def main() -> None:
    """Start the bot."""
    # --- Environment Variable Check ---
    required_vars = ['TELEGRAM_BOT_TOKEN', 'SONARR_URL', 'SONARR_API_KEY', 'RADARR_URL', 'RADARR_API_KEY']
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
            CHOOSE_ITEM: [CallbackQueryHandler(item_chosen, pattern='^choose_\\d+$|^cancel$')],
            CONFIRM_ADD: [CallbackQueryHandler(add_item_confirmed, pattern='^confirm_add$|^cancel_add$')],
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

    # Run the bot until the user presses Ctrl-C
    logger.info("Starting bot...")
    application.run_polling()
    logger.info("Bot stopped.")

if __name__ == '__main__':
    # The check for placeholder tokens is removed as config.py is no longer used.
    # The check for missing environment variables is now inside main().
    main()
