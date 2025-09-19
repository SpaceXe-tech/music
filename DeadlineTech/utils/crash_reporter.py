# Powered By DeadlineTech

import asyncio
from traceback import format_exc
from pyrogram.errors import RPCError

from DeadlineTech import app
from config import LOGGER_ID  # Logger group ID


IGNORED_ERRORS = [
    "The userbot there isn't in a group call",
    "Chat is not active",  # Matches "Admin Blocked ... Chat is not active"
]


async def notify_logger_about_crash(error: Exception):
    error_str = str(error)

    # Skip noisy/ignored errors
    if any(skip in error_str for skip in IGNORED_ERRORS):
        return

    error_text = (
        "🚨 <b><u>Bot Crash Alert</u></b>\n\n"
        f"<b>Error:</b> <code>{error_str}</code>\n\n"
        f"<b>Traceback:</b>\n<pre>{format_exc()}</pre>"
    )
    try:
        await app.send_message(
            chat_id=LOGGER_ID,
            text=error_text,
            disable_web_page_preview=True
        )
    except RPCError:
        pass


def logger_alert_on_crash(func):
    async def wrapper(client, *args, **kwargs):
        try:
            return await func(client, *args, **kwargs)
        except Exception as e:
            await notify_logger_about_crash(e)
            raise  # Re-raise if you want the higher-level handler to still see it
    return wrapper


def setup_global_exception_handler():
    loop = asyncio.get_event_loop()

    def handle_exception(loop, context):
        error = context.get("exception")
        if error:
            asyncio.create_task(notify_logger_about_crash(error))

    loop.set_exception_handler(handle_exception)
