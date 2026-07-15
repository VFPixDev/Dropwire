import logging
from telegram import BotCommand, Update
from telegram.error import InvalidToken, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from src.config import config
from src.handlers.commands import admin_panel, downloads, help_command, settings, start, status
from src.handlers.callbacks import handle_callback_query
from src.handlers.chat_members import handle_my_chat_member
from src.handlers.messages import handle_message
from src.media.cleanup import cleanup_temp_files
from src.services.database import Database
from src.services.download_queue import DownloadQueue
from src.services.youtube_downloader import YtDlpDownloader
from src.utils.rate_limit import rate_limiter

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=getattr(logging, config.LOG_LEVEL)
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодическая очистка временных файлов и rate limiter"""
    logger.info("Запуск периодической очистки...")
    cleanup_temp_files(max_age_seconds=3600)
    rate_limiter.cleanup_old_entries(max_age=3600)
    downloader = context.application.bot_data.get("youtube_downloader")
    if isinstance(downloader, YtDlpDownloader):
        await downloader.cleanup_stale_files(config.DOWNLOAD_FILE_RETENTION_HOURS * 3600)
    logger.info("Периодическая очистка завершена")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log handler failures without leaking request data back to Telegram."""
    if isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning("Сетевая ошибка Telegram без автоматического повтора: %s", context.error)
        return
    error = context.error
    update_id = getattr(update, "update_id", None)
    exc_info = (type(error), error, error.__traceback__) if isinstance(error, BaseException) else None
    logger.error(
        "Необработанная ошибка update_id=%s error_type=%s",
        update_id,
        type(error).__name__,
        exc_info=exc_info,
    )


async def post_init(application: Application) -> None:
    """Инициализация после запуска бота"""
    database = Database(config.DATABASE_PATH)
    await database.connect()
    await database.init_schema()
    interrupted = await database.fail_interrupted_downloads()
    if interrupted:
        logger.warning("После перезапуска помечено неудачными загрузок: %s", interrupted)
    application.bot_data["database"] = database
    application.bot_data["download_queue"] = DownloadQueue(config.MAX_CONCURRENT_DOWNLOADS)
    application.bot_data["youtube_downloader"] = YtDlpDownloader(config.DOWNLOAD_DIR)

    try:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Главное меню"),
                BotCommand("settings", "Настройки"),
                BotCommand("downloads", "Мои загрузки"),
                BotCommand("help", "Справка"),
                BotCommand("status", "Состояние бота"),
            ]
        )
    except NetworkError as exc:
        logger.warning("Не удалось зарегистрировать команды Telegram: %s", exc)

    if not config.BOT_ADMIN_IDS:
        logger.warning("BOT_ADMIN_IDS не задан: глобальные настройки и админ-панель заблокированы")
    if not config.WEB_BASE_URL:
        logger.warning("WEB_BASE_URL не задан: YouTube-загрузки через браузер отключены")

    logger.info("Очистка временных файлов при старте...")
    cleanup_temp_files()
    logger.info("%s запущен и готов к работе", config.APP_NAME)


async def post_shutdown(application: Application) -> None:
    """Закрытие ресурсов приложения."""
    database = application.bot_data.get("database")
    if isinstance(database, Database):
        await database.close()


def main():
    """Запуск бота"""
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .connect_timeout(config.TELEGRAM_CONNECT_TIMEOUT)
        .read_timeout(config.TELEGRAM_READ_TIMEOUT)
        .write_timeout(config.TELEGRAM_WRITE_TIMEOUT)
        .pool_timeout(config.TELEGRAM_POOL_TIMEOUT)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("downloads", downloads))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("status", status))

    # Обработчик callback запросов от inline кнопок
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Отслеживаем, кто добавил бота в группу, чтобы показывать пользователю только его группы.
    application.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Обработчик сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    # Периодическая очистка (каждый час)
    application.job_queue.run_repeating(cleanup_job, interval=3600, first=60)  # 1 час  # Первый запуск через минуту

    # Запуск
    try:
        if config.MODE == "polling":
            logger.info("Запуск в режиме polling")
            application.run_polling(allowed_updates=Update.ALL_TYPES)
        else:
            logger.warning("Webhook режим пока не реализован, используется polling")
            application.run_polling(allowed_updates=Update.ALL_TYPES)
    except InvalidToken as exc:
        logger.error("BOT_TOKEN отклонен Telegram. Проверьте .env или перевыпустите токен через BotFather.")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
