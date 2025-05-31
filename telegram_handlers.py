import logging
# From telegram library
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler
# From our modules
from utils import is_user_allowed
from sonarr_client import search_sonarr, add_series_to_sonarr
from radarr_client import search_radarr, add_movie_to_radarr
from qb_client import get_qbittorrent_downloads
# Other standard libraries if needed by handlers
import requests # For vpn check
import json # For vpn check
import sys, os # For any remaining manual traceback (should be minimal)
import html # Added for HTML escaping

logger = logging.getLogger(__name__)

# Load environment variables directly
gluetunCheck = os.environ.get('gluetunCheck', 'False') # Default to 'False' if not set
gluetunUser = os.environ.get('GLUETUN_USER')
gluetunPass = os.environ.get('GLUETUN_PASS')

# Allowed User IDs - handle as a list of integers
allowed_users_str = os.environ.get('ALLOWED_USER_IDS')
ALLOWED_USER_IDS = [int(user_id.strip()) for user_id in allowed_users_str.split(',') if user_id.strip()] if allowed_users_str else None

# Conversation states (assuming these were imported from config)
SEARCH_TYPE, SEARCH_QUERY, CHOOSE_ITEM, CONFIRM_ADD = range(4)


# Helper function (originally in main.py, now here as it's closely tied to handlers)
async def _restart_conversation(update: Update, context: CallbackContext) -> int:
    """Cleans up user data and sends the initial prompt, restarting the conversation and returning to type selection."""
    logger.info("Restarting conversation and returning to type selection.")

    # Clean up user data defensively
    for key in ['search_type', 'search_results', 'chosen_item']:
        context.user_data.pop(key, None)

    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        [InlineKeyboardButton("📺 Series", callback_data='series')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = f"Hi {user.mention_html()}! What would you like to search for?"

    query = update.callback_query
    if query:
        await query.answer()
        try:
            await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode='HTML')
        except Exception:
            # If editing fails (e.g., message too old, or not found), send a new message.
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        # If no query, it's likely a message handler context (e.g. /cancel command)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup, parse_mode='HTML')

    return SEARCH_TYPE

async def check_vpn_ip_job(context: CallbackContext) -> None:
    """Checks the public IP and sends a Telegram alert if the country is not Netherlands."""
    logger.info("Checking public IP (scheduled job)...")
    # Assuming gluetunUser and gluetunPass are loaded from config
    if not gluetunUser or not gluetunPass:
        logger.warning("Gluetun credentials not set. VPN check skipped.")
        return

    url = "http://192.168.1.137:8111/v1/publicip/ip"  #Gluetun
    
    try:
        response = requests.get(url, auth=(gluetunUser, gluetunPass), timeout=10)
        response.raise_for_status() # Raise an exception for bad status codes

        ip_info = response.json()
        logger.debug(f"IP Info response: {ip_info}")

        if "country" in ip_info and ip_info["country"] == "Netherlands":
            logger.info("VPN IP is in Netherlands. All good.")
        else:
            logger.warning(f"VPN IP is NOT in Netherlands. Current country: {ip_info.get('country', 'N/A')}. Sending alert.")
            if ALLOWED_USER_IDS:
                await context.bot.send_message(chat_id=ALLOWED_USER_IDS[0], text="🚨 Alerta: La VPN parece estar caída o no está en Países Bajos.")
            else:
                logger.warning("No allowed user IDs configured to send VPN alert.")

    except requests.exceptions.RequestException:
        logger.exception("Error checking public IP (scheduled job)")
        if ALLOWED_USER_IDS:
            await context.bot.send_message(chat_id=ALLOWED_USER_IDS[0], text="🚨 Error al verificar la VPN (programado): Falló la conexión.")
        else:
            logger.warning("No allowed user IDs configured to send VPN error alert.")
    except json.JSONDecodeError:
        logger.exception("Failed to decode JSON from IP check response (scheduled job)")
        if ALLOWED_USER_IDS:
            await context.bot.send_message(chat_id=ALLOWED_USER_IDS[0], text="🚨 Error al procesar la respuesta de la VPN (programado): Respuesta inválida.")
        else:
            logger.warning("No allowed user IDs configured to send VPN JSON error alert.")
    except Exception:
        logger.exception("An unexpected error occurred during VPN check (scheduled job)")
        if ALLOWED_USER_IDS:
            await context.bot.send_message(chat_id=ALLOWED_USER_IDS[0], text="🚨 Error inesperado al verificar la VPN (programado).")
        else:
            logger.warning("No allowed user IDs configured to send unexpected VPN error alert.")

async def vpnstatus_command(update: Update, context: CallbackContext) -> None:
    """Checks the public IP and sends a Telegram alert if the country is not Netherlands."""
    logger.info("Checking public IP (command)...")
    if not gluetunUser or not gluetunPass:
        await update.message.reply_text("Credenciales de Gluetun no configuradas.")
        return

    url = "http://192.168.1.137:8111/v1/publicip/ip"  #Gluetun
    
    try:
        response = requests.get(url, auth=(gluetunUser, gluetunPass), timeout=10)
        response.raise_for_status() 

        ip_info = response.json()
        logger.debug(f"IP Info response: {ip_info}")

        if "country" in ip_info and ip_info["country"] == "Netherlands":
            await update.message.reply_text("VPN IP is in Netherlands. All good.")

            # Removed check and reset logic as requested.

        else:
            await update.message.reply_text(f"🚨 Alerta: La VPN parece estar caída o no está en Países Bajos. Current country: {ip_info.get('country', 'N/A')}.")


        



    except requests.exceptions.RequestException:
        logger.exception("Error checking public IP (command)")
        await update.message.reply_text("🚨 Error al verificar la VPN: Falló la conexión.")
    except json.JSONDecodeError:
        logger.exception("Failed to decode JSON from IP check response (command)")
        await update.message.reply_text("🚨 Error al procesar la respuesta de la VPN: Respuesta inválida.")
    except Exception:
        logger.exception("An unexpected error occurred during VPN check (command)")
        await update.message.reply_text("🚨 Error inesperado al verificar la VPN.")


async def downloads_command(update: Update, context: CallbackContext) -> None:
    """Handles the /downloads command."""
    # user = update.effective_user # Not used

    await update.message.reply_text("Fetching download status from qBittorrent...")

    message, error = get_qbittorrent_downloads()

    if error:
        await update.message.reply_text(f"Error: {error}")
    elif message:
        max_len = 4096
        if len(message) == 0: # Should be handled by get_qbittorrent_downloads returning specific message
            await update.message.reply_text('No active Downloads', parse_mode='HTML')
        elif len(message) > max_len:
             for i in range(0, len(message), max_len):
                  await update.message.reply_text(message[i:i+max_len], parse_mode='HTML')
        else:
            try:
                await update.message.reply_text(message, parse_mode='HTML')
            except Exception: # Catch more specific telegram.error.BadRequest if possible
                logger.exception(f"Failed to send message (possibly due to Markdown formatting): {message}")
                await update.message.reply_text("Failed to send download status due to formatting. Check logs. Will try plain text.")
                await update.message.reply_text(message) # Fallback to plain text
    else:
        await update.message.reply_text("Could not retrieve download status or no downloads.")


async def start(update: Update, context: CallbackContext) -> int:
    """Sends a welcome message and asks what to search for."""
    user = update.effective_user 
    chat_id_msg = update.effective_chat.id # Simplified

    keyboard = [
        [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        [InlineKeyboardButton("📺 Series", callback_data='series')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id_msg,text=f"Hi {user.mention_html()}! What would you like to search for?",reply_markup=reply_markup, parse_mode='HTML')
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

    if search_type == 'cancel': # Should match a cancel button if one exists at this stage
        return await _restart_conversation(update, context)

    context.user_data['search_type'] = search_type
    await query.edit_message_text(f"Okay, searching for a {search_type}. Please enter the title:")
    return SEARCH_QUERY

async def _render_search_results(update: Update, context: CallbackContext, results: list) -> int:
    """Displays search results with inline buttons."""
    # No try-except here, will be handled by global error handler or calling function's try-except
    context.user_data['search_results'] = results
    keyboard = []
    for i, item in enumerate(results[:10]):
        title = item.get('title', 'N/A')
        year = item.get('year', '')
        # HTML escape title for button text if it can contain special characters
        button_text = f"{html.escape(str(title))} ({year})" if year else html.escape(str(title))
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f'choose_{i}')])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel')]) # Universal cancel
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = "Here's what I found:"
    if update.callback_query: # If called from a button press (like 'back')
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
    else: # If called after a text message (initial search)
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    return CHOOSE_ITEM


async def search_query_received(update: Update, context: CallbackContext) -> int:
    """Performs the search based on the type and query, then displays results."""
    query_text = update.message.text
    search_type = context.user_data.get('search_type')
    user_id = update.effective_user.id

    if not is_user_allowed(user_id):
        await update.message.reply_text("Sorry, you are not authorized.")
        return ConversationHandler.END

    await update.message.reply_text(f"Searching for {search_type}: '{html.escape(query_text)}'...")

    results = []
    if search_type == 'movie':
        results = search_radarr(query_text) # query_text is not escaped for API call
    elif search_type == 'series':
        results = search_sonarr(query_text) # query_text is not escaped for API call

    if results is None:
        return await _restart_conversation(update, context)
    if not results:
        await update.message.reply_text("Sorry, I couldn't find anything matching that title.")
        return await _restart_conversation(update, context)

    return await _render_search_results(update, context, results)


async def item_chosen(update: Update, context: CallbackContext) -> int:
    """Handles the user's choice from the search results and asks for confirmation."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == 'cancel':
        return await _restart_conversation(update, context)
    if callback_data == 'back_to_results': 
        results = context.user_data.get('search_results')
        if results:
            # Delete the current message (confirmation message) before showing results again
            await query.delete_message() 
            return await _render_search_results(update, context, results)
        else: 
            return await _restart_conversation(update, context)


    if not callback_data.startswith('choose_'):
        return await _restart_conversation(update, context)

    try:
        choice_index = int(callback_data.split('_')[1])
        results = context.user_data.get('search_results', []) 
        if not 0 <= choice_index < len(results):
            raise ValueError("Choice index out of bounds.")

        chosen_item = results[choice_index]
        context.user_data['chosen_item'] = chosen_item

        title = chosen_item.get('title', 'N/A')
        year = chosen_item.get('year', '')
        overview = chosen_item.get('overview', 'No description available.')
        poster_url = None
        images = chosen_item.get('images', [])
        if images:
            poster_info = next((img for img in images if img.get('coverType') == 'poster'), None)
            if poster_info:
                poster_url = poster_info.get('remoteUrl') or poster_info.get('url')

        title_str = html.escape(str(title) if title is not None else 'N/A')
        overview_str = html.escape(str(overview) if overview is not None else 'No description available.')
        message_text = f"<b>{title_str} ({year})</b>\n\n{overview_str}"
        
        keyboard = [
            [InlineKeyboardButton("✅ Add this", callback_data='confirm_add')],
            [InlineKeyboardButton("⬅️ Back to search results", callback_data='back_to_results')],
            [InlineKeyboardButton("❌ Cancel Search", callback_data='cancel_search_completely')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.delete_message() # Delete the "Here's what I found" message (results list)

        if poster_url:
            try:
                await context.bot.send_photo( 
                    chat_id=update.effective_chat.id,
                    photo=poster_url,
                    caption=message_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            except Exception: 
                logger.exception(f"Failed to send photo {poster_url}. Sending text instead.")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=message_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        return CONFIRM_ADD

    except (ValueError, IndexError) :
        logger.exception("Error processing item choice (ValueError or IndexError)")
        return await _restart_conversation(update, context)
    except Exception: 
        logger.exception("Unexpected error in item_chosen")
        return await _restart_conversation(update, context)


async def add_item_confirmed(update: Update, context: CallbackContext) -> int:
    """Adds the chosen item to Sonarr/Radarr."""
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    
    original_message_id = query.message.message_id # Store for potential later use if caption fails
    original_chat_id = query.message.chat_id

    if callback_data == 'back_to_results':
        await query.delete_message() 
        results = context.user_data.get('search_results')
        if results: 
            return await _render_search_results(update, context, results)
        else: 
            return await _restart_conversation(update, context)
    
    if callback_data == 'cancel_search_completely':
        await query.delete_message() 
        return await _restart_conversation(update, context)

    if callback_data != 'confirm_add':
        await query.delete_message() 
        return await _restart_conversation(update, context)

    chosen_item = context.user_data.get('chosen_item')
    search_type = context.user_data.get('search_type')

    if not chosen_item or not search_type :
        logger.error("Missing context (chosen_item or search_type) in add_item_confirmed.")
        await query.delete_message() 
        return await _restart_conversation(update, context)

    title = chosen_item.get('title', 'N/A')
    title_str = html.escape(str(title) if title is not None else 'N/A') # Escaped title
    
    caption_text_adding = f"⏳ Adding '{title_str}' to {'Sonarr' if search_type == 'series' else 'Radarr'}..."
    try:
        if query.message.caption:
            await query.edit_message_caption(caption=caption_text_adding, parse_mode='HTML', reply_markup=None)
        else:
            await query.edit_message_text(text=caption_text_adding, parse_mode='HTML', reply_markup=None)
    except Exception as e_edit_adding:
        logger.exception(f"Failed to edit message to 'Adding...': {e_edit_adding}. Attempting to send as new message.")
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=caption_text_adding, parse_mode='HTML')
            # Attempt to delete the original message with buttons
            await query.delete_message()
        except Exception as e_send_new:
            logger.exception(f"Failed to send new 'Adding...' message or delete original: {e_send_new}")

    success = False
    if search_type == 'movie':
        success = add_movie_to_radarr(chosen_item)
    elif search_type == 'series':
        success = add_series_to_sonarr(chosen_item)

    result_text = ""
    if success:
        result_text = f"✅ Successfully added '{title_str}' and started search."
    else:
        result_text = f"❌ Failed to add '{title_str}'. Check logs for details."
    
    try:
        if query.message.caption:
            await query.edit_message_caption(caption=result_text, parse_mode='HTML', reply_markup=None)
        else:
            await query.edit_message_text(text=result_text, parse_mode='HTML', reply_markup=None)
    except Exception as e_edit_final:
        logger.exception(f"Failed to edit message with final result: {e_edit_final}. Attempting to send as new message.")
        try:
            # No need to delete original message here if edit failed, as it's already the final status.
            await context.bot.send_message(chat_id=update.effective_chat.id, text=result_text, parse_mode='HTML')
        except Exception as e_send_new_final:
            logger.exception(f"Failed to send new final result message: {e_send_new_final}")

    context.user_data.pop('search_type', None)
    context.user_data.pop('search_results', None)
    context.user_data.pop('chosen_item', None)
    
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        [InlineKeyboardButton("📺 Series", callback_data='series')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Hi {user.mention_html()}! What would you like to search for next?",reply_markup=reply_markup, parse_mode='HTML')

    return SEARCH_TYPE 

async def cancel_conversation(update: Update, context: CallbackContext) -> int:
    """Cancels the current conversation via a /cancel command or button not in a state."""
    return await _restart_conversation(update, context)


async def cancel_conversation_and_restart(update: Update, context: CallbackContext) -> int:
    """Handles 'cancel' button presses that are part of the conversation flow."""
    return await _restart_conversation(update, context)

async def unknown_command(update: Update, context: CallbackContext) -> int:
    """Handles unknown commands during the conversation by restarting it."""
    await update.message.reply_text("Sorry, I didn't understand that command. Let's start over.")
    return await _restart_conversation(update, context)

async def unknown_state_handler(update: Update, context: CallbackContext) -> int:
    """Handles any unexpected message or callback query in any state, restarting conversation."""
    current_state = context.user_data.get('_state_name', 'an unknown state') 
    logger.warning(f"Unhandled update received in {current_state}: {update}")
    
    message_to_user = "Something went wrong or I received unexpected input. Let's start over."
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass 
        
        try:
            await update.callback_query.edit_message_text(message_to_user)
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message_to_user)
    else: 
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message_to_user)

    for key in ['search_type', 'search_results', 'chosen_item', '_state_name']:
        context.user_data.pop(key, None)
        
    return ConversationHandler.END
