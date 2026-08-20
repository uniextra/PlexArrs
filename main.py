import logging
from telegram import BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
)

from config import TELEGRAM_BOT_TOKEN, validate_config
from telegram_handlers import (
    start,
    help_command,
    downloads_command,
    search_type_chosen,
    search_query_received,
    item_chosen,
    add_item_confirmed,
    cancel_conversation,
    cancel_conversation_and_restart,
    _restart_conversation,
    global_error_handler,
    SEARCH_TYPE,
    SEARCH_QUERY,
    CHOOSE_ITEM,
    CONFIRM_ADD,
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d - %(funcName)s()] %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


if __name__ == '__main__':
    """Start the bot."""
    validate_config()

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
            CallbackQueryHandler(_restart_conversation),
        ],
        per_user=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("downloads", downloads_command))
    application.add_handler(CommandHandler("cancel", cancel_conversation))
    application.add_handler(CallbackQueryHandler(_restart_conversation, pattern='^back_to_start$'))

    # Global Error Handler
    application.add_error_handler(global_error_handler)

    # Define base commands for Telegram UI menu
    base_commands = [
        BotCommand("start", "Iniciar una nueva búsqueda"),
        BotCommand("downloads", "Ver descargas actuales"),
        BotCommand("help", "Mostrar ayuda"),
        BotCommand("cancel", "Cancelar la operación actual"),
    ]

    async def post_init_commands(context_param: CallbackContext) -> None:
        try:
            await context_param.bot.set_my_commands(base_commands)
            logger.info("Bot commands successfully set.")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}", exc_info=True)

    if application.job_queue:
        application.job_queue.run_once(post_init_commands, when=0)

    logger.info("Starting PlexArrs bot...")
    application.run_polling()
    logger.info("Bot stopped.")
