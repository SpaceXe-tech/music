from pyrogram.enums import ParseMode

from DeadlineTech import app
from DeadlineTech.utils.database import is_on_off
from DeadlineTech.misc import SUDOERS
from config import LOGGER_ID


async def play_logs(message, streamtype):
    if not await is_on_off(2):
        return

    if message.from_user.id in SUDOERS:
        return

    log_text = f"""
<b>{app.mention} • Playback Log</b>
────────────────────

<b>Chat:</b> {message.chat.title or 'Private Chat'}
<b>Chat ID:</b> <code>{message.chat.id}</code>
<b>Username:</b> @{message.chat.username or 'N/A'}

<b>User:</b> {message.from_user.mention}
<b>User ID:</b> <code>{message.from_user.id}</code>
<b>Handle:</b> @{message.from_user.username or 'N/A'}

<b>Query:</b> {message.text.split(None, 1)[1]}
<b>Stream Type:</b> {streamtype}
────────────────────
"""

    if message.chat.id != LOGGER_ID:
        try:
            await app.send_message(
                chat_id=LOGGER_ID,
                text=log_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except:
            pass
