from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram.enums import ParseMode
from DeadlineTech import app
import config

TEXT = f"""
🔒 **Privacy Policy for Billa Music & Space Bot's !**

Your privacy is important to us. To learn more about how we collect, use, and protect your data, please review our Privacy Policy here: [Privacy Policy](https://graph.org/vTelegraphBot-07-27-37).

If you have any questions or concerns, feel free to reach out us on [support team](https://t.me/BillaCore).
"""

@app.on_message(filters.command("privacy"))
async def privacy(client, message: Message):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Privacy Policy 🧣", url=f"https://graph.org/vTelegraphBot-07-27-37"
                )
            ]
        ]
    )
    await message.reply_text(
        TEXT, 
        reply_markup=keyboard, 
        parse_mode=ParseMode.MARKDOWN, 
        disable_web_page_preview=True
    )
