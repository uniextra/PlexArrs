import logging
import html
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler

from config import DEFAULT_TIMEOUT, SPOTIFY_API_URL
from utils import restricted, http_session
from sonarr_client import search_sonarr, add_series_to_sonarr
from radarr_client import search_radarr, add_movie_to_radarr
from qb_client import get_qbittorrent_downloads

logger = logging.getLogger(__name__)

# Conversation states
SEARCH_TYPE, SEARCH_QUERY, CHOOSE_ITEM, CONFIRM_ADD = range(4)


def _clear_user_data(context: CallbackContext) -> None:
    """Safely cleans up all conversation-related keys from context.user_data."""
    for key in ['search_type', 'search_results', 'chosen_item', '_state_name']:
        context.user_data.pop(key, None)


def _build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Builds the selection keyboard, dynamically including Spotify only if SPOTIFY_API_URL is configured."""
    keyboard = [
        [InlineKeyboardButton("🎬 Movie", callback_data='movie')],
        [InlineKeyboardButton("📺 Series", callback_data='series')],
    ]
    if SPOTIFY_API_URL:
        keyboard.append([InlineKeyboardButton("🎵 Spotify Playlist", callback_data='spotify')])
    return InlineKeyboardMarkup(keyboard)


async def _restart_conversation(update: Update, context: CallbackContext) -> int:
    """Cleans up user data and sends the initial prompt, restarting the conversation."""
    logger.info("Restarting conversation and returning to main selection.")
    _clear_user_data(context)

    user = update.effective_user
    user_name = user.mention_html() if user else "there"
    message_text = f"Hi {user_name}! What would you like to search for?"
    reply_markup = _build_main_menu_keyboard()

    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"Could not answer callback query during restart: {e}")
        try:
            await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode='HTML')
        except Exception:
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=message_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
    elif update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

    return ConversationHandler.END


@restricted
async def start(update: Update, context: CallbackContext) -> int:
    """Sends welcome message and displays search options."""
    _clear_user_data(context)
    user = update.effective_user
    user_name = user.mention_html() if user else "there"
    reply_markup = _build_main_menu_keyboard()

    if update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Hi {user_name}! What would you like to search for?",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    return SEARCH_TYPE


@restricted
async def help_command(update: Update, context: CallbackContext) -> None:
    """Displays help information."""
    if update.message:
        media_types = "Movies, Series, or Spotify" if SPOTIFY_API_URL else "Movies or Series"
        await update.message.reply_text(
            "🤖 <b>Bot Commands:</b>\n\n"
            f"• /start - Start a new search for {media_types}\n"
            "• /downloads - Check active qBittorrent downloads\n"
            "• /help - Show this help message\n"
            "• /cancel - Cancel the current action",
            parse_mode='HTML'
        )


@restricted
async def downloads_command(update: Update, context: CallbackContext) -> None:
    """Handles the /downloads command non-blockingly with safe message splitting."""
    if not update.message:
        return

    await update.message.reply_text("⏳ Fetching download status from qBittorrent...")

    # Run blocking qBittorrent I/O in a separate thread to avoid freezing the event loop
    message, error = await asyncio.to_thread(get_qbittorrent_downloads)

    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data='back_to_start')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if error:
        await update.message.reply_text(f"❌ Error: {error}", reply_markup=reply_markup)
        return

    if not message:
        await update.message.reply_text("Could not retrieve download status or no active downloads.", reply_markup=reply_markup)
        return

    # Split message safely by lines if length exceeds Telegram limits (4000 chars)
    max_len = 4000
    if len(message) <= max_len:
        try:
            await update.message.reply_text(message, parse_mode='HTML', reply_markup=reply_markup)
        except Exception:
            logger.exception("Failed to send formatted HTML download message. Falling back to plain text.")
            await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        lines = message.split('\n')
        chunks = []
        current_chunk = []
        current_len = 0

        for line in lines:
            if current_len + len(line) + 1 > max_len:
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_len = len(line) + 1
            else:
                current_chunk.append(line)
                current_len += len(line) + 1

        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        for idx, chunk in enumerate(chunks):
            is_last = (idx == len(chunks) - 1)
            chunk_markup = reply_markup if is_last else None
            try:
                await update.message.reply_text(chunk, parse_mode='HTML', reply_markup=chunk_markup)
            except Exception:
                await update.message.reply_text(chunk, reply_markup=chunk_markup)


@restricted
async def search_type_chosen(update: Update, context: CallbackContext) -> int:
    """Stores the chosen search type and asks for query."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Could not answer callback query: {e}")

    search_type = query.data
    if search_type == 'cancel':
        return await _restart_conversation(update, context)

    context.user_data['search_type'] = search_type

    if search_type == 'spotify':
        if not SPOTIFY_API_URL:
            await query.edit_message_text("⚠️ Spotify integration is not configured on this server.")
            return await _restart_conversation(update, context)
        await query.edit_message_text("🎵 Please enter the Spotify Playlist URL:")
    else:
        await query.edit_message_text(f"🔍 Searching for a <b>{html.escape(str(search_type))}</b>. Please enter the title:", parse_mode='HTML')
    return SEARCH_QUERY


async def _render_search_results(update: Update, context: CallbackContext, results: list) -> int:
    """Displays search results with inline buttons."""
    context.user_data['search_results'] = results
    keyboard = []
    for i, item in enumerate(results[:10]):
        title = item.get('title', 'N/A')
        year = item.get('year', '')
        button_text = f"{title} ({year})" if year else str(title)
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f'choose_{i}')])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = "Here's what I found:"
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    return CHOOSE_ITEM


def _sync_spotify_playlist(query_text: str) -> tuple[dict | None, str | None]:
    """Helper to communicate with Spotify service synchronously in worker thread."""
    if not SPOTIFY_API_URL:
        return None, "Spotify service URL (SPOTIFY_API_URL) is not configured."

    api_endpoint = f"{SPOTIFY_API_URL.rstrip('/')}/api/saved-items"
    try:
        payload1 = {"search": query_text}
        res1 = http_session.post(api_endpoint, json=payload1, timeout=DEFAULT_TIMEOUT)
        res1.raise_for_status()
        data = res1.json()

        playlist = None
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("type") == "spotify-playlist":
                    playlist = item
                    break

        if not playlist:
            return None, "Could not find a valid Spotify playlist from that URL."

        playlist_id = playlist.get("id")
        if not playlist_id:
            return None, "Playlist ID not found in the response."

        payload2 = {"ids": [playlist_id], "sync": True, "sync_interval": "10", "label": ""}
        res2 = http_session.put(api_endpoint, json=payload2, timeout=DEFAULT_TIMEOUT)
        res2.raise_for_status()

        return playlist, None
    except requests.exceptions.ConnectionError:
        logger.exception(f"Connection refused to Spotify service at {SPOTIFY_API_URL}")
        return None, f"Could not connect to Spotify service at {SPOTIFY_API_URL}. Check that the service is running and reachable."
    except requests.exceptions.Timeout:
        logger.exception(f"Timeout connecting to Spotify service at {SPOTIFY_API_URL}")
        return None, f"Timeout connecting to Spotify service at {SPOTIFY_API_URL}."
    except requests.RequestException as e:
        logger.exception("Network error while adding Spotify playlist")
        return None, f"Network error: {e}"
    except Exception as e:
        logger.exception("Unexpected error while adding Spotify playlist")
        return None, f"Unexpected error: {e}"


@restricted
async def search_query_received(update: Update, context: CallbackContext) -> int:
    """Performs search in worker thread and renders results."""
    if not update.message or not update.message.text:
        return ConversationHandler.END

    query_text = update.message.text.strip()
    search_type = context.user_data.get('search_type')

    if search_type == 'spotify':
        await update.message.reply_text("⏳ Processing Spotify playlist...")
        playlist, error = await asyncio.to_thread(_sync_spotify_playlist, query_text)

        if error or not playlist:
            await update.message.reply_text(f"❌ {error or 'Failed to add Spotify playlist.'}")
            return await _restart_conversation(update, context)

        title = playlist.get("title", "Unknown Playlist")
        image_url = playlist.get("image")
        title_str = html.escape(str(title))
        message_text = f"✅ Successfully added Spotify Playlist:\n<b>{title_str}</b>"
        reply_markup = _build_main_menu_keyboard()

        if image_url:
            try:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=image_url,
                    caption=message_text,
                    parse_mode='HTML'
                )
            except Exception:
                logger.exception(f"Failed to send photo {image_url}. Sending text instead.")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=message_text,
                    parse_mode='HTML'
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message_text,
                parse_mode='HTML'
            )

        context.user_data.pop('search_type', None)
        user = update.effective_user
        user_name = user.mention_html() if user else "there"
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Hi {user_name}! What would you like to search for next?",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return ConversationHandler.END

    await update.message.reply_text(f"⏳ Searching for {search_type}: <i>{html.escape(query_text)}</i>...", parse_mode='HTML')

    results = []
    if search_type == 'movie':
        results = await asyncio.to_thread(search_radarr, query_text)
    elif search_type == 'series':
        results = await asyncio.to_thread(search_sonarr, query_text)

    if results is None:
        return await _restart_conversation(update, context)
    if not results:
        await update.message.reply_text("Sorry, I couldn't find anything matching that title.")
        return await _restart_conversation(update, context)

    return await _render_search_results(update, context, results)


@restricted
async def item_chosen(update: Update, context: CallbackContext) -> int:
    """Handles item selection from search results and displays confirmation card."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Could not answer callback query: {e}")

    callback_data = query.data

    if callback_data == 'cancel':
        return await _restart_conversation(update, context)
    if callback_data == 'back_to_results':
        results = context.user_data.get('search_results')
        if results:
            await query.delete_message()
            return await _render_search_results(update, context, results)
        return await _restart_conversation(update, context)

    if not callback_data or not callback_data.startswith('choose_'):
        return await _restart_conversation(update, context)

    try:
        choice_index = int(callback_data.split('_')[1])
        results = context.user_data.get('search_results', [])
        if not (0 <= choice_index < len(results)):
            raise ValueError("Choice index out of bounds.")

        chosen_item = results[choice_index]
        context.user_data['chosen_item'] = chosen_item

        title = chosen_item.get('title', 'N/A')
        year = chosen_item.get('year', '')
        overview = chosen_item.get('overview', 'No description available.')
        poster_url = None
        images = chosen_item.get('images', [])
        if isinstance(images, list):
            poster_info = next((img for img in images if isinstance(img, dict) and img.get('coverType') == 'poster'), None)
            if poster_info:
                poster_url = poster_info.get('remoteUrl') or poster_info.get('url')

        title_str = html.escape(str(title) if title is not None else 'N/A')
        overview_str = html.escape(str(overview) if overview is not None else 'No description available.')

        rating_value = None
        ratings_data = chosen_item.get('ratings')
        if isinstance(ratings_data, dict) and ratings_data.get('value') is not None:
            rating_value = ratings_data['value']

        message_text = f"<b>{title_str} ({year})</b>\n\n{overview_str}"
        if rating_value is not None:
            message_text += f"\n\n❤️ {rating_value}"

        keyboard = [
            [InlineKeyboardButton("✅ Add this", callback_data='confirm_add')],
            [InlineKeyboardButton("⬅️ Back to search results", callback_data='back_to_results')],
            [InlineKeyboardButton("❌ Cancel Search", callback_data='cancel_search_completely')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.delete_message()

        if poster_url and update.effective_chat:
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
        elif update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        return CONFIRM_ADD

    except (ValueError, IndexError):
        logger.exception("Error processing item choice (ValueError or IndexError)")
        return await _restart_conversation(update, context)
    except Exception:
        logger.exception("Unexpected error in item_chosen")
        return await _restart_conversation(update, context)


@restricted
async def add_item_confirmed(update: Update, context: CallbackContext) -> int:
    """Adds the chosen item to Sonarr/Radarr non-blockingly."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Could not answer callback query: {e}")

    callback_data = query.data

    if callback_data == 'back_to_results':
        await query.delete_message()
        results = context.user_data.get('search_results')
        if results:
            return await _render_search_results(update, context, results)
        return await _restart_conversation(update, context)

    if callback_data == 'cancel_search_completely' or callback_data != 'confirm_add':
        await query.delete_message()
        return await _restart_conversation(update, context)

    chosen_item = context.user_data.get('chosen_item')
    search_type = context.user_data.get('search_type')

    if not chosen_item or not search_type:
        logger.error("Missing context (chosen_item or search_type) in add_item_confirmed.")
        await query.delete_message()
        return await _restart_conversation(update, context)

    title = chosen_item.get('title', 'N/A')
    title_str = html.escape(str(title) if title is not None else 'N/A')
    target_service = 'Sonarr' if search_type == 'series' else 'Radarr'

    caption_text_adding = f"⏳ Adding '{title_str}' to {target_service}..."
    try:
        if query.message and query.message.caption:
            await query.edit_message_caption(caption=caption_text_adding, parse_mode='HTML', reply_markup=None)
        elif query.message:
            await query.edit_message_text(text=caption_text_adding, parse_mode='HTML', reply_markup=None)
    except Exception as e_edit:
        logger.warning(f"Could not edit message to 'Adding...': {e_edit}")

    # Perform blocking add in worker thread
    add_result = False
    if search_type == 'movie':
        add_result = await asyncio.to_thread(add_movie_to_radarr, chosen_item)
    elif search_type == 'series':
        add_result = await asyncio.to_thread(add_series_to_sonarr, chosen_item)

    if add_result is True:
        result_text = f"✅ Successfully added <b>{title_str}</b> and started search."
    elif isinstance(add_result, str):
        if add_result in ('SeriesExistsValidator', 'MovieExistsValidator'):
            result_text = f"⚠️ <b>{title_str}</b> already exists in {target_service}."
        else:
            result_text = f"❌ Failed to add <b>{title_str}</b>. Error code: <code>{add_result}</code>."
    else:
        result_text = f"❌ Failed to add <b>{title_str}</b>. Check logs for details."

    try:
        if query.message and query.message.caption:
            await query.edit_message_caption(caption=result_text, parse_mode='HTML', reply_markup=None)
        elif query.message:
            await query.edit_message_text(text=result_text, parse_mode='HTML', reply_markup=None)
    except Exception:
        if update.effective_chat:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=result_text, parse_mode='HTML')

    _clear_user_data(context)

    user = update.effective_user
    user_name = user.mention_html() if user else "there"
    reply_markup = _build_main_menu_keyboard()

    if update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Hi {user_name}! What would you like to search for next?",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

    return ConversationHandler.END


@restricted
async def cancel_conversation(update: Update, context: CallbackContext) -> int:
    """Cancels the current conversation."""
    return await _restart_conversation(update, context)


@restricted
async def cancel_conversation_and_restart(update: Update, context: CallbackContext) -> int:
    """Handles inline cancel buttons."""
    return await _restart_conversation(update, context)


async def global_error_handler(update: object, context: CallbackContext) -> None:
    """Global error handler that logs exceptions and notifies users gracefully."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ An unexpected error occurred. Please try again with /start.",
                reply_markup=_build_main_menu_keyboard()
            )
        except Exception as e:
            logger.warning(f"Failed to send error notification message: {e}")
