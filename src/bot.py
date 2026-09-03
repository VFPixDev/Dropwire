import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram import BaseMiddleware
from aiogram.types import BotCommand, CallbackQuery, ChatMemberUpdated, ErrorEvent, InlineQuery, Message
from aiogram.utils.token import TokenValidationError

from src.config import config
from src.handlers.callbacks import handle_callback_query
from src.handlers.chat_members import handle_my_chat_member
from src.handlers.commands import admin_panel, downloads, help_command, settings, start
from src.handlers.inline import handle_inline_query
from src.handlers.delete import delete_card
from src.handlers.messages import handle_message
from src.media.cleanup import cleanup_temp_files
from src.services.database import Database
from src.services.download_queue import DownloadQueue
from src.services.youtube_downloader import YtDlpDownloader
from src.services.settings import GLOBAL_OWNER_ID, is_admin
from src.telegram_runtime import (
    ApplicationState,
    BotAdapter,
    HandlerContext,
    callback_update,
    inline_update,
    member_update,
    message_update,
)
from src.utils.rate_limit import rate_limiter

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, config.LOG_LEVEL),
)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class ConcurrentUpdateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self._semaphore = asyncio.Semaphore(self.limit)

    async def __call__(self, handler, event, data):
        async with self._semaphore:
            return await handler(event, data)


async def cleanup_job(context: HandlerContext) -> None:
    """Periodically clean temporary files and stale in-memory state."""
    logger.info("Запуск периодической очистки...")
    cleanup_temp_files(max_age_seconds=3600)
    rate_limiter.cleanup_old_entries(max_age=3600)
    downloader = context.application.bot_data.get("youtube_downloader")
    if isinstance(downloader, YtDlpDownloader):
        await downloader.cleanup_stale_files(config.DOWNLOAD_FILE_RETENTION_HOURS * 3600)
    database = context.application.bot_data.get("database")
    if isinstance(database, Database):
        await database.prune_deliveries(max_age_hours=48)
    logger.info("Периодическая очистка завершена")


async def _cleanup_loop(context: HandlerContext) -> None:
    await asyncio.sleep(60)
    while True:
        try:
            await cleanup_job(context)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка периодической очистки")
        await asyncio.sleep(3600)


async def post_init(bot: BotAdapter, application: ApplicationState) -> None:
    database = Database(config.DATABASE_PATH)
    await database.connect()
    await database.init_schema()
    interrupted = await database.fail_interrupted_downloads()
    if interrupted:
        logger.warning("После перезапуска помечено неудачными загрузок: %s", interrupted)

    application.bot_data["database"] = database
    application.bot_data["download_queue"] = DownloadQueue(config.MAX_CONCURRENT_DOWNLOADS)
    application.bot_data["youtube_downloader"] = YtDlpDownloader(config.DOWNLOAD_DIR)

    me = await bot.get_me()
    bot.username = me.username
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="settings", description="Настройки"),
                BotCommand(command="downloads", description="Мои загрузки"),
                BotCommand(command="help", description="Справка"),
                BotCommand(command="del", description="Удалить карточку ответом в группе"),
            ]
        )
    except TelegramNetworkError as exc:
        logger.warning("Не удалось зарегистрировать команды Telegram: %s", exc)

    if not config.BOT_ADMIN_IDS:
        logger.warning("BOT_ADMIN_IDS не задан: глобальные настройки и админ-панель заблокированы")
    if not config.WEB_BASE_URL:
        logger.warning("WEB_BASE_URL не задан: YouTube-загрузки через браузер отключены")

    logger.info("Очистка временных файлов при старте...")
    cleanup_temp_files()
    logger.info("%s запущен и готов к работе", config.APP_NAME)


async def post_shutdown(application: ApplicationState) -> None:
    database = application.bot_data.get("database")
    if isinstance(database, Database):
        await database.close()


def _command_args(message: Message) -> list[str]:
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].split() if len(parts) > 1 else []


def build_dispatcher(bot: BotAdapter, application: ApplicationState) -> Dispatcher:
    dispatcher = Dispatcher()
    concurrency = ConcurrentUpdateLimitMiddleware(config.MAX_CONCURRENT_UPDATES)
    dispatcher.update.outer_middleware(concurrency)
    dispatcher["max_concurrent_updates"] = concurrency.limit

    def context(args: list[str] | None = None) -> HandlerContext:
        return HandlerContext(bot=bot, application=application, args=args or [])

    async def on_start(message: Message) -> None:
        await start(message_update(message, bot), context(_command_args(message)))

    async def on_help(message: Message) -> None:
        await help_command(message_update(message, bot), context())

    async def on_settings(message: Message) -> None:
        await settings(message_update(message, bot), context())

    async def on_downloads(message: Message) -> None:
        await downloads(message_update(message, bot), context())

    async def on_admin(message: Message) -> None:
        await admin_panel(message_update(message, bot), context())

    async def on_delete(message: Message) -> None:
        await delete_card(message, bot, application)

    async def on_callback(query: CallbackQuery) -> None:
        await handle_callback_query(callback_update(query, bot), context())

    async def on_inline(query: InlineQuery) -> None:
        await handle_inline_query(inline_update(query, bot), context())

    async def on_member(event: ChatMemberUpdated) -> None:
        await handle_my_chat_member(member_update(event, bot), context())

    async def on_message(message: Message) -> None:
        await handle_message(message_update(message, bot), context())

    async def is_pending_cache_binding(message: Message) -> bool:
        pending = application.bot_data.get("pending_cache_bindings")
        return bool(message.from_user and isinstance(pending, set) and message.from_user.id in pending)

    async def on_cache_binding(message: Message) -> None:
        pending = application.bot_data.get("pending_cache_bindings")
        if message.from_user is None or not isinstance(pending, set):
            return
        user_id = message.from_user.id
        if not is_admin(user_id) or message.chat.type != "private":
            pending.discard(user_id)
            return

        origin = message.forward_origin
        channel = getattr(origin, "chat", None)
        if channel is None or channel.type != "channel":
            await message.answer("Нужна пересылка именно из канала. Попробуйте ещё раз.")
            return
        try:
            member = await bot.get_chat_member(chat_id=channel.id, user_id=bot.id)
        except TelegramAPIError:
            await message.answer("Не удалось открыть канал. Добавьте бота в администраторы и повторите.")
            return

        status = getattr(member.status, "value", member.status)
        can_post = getattr(member, "can_post_messages", True)
        can_delete = getattr(member, "can_delete_messages", True)
        if (
            str(status) not in {"administrator", "creator", "owner"}
            or can_post is False
            or can_delete is False
        ):
            await message.answer("Боту нужны права публикации и удаления сообщений в канале-кэше.")
            return

        database = application.bot_data.get("database")
        if not isinstance(database, Database):
            await message.answer("База данных пока недоступна.")
            return
        await database.set_setting("global", GLOBAL_OWNER_ID, "inline_cache_chat_id", str(channel.id))
        pending.discard(user_id)
        await message.answer(f"Технический медиакэш подключён: <code>{channel.id}</code>.")

    async def on_error(event: ErrorEvent) -> None:
        error = event.exception
        if isinstance(error, TelegramNetworkError):
            logger.warning("Сетевая ошибка Telegram без автоматического повтора: %s", error)
            return
        logger.error(
            "Необработанная ошибка update_id=%s error_type=%s",
            event.update.update_id,
            type(error).__name__,
            exc_info=(type(error), error, error.__traceback__),
        )

    dispatcher.message.register(on_start, Command("start"))
    dispatcher.message.register(on_help, Command("help"))
    dispatcher.message.register(on_settings, Command("settings"))
    dispatcher.message.register(on_downloads, Command("downloads"))
    dispatcher.message.register(on_admin, Command("admin"))
    dispatcher.message.register(on_delete, Command("del"))
    dispatcher.message.register(on_cache_binding, is_pending_cache_binding)
    dispatcher.callback_query.register(on_callback)
    dispatcher.inline_query.register(on_inline)
    dispatcher.my_chat_member.register(on_member)
    dispatcher.message.register(on_message, F.text & ~F.text.startswith("/"))
    dispatcher.errors.register(on_error)
    return dispatcher


async def run() -> None:
    raw_bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot = BotAdapter(raw_bot)
    application = ApplicationState()
    cleanup_task: asyncio.Task | None = None

    try:
        await post_init(bot, application)
        dispatcher = build_dispatcher(bot, application)
        handler_context = HandlerContext(bot=bot, application=application)
        cleanup_task = asyncio.create_task(_cleanup_loop(handler_context), name="dropwire-cleanup")
        logger.info("Запуск в режиме polling")
        await dispatcher.start_polling(raw_bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        if cleanup_task is not None:
            cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup_task
        await post_shutdown(application)
        await raw_bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (TokenValidationError, TelegramUnauthorizedError) as exc:
        logger.error("BOT_TOKEN отклонен Telegram. Проверьте .env или перевыпустите токен через BotFather.")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
