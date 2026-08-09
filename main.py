import logging
import sys, os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler

from telegram_handlers import (
    start, help_command, downloads_command,
    search_type_chosen, search_query_received, item_chosen, add_item_confirmed,
    cancel_conversation, cancel_conversation_and_restart, _restart_conversation
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

# Allowed User IDs - handle as a list of integers
allowed_users_str = os.environ.get('ALLOWED_USER_IDS')
ALLOWED_USER_IDS = [int(user_id.strip()) for user_id in allowed_users_str.split(',') if user_id.strip()] if allowed_users_str else None

# Conversation states
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
        sys.exit(1)

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
              sys.exit(1)

    logger.info(f"Allowed user IDs loaded: {ALLOWED_USER_IDS if ALLOWED_USER_IDS else 'None (all allowed)'}")


    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation handler for the search/add process
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(search_type_chosen, pattern='^movie$|^series$|^spotify$')],
        states={
            SEARCH_TYPE: [CallbackQueryHandler(search_type_chosen)],
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_query_received)],
            CHOOSE_ITEM: [CallbackQueryHandler(item_chosen, pattern='^choose_\\d+$|^cancel$|^backtosearch$')],
            CONFIRM_ADD: [CallbackQueryHandler(add_item_confirmed, pattern='^confirm_add$|^cancel_add$|^back_to_results$')],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation),
            CallbackQueryHandler(cancel_conversation_and_restart, pattern='^cancel$'),
            MessageHandler(filters.COMMAND, cancel_conversation),
            MessageHandler(filters.ALL, cancel_conversation),
            CallbackQueryHandler(_restart_conversation)
            ],
        per_user=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start, filters=filters.Chat(chat_id = ALLOWED_USER_IDS)))
    application.add_handler(CommandHandler("help", help_command, filters=filters.Chat(chat_id = ALLOWED_USER_IDS)))
    application.add_handler(CommandHandler("downloads", downloads_command, filters=filters.Chat(chat_id = ALLOWED_USER_IDS)))
    application.add_handler(CommandHandler("cancel", cancel_conversation, filters=filters.Chat(chat_id = ALLOWED_USER_IDS)))
    application.add_handler(CallbackQueryHandler(_restart_conversation, pattern='^back_to_start$'))

    # Define base commands
    base_commands = [
        BotCommand("start", "Iniciar una nueva búsqueda"),
        BotCommand("downloads", "Ver descargas actuales"),
        BotCommand("help", "Mostrar ayuda"),
        BotCommand("cancel", "Cancelar la operación actual"),
    ]

    # Asynchronously set the bot commands
    async def post_init_commands(context_param: CallbackContext):
        try:
            await context_param.bot.set_my_commands(base_commands)
            logger.info("Bot commands successfully set.")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}", exc_info=True)

    application.job_queue.run_once(post_init_commands, when=0)

    # Run the bot using polling
    logger.info("Starting bot...")
    application.run_polling()
    logger.info("Bot stopped.")
