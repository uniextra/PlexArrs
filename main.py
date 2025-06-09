import logging
import requests
import json
import sys, os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler
import re
import qbittorrentapi # Use the new library

# from utils import is_user_allowed, make_api_request, escape_markdown_v2 # No longer needed directly in main
# from sonarr_client import search_sonarr, add_series_to_sonarr # No longer needed directly in main
# from radarr_client import search_radarr, add_movie_to_radarr # No longer needed directly in main
# from qb_client import get_qbittorrent_downloads # No longer needed directly in main
from telegram_handlers import (
    start, help_command, downloads_command, vpnstatus_command, check_vpn_ip_job,
    search_type_chosen, search_query_received, item_chosen, add_item_confirmed,
    cancel_conversation, cancel_conversation_and_restart, _restart_conversation,
    unknown_command, unknown_state_handler,
    # _render_search_results, _restart_conversation # These are internal to telegram_handlers.py
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d - %(funcName)s()] %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables directly
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
SONARR_URL = os.environ.get('SONARR_URL')
SONARR_API_KEY = os.environ.get('SONARR_API_KEY')
RADARR_URL = os.environ.get('RADARR_URL')
RADARR_API_KEY = os.environ.get('RADARR_API_KEY')
QBITTORRENT_URL = os.environ.get('QBITTORRENT_URL')
QBITTORRENT_USERNAME = os.environ.get('QBITTORRENT_USERNAME')
QBITTORRENT_PASSWORD = os.environ.get('QBITTORRENT_PASSWORD')

# Numeric IDs - provide default values or handle missing
SONARR_ROOT_FOLDER_ID = int(os.environ.get('SONARR_ROOT_FOLDER_ID', 1)) # Default to 1 if not set
SONARR_QUALITY_PROFILE_ID = int(os.environ.get('SONARR_QUALITY_PROFILE_ID', 1)) # Default to 1 if not set
RADARR_ROOT_FOLDER_ID = int(os.environ.get('RADARR_ROOT_FOLDER_ID', 1)) # Default to 1 if not set
RADARR_QUALITY_PROFILE_ID = int(os.environ.get('RADARR_QUALITY_PROFILE_ID', 1)) # Default to 1 if not set

# Gluetun variables
gluetunCheck = os.environ.get('gluetunCheck', 'False') # Default to 'False' if not set
gluetunUser = os.environ.get('gluetunUser')
gluetunPass = os.environ.get('gluetunPass')

# Allowed User IDs - handle as a list of integers
allowed_users_str = os.environ.get('ALLOWED_USER_IDS')
ALLOWED_USER_IDS = [int(user_id.strip()) for user_id in allowed_users_str.split(',') if user_id.strip()] if allowed_users_str else None

# Conversation states (assuming these are constants defined elsewhere or will be defined here)
# If these were imported from config, they need to be defined here or imported from another file
# For now, assuming they might be defined in telegram_handlers or are simple constants.
# If they were in config, they need to be moved or redefined. Let's define them here for now.
SEARCH_TYPE, SEARCH_QUERY, CHOOSE_ITEM, CONFIRM_ADD = range(4)


if __name__ == '__main__':
    """Start the bot."""
    # --- Environment Variable Check ---
    required_vars = {
        'TELEGRAM_BOT_TOKEN': TELEGRAM_BOT_TOKEN,
        'SONARR_URL': SONARR_URL,
        'SONARR_API_KEY': SONARR_API_KEY,
        'RADARR_URL': RADARR_URL,
        'RADARR_API_KEY': RADARR_API_KEY,
        'QBITTORRENT_URL': QBITTORRENT_URL
        # Username/Password are optional depending on qBittorrent setup, so not strictly required here
    }
    missing_vars = [name for name, value in required_vars.items() if not value]
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
            CallbackQueryHandler(_restart_conversation) # Handle unexpected callbacks
            # MessageHandler(filters.COMMAND, unknown_command), # Handle unknown commands within the conversation
            # MessageHandler(filters.ALL, unknown_state_handler), # Handle unexpected text/messages
            # CallbackQueryHandler(unknown_state_handler) # Handle unexpected callbacks
            ],
        # Let's keep per_user=True for now, it's generally safer for conversation state management.
        per_user=True # Store conversation state per user
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command, filters=filters.Chat(chat_id = ALLOWED_USER_IDS)))
    # application.add_handler(CommandHandler("vpnstatus", vpnstatus_command, filters=filters.Chat(chat_id = ALLOWED_USER_IDS)))
    application.add_handler(CommandHandler("downloads", downloads_command, filters=filters.Chat(chat_id = ALLOWED_USER_IDS))) # Add the new command handler
    application.add_handler(CommandHandler("cancel", cancel_conversation, filters=filters.Chat(chat_id = ALLOWED_USER_IDS))) # Add the new command handler

    # Set bot commands for the menu button
    commands = [
        BotCommand("start", "Iniciar una nueva búsqueda"),
        BotCommand("downloads", "Ver descargas actuales"),
        BotCommand("help", "Mostrar ayuda"),
        BotCommand("cancel", "Cancelar la operación actual"),
    ]

    # Schedule the VPN check function
    # Check if the gluetunCheck variable is set to 'True'
    # if gluetunCheck == 'True':
    #     commands.append(BotCommand("vpnstatus", "Verificar estado de VPN")) # Add the VPN status command if enabled
    #     logger.info("VPN check enabled. Scheduling VPN IP check.")
    #     # Schedule the VPN check every 10 minutes
    #     # application.job_queue.run_repeating(check_vpn_ip_job, interval=600, first=10) # 600 seconds = 10 minutes

    # Use run_sync for potentially blocking operations if needed, but set_my_commands is usually quick
    # await application.bot.set_my_commands(commands)
    # For simplicity in this context, let's assume direct call is okay or handle potential blocking if necessary
    # Using a synchronous approach within the async main function requires care.
    # A common pattern is to run it in a separate thread or use asyncio's run_in_executor.
    # However, python-telegram-bot v20+ handles this internally more gracefully.
    # Let's try the direct await first. If it causes issues, we might need adjustment.
    # Removed the await application.bot.set_my_commands(commands) line

    # Define base commands
    base_commands = [
        BotCommand("start", "Iniciar una nueva búsqueda"),
        BotCommand("downloads", "Ver descargas actuales"),
        BotCommand("help", "Mostrar ayuda"),
        BotCommand("cancel", "Cancelar la operación actual"),
    ]

    # # Add VPN status command if enabled
    # if gluetunCheck == 'True': # gluetunCheck is imported from config
    #     base_commands.append(BotCommand("vpnstatus", "Verificar estado de VPN"))
    #     # The job_queue setup for check_vpn_ip_job should already be there and is fine.
    #     # commands.append(BotCommand("vpnstatus", "Verificar estado de VPN")) # This is now handled below
    #     logger.info("VPN check enabled. Scheduling VPN IP check.")
    #     # Schedule the VPN check every 10 minutes
    #     application.job_queue.run_repeating(check_vpn_ip_job, interval=600, first=10) # 600 seconds = 10 minutes

    # Asynchronously set the bot commands
    # We need an async function to use await, and schedule it to run once.
    async def post_init_commands(context_param: CallbackContext): # Renamed context to context_param to avoid conflict
        try:
            await context_param.bot.set_my_commands(base_commands)
            logger.info("Bot commands successfully set.")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}", exc_info=True)

    # Schedule the command setting task to run once after the application is initialized.
    # The job_queue is available on the application object after it's built.
    application.job_queue.run_once(post_init_commands, when=0) # when=0 means as soon as possible

    # Run the bot using polling
    logger.info("Starting bot...")
    application.run_polling()
    logger.info("Bot stopped.")
