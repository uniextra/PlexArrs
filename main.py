import logging
import requests
import json
import sys, os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler
import re
import qbittorrentapi # Use the new library
from config import (
    TELEGRAM_BOT_TOKEN, SONARR_URL, SONARR_API_KEY, RADARR_URL, RADARR_API_KEY,
    QBITTORRENT_URL, QBITTORRENT_USERNAME, QBITTORRENT_PASSWORD,
    SONARR_ROOT_FOLDER_ID, SONARR_QUALITY_PROFILE_ID,
    RADARR_ROOT_FOLDER_ID, RADARR_QUALITY_PROFILE_ID,
    gluetunCheck, gluetunUser, gluetunPass, ALLOWED_USER_IDS,
    SEARCH_TYPE, SEARCH_QUERY, CHOOSE_ITEM, CONFIRM_ADD
)
from utils import is_user_allowed, make_api_request, escape_markdown_v2
from sonarr_client import search_sonarr, add_series_to_sonarr
from radarr_client import search_radarr, add_movie_to_radarr
from qb_client import get_qbittorrent_downloads

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d - %(funcName)s()] %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

async def _restart_conversation(update: Update, context: CallbackContext, message: str) -> int:
    """Cleans up user data and sends the initial prompt, restarting the conversation."""
    logger.info(f"Restarting conversation: {message}")

    # Clean up user data defensively
    for key in ['search_type', 'search_results', 'chosen_item']:
        context.user_data.pop(key, None)

    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Operation cancelled.4")
    else:
        await update.message.reply_text("Operation cancelled.5")

    await context.bot.send_message(chat_id=update.effective_chat.id,text="Envia el comando /start por favor para reiniciar la conversación.", parse_mode='HTML')

    return ConversationHandler.END # Return the correct state to handle button clicks

async def check_vpn_ip_job(context: CallbackContext) -> None:
    """Checks the public IP and sends a Telegram alert if the country is not Netherlands."""
    logger.info("Checking public IP (scheduled job)...")
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
            # Send Telegram message to the first allowed user
            if ALLOWED_USER_IDS:
                await context.bot.send_message(chat_id=ALLOWED_USER_IDS[0], text="🚨 Alerta: La VPN parece estar caída o no está en Países Bajos.")
            else:
                logger.warning("No allowed user IDs configured to send VPN alert.")

    except requests.exceptions.RequestException as e:
        logger.exception("Error checking public IP (scheduled job)")
        # Send Telegram message about the error to the first allowed user
        if ALLOWED_USER_IDS:
            await context.bot.send_message(chat_id=ALLOWED_USER_IDS[0], text=f"🚨 Error al verificar la VPN (programado): {e}")
        else:
            logger.warning("No allowed user IDs configured to send VPN error alert.")
    except json.JSONDecodeError as e:
        logger.exception("Failed to decode JSON from IP check response (scheduled job)")
        # Send Telegram message about the JSON error to the first allowed user
        if ALLOWED_USER_IDS:
            await context.bot.send_message(chat_id=ALLOWED_USER_IDS[0], text=f"🚨 Error al procesar la respuesta de la VPN (programado): {e}")
        else:
            logger.warning("No allowed user IDs configured to send VPN JSON error alert.")
    except Exception as e:
        logger.exception("An unexpected error occurred during VPN check (scheduled job)")
        # Send Telegram message about unexpected error to the first allowed user
        if ALLOWED_USER_IDS:
            await context.bot.send_message(chat_id=ALLOWED_USER_IDS[0], text=f"🚨 Error inesperado al verificar la VPN (programado): {e}")
        else:
            logger.warning("No allowed user IDs configured to send unexpected VPN error alert.")


async def vpnstatus_command(update: Update, context: CallbackContext) -> None:
    """Checks the public IP and sends a Telegram alert if the country is not Netherlands."""
    # This command handler can reuse the logic from the scheduled job, but send the message to the user who issued the command
    logger.info("Checking public IP (command)...")
    url = "http://192.168.1.137:8111/v1/publicip/ip"  #Gluetun
    
    try:
        response = requests.get(url, auth=(gluetunUser, gluetunPass), timeout=10)
        response.raise_for_status() # Raise an exception for bad status codes

        ip_info = response.json()
        logger.debug(f"IP Info response: {ip_info}")

        if "country" in ip_info and ip_info["country"] == "Netherlands":
            await update.message.reply_text("VPN IP is in Netherlands. All good.")
        else:
            await update.message.reply_text(f"🚨 Alerta: La VPN parece estar caída o no está en Países Bajos. Current country: {ip_info.get('country', 'N/A')}.")

    except requests.exceptions.RequestException as e:
        logger.exception("Error checking public IP (command)")
        await update.message.reply_text(f"🚨 Error al verificar la VPN: {e}")
    except json.JSONDecodeError as e:
        logger.exception("Failed to decode JSON from IP check response (command)")
        await update.message.reply_text(f"🚨 Error al procesar la respuesta de la VPN: {e}")
    except Exception as e:
        logger.exception("An unexpected error occurred during VPN check (command)")
        await update.message.reply_text(f"🚨 Error inesperado al verificar la VPN: {e}")


# --- Telegram Bot Handlers ---

async def downloads_command(update: Update, context: CallbackContext) -> None:
    """Handles the /downloads command."""
    user = update.effective_user

    await update.message.reply_text("Fetching download status from qBittorrent...")

    message, error = get_qbittorrent_downloads()

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
                logger.exception(f"Failed to send message: {message}") # e is already part of exception
                await update.message.reply_text("Failed to send download status. Check logs for details.")
    else:
        # This case should ideally be handled by get_qbittorrent_downloads returning a specific message
        await update.message.reply_text("Could not retrieve download status.")


async def start(update: Update, context: CallbackContext) -> int:
    """Sends a welcome message and asks what to search for."""
    user = update.effective_user 

    try:
        chat_id_msg = update.message.from_user['id']

    except:
        chat_id_msg = update.callback_query.from_user['id']




    # Initial prompt without the Cancel button
    keyboard = [
        [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        [InlineKeyboardButton("📺 Series", callback_data='series')],
        # [InlineKeyboardButton("❌ Cancel", callback_data='cancel')], # Removed initial cancel button
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id_msg,text=f"Hi {user.mention_html()}! What would you like to search for?",reply_markup=reply_markup, parse_mode='HTML')
    # await update.message.reply_text(
    #     f"Hi {user.mention_html()}! What would you like to search for?",
    #     reply_markup=reply_markup,
    #     parse_mode='HTML'
    # )
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
        return await cancel_conversation(update, context)

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
        logger.exception(f"Error _render_search_results: {e}")
        # Use the restart helper on error
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
        return await cancel_conversation(update, context)


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
            logger.exception(f"Could not delete message on cancel: {e}. Trying edit instead.")
            try:
                 # Edit using query context as fallback if delete failed
                 await query.edit_message_text("Okay, I won't add it. Operation cancelled.7")
            except Exception as e2:
                 logger.exception(f"Could not edit message on cancel either: {e2}")
                 # Final fallback: send new message if possible
                 await context.bot.send_message("Okay, I won't add it. Operation cancelled.8")

        # Clean up user data here as well for cancellation
        context.user_data.pop('search_type', None)
        context.user_data.pop('search_results', None)
        context.user_data.pop('chosen_item', None)
        # Use the restart helper after cancelling the add
        # The previous logic sent multiple messages, let's simplify with the helper
        return await _restart_conversation(update, context, "Okay, I won't add it. Operation cancelled.9")

    # Keep handling 'cancel' just in case, though fallbacks might catch it too
    if callback_data == 'cancel':
        # Use the restart helper
        return await _restart_conversation(update, context, "Operation cancelled.6")


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
        logger.exception(f"Error processing item choice: {e}") # or just "Error processing item choice"
        # Use the restart helper on error
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
            logger.exception(f"Could not delete message on cancel: {e}. Trying edit instead.")
            try:
                 # Edit using query context as fallback if delete failed
                 await query.edit_message_text("Okay, I won't add it. Operation cancelled.7")
            except Exception as e2:
                 logger.exception(f"Could not edit message on cancel either: {e2}")
                 # Final fallback: send new message if possible
                 if update_message:
                      await update_message.reply_text("Okay, I won't add it. Operation cancelled.8")

        # Clean up user data here as well for cancellation
        context.user_data.pop('search_type', None)
        context.user_data.pop('search_results', None)
        context.user_data.pop('chosen_item', None)
        # Use the restart helper after cancelling the add
        # The previous logic sent multiple messages, let's simplify with the helper
        return await _restart_conversation(update, context, "Okay, I won't add it. Operation cancelled.9")

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
                 logger.exception(f"Could not edit message on cancel_add (restart) either: {e2}")
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
        logger.exception("Failed to send 'Adding...' status message")
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
            logger.exception("Failed to edit status message. Sending new message instead.")
            # Fallback: send result as a new message if editing fails
            await context.bot.send_message(chat_id=update.effective_chat.id, text=result_text)
    else:
         # If status message failed, send result as new message
         if success:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ Successfully added '{title}' and started search.")
         else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Failed to add '{title}'. Check logs for details.")


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
        await query.edit_message_text("Operation cancelled.1 envia /start")
    else:
        await update.message.reply_text("Operation cancelled.2 envia /start")

    # Clean up user data
    context.user_data.pop('search_type', None)
    context.user_data.pop('search_results', None)
    context.user_data.pop('chosen_item', None)
    return ConversationHandler.END

async def cancel_conversation_and_restart(update: Update, context: CallbackContext) -> int:
    """Handles 'cancel' button presses within the conversation, restarting it."""
    return await _restart_conversation(update, context, "Operation cancelled.3")

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


if __name__ == '__main__':
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
        sys.exit(1) # Use sys.exit instead of return

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
              sys.exit(1) # Use sys.exit instead of return

    logger.info(f"Allowed user IDs loaded: {ALLOWED_USER_IDS if ALLOWED_USER_IDS else 'None (all allowed)'}")


    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build() # Use loaded env var

    # Conversation handler for the search/add process
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start, filters=filters.Chat(chat_id = ALLOWED_USER_IDS))],
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
            MessageHandler(filters.COMMAND, cancel_conversation), # Handle unknown commands within the conversation
            MessageHandler(filters.ALL, cancel_conversation), # Handle unexpected text/messages
            CallbackQueryHandler(cancel_conversation) # Handle unexpected callbacks            
            # MessageHandler(filters.COMMAND, unknown_command), # Handle unknown commands within the conversation
            # MessageHandler(filters.ALL, unknown_state_handler), # Handle unexpected text/messages
            # CallbackQueryHandler(unknown_state_handler) # Handle unexpected callbacks
            ],
        # Let's keep per_user=True for now, it's generally safer for conversation state management.
        per_user=True # Store conversation state per user
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command, filters=filters.Chat(chat_id = ALLOWED_USER_IDS)))
    application.add_handler(CommandHandler("vpnstatus", vpnstatus_command, filters=filters.Chat(chat_id = ALLOWED_USER_IDS)))
    application.add_handler(CommandHandler("downloads", downloads_command, filters=filters.Chat(chat_id = ALLOWED_USER_IDS))) # Add the new command handler
    application.add_handler(CallbackQueryHandler(cancel_conversation)) #unknown_state_handler

    # Set bot commands for the menu button
    commands = [
        BotCommand("start", "Iniciar una nueva búsqueda"),
        BotCommand("downloads", "Ver descargas actuales"),
        BotCommand("help", "Mostrar ayuda"),
        BotCommand("cancel", "Cancelar la operación actual"),
    ]

    # Schedule the VPN check function
    # Check if the gluetunCheck variable is set to 'True'    
    if gluetunCheck == 'True':
        commands.append(BotCommand("vpnstatus", "Verificar estado de VPN")) # Add the VPN status command if enabled
        logger.info("VPN check enabled. Scheduling VPN IP check.")
        # Schedule the VPN check every 10 minutes
        # application.job_queue.run_repeating(check_vpn_ip_job, interval=600, first=10) # 600 seconds = 10 minutes

    # Use run_sync for potentially blocking operations if needed, but set_my_commands is usually quick
    # await application.bot.set_my_commands(commands)
    # For simplicity in this context, let's assume direct call is okay or handle potential blocking if necessary
    # Using a synchronous approach within the async main function requires care.
    # A common pattern is to run it in a separate thread or use asyncio's run_in_executor.
    # However, python-telegram-bot v20+ handles this internally more gracefully.
    # Let's try the direct await first. If it causes issues, we might need adjustment.
    # Removed the await application.bot.set_my_commands(commands) line

    # Schedule the VPN check function using jobqueue
    if gluetunCheck == 'True':
        commands.append(BotCommand("vpnstatus", "Verificar estado de VPN")) # Add the VPN status command if enabled
        logger.info("VPN check enabled. Scheduling VPN IP check.")
        # Schedule the VPN check every 10 minutes
        application.job_queue.run_repeating(check_vpn_ip_job, interval=600, first=10) # 600 seconds = 10 minutes

    # Run the bot using polling
    logger.info("Starting bot...")
    application.run_polling()
    logger.info("Bot stopped.")
