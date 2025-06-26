# ==========================================================
# 🔒 All Rights Reserved © Team DeadlineTech
# 📁 This file is part of the DeadlineTech Project.
# ==========================================================

import os
import re
import asyncio
import requests
import logging
import urllib.request
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ChatAction
from youtubesearchpython.__future__ import VideosSearch
from config import API_KEY, API_BASE_URL, COOKIES_URL

# 📝 Logging Setup
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[
        logging.FileHandler("logs/music_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

MIN_FILE_SIZE = 51200
DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def extract_video_id(link: str) -> str | None:
    patterns = [
        r'youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=)([0-9A-Za-z_-]{11})',
        r'youtu\.be\/([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    return None

def download_thumbnail(video_id: str) -> str | None:
    try:
        url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        path = os.path.join(DOWNLOADS_DIR, f"{video_id}.jpg")
        urllib.request.urlretrieve(url, path)
        return path
    except Exception as e:
        logger.warning(f"Thumbnail error: {e}")
        return None

def cookie_txt_file():
    # Fetch cookies from COOKIES_URL defined in config.py
    cookies_file_path = os.path.join("cookies", "cookies.txt")
    os.makedirs("cookies", exist_ok=True)

    try:
        response = requests.get(COOKIES_URL, timeout=10) 
        if response.status_code == 200:
            with open(cookies_file_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"Cookies downloaded successfully to {cookies_file_path}")
        else:
            raise FileNotFoundError(f"Failed to fetch cookies from {COOKIES_URL}. Status: {response.status_code}")
    except requests.RequestException as e:
        raise FileNotFoundError(f"Error fetching cookies from {COOKIES_URL}: {e}")

    # Log the chosen file
    with open(os.path.join("cookies", "logs.csv"), 'a') as file:
        file.write(f"Chosen File: {cookies_file_path}\n")

    return cookies_file_path

def api_dl(video_id: str) -> str | None:
    # Construct API URL using API_BASE_URL from config.py
    api_url = f"{API_BASE_URL}?direct&id={video_id}"
    if API_KEY:  # Append API key only if defined
        api_url += f"&key={API_KEY}"
    
    file_path = os.path.join(DOWNLOADS_DIR, f"{video_id}.mp3")

    # Check if already downloaded
    if os.path.exists(file_path):
        logger.info(f"Song {file_path} already exists. Skipping download ✅")
        return file_path

    try:
        response = requests.get(api_url, stream=True, timeout=15)
        if response.status_code == 200:
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if os.path.getsize(file_path) < MIN_FILE_SIZE:
                logger.warning(f"Downloaded file is too small ({os.path.getsize(file_path)} bytes). Removing.")
                os.remove(file_path)
                return None
            logger.info(f"Song Downloaded Successfully ✅ {file_path} ({os.path.getsize(file_path)} bytes)")
            return file_path
        else:
            logger.error(f"Failed to download {video_id}. Status: {response.status_code}")
    except Exception as e:
        logger.error(f"API download failed: {e}")

    # Fallback to yt-dlp
    logger.info(f"API download failed for {video_id}. Falling back to yt-dlp.")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOADS_DIR, f"{video_id}.%(ext)s"),
        "geo_bypass": True,
        "nocheckcertificate": True,
        "quiet": True,
        "cookiefile": cookie_txt_file(),
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if os.path.exists(file_path):
                logger.info(f"Song {file_path} already exists from yt-dlp cache.")
                return file_path
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            if os.path.exists(file_path):
                if os.path.getsize(file_path) < MIN_FILE_SIZE:
                    logger.warning(f"yt-dlp downloaded file is too small ({os.path.getsize(file_path)} bytes). Removing.")
                    os.remove(file_path)
                    return None
                logger.info(f"Song downloaded via yt-dlp successfully: {file_path}")
                return file_path
            else:
                logger.error(f"yt-dlp failed to download {video_id}: File not found.")
                return None
    except Exception as e:
        logger.error(f"yt-dlp download failed for {video_id}: {e}")
        return None

def parse_duration(duration: str) -> int:
    parts = list(map(int, duration.split(":")))
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m = 0, parts[0]
        s = parts[1]
    else:
        return int(parts[0])
    return h * 3600 + m * 60 + s

@app.on_message(filters.command(["song", "music"]))
async def song_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("🎧 <b>𝖴𝗌𝖺𝗀𝖾:</b> <code>/music [song name or YouTube link]</code>")

    query = message.text.split(None, 1)[1].strip()
    video_id = extract_video_id(query)

    if video_id:
        msg = await message.reply_text("🎼 𝖥𝖾𝗍𝖼𝗁𝗂𝗇𝗀 𝗍𝗋𝖺𝖼𝗄...")
        await send_audio(client, msg, video_id)
    else:
        try:
            results = (await VideosSearch(query, limit=5).next()).get('result', [])
            if not results:
                return await message.reply_text("❌ 𝖭𝗈 𝗌𝗈𝗇𝗀𝗌 𝖿𝗈𝗎𝗇𝖽.")
            buttons = [[
                InlineKeyboardButton(f"🎙 {video['title'][:30]}{'...' if len(video['title']) > 30 else ''}",
                                     callback_data=f"dl_{video['id']}")
            ] for video in results]
            await message.reply_text(
                "🎧 𝖲𝖾𝗅𝖾𝖼𝗍 𝖺 𝗌𝗈𝗇𝗀:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception as e:
            logger.error(f"Search error: {e}")
            await message.reply_text("⚠️ 𝖤𝗋𝗋𝗈𝗋 𝗐𝗁𝗂𝗅𝖾 𝗌𝖾𝖺𝗋𝖼𝗁𝗂𝗇𝗀 Try Searching Case Sensitive Name of Song.")

@app.on_callback_query(filters.regex(r"^dl_(.+)$"))
async def callback_handler(client: Client, cq: CallbackQuery):
    video_id = cq.data.split("_", 1)[1]
    await cq.answer()
    await cq.message.edit("⏳ 𝖯𝗋𝗈𝖼𝖾𝗌𝗌𝗂𝗇𝗀 𝗍𝗋𝖺𝖼𝗄...")
    await send_audio(client, cq.message, video_id)

async def send_audio(client: Client, message: Message, video_id: str):
    try:
        result = (await VideosSearch(video_id, limit=1).next())["result"][0]
        title = result.get("title", "Unknown")
        duration_str = result.get("duration", "0:00")
        duration = parse_duration(duration_str)
        url = result.get("link")
    except Exception as e:
        logger.warning(f"Metadata error: {e}")
        title, duration_str, duration, url = "Unknown", "0:00", 0, None

    thumb_path = await asyncio.to_thread(download_thumbnail, video_id)
    file_path = await asyncio.to_thread(api_dl, video_id)

    if not file_path:
        return await message.edit("❌ 𝖢𝗈𝗎𝗅𝖽𝗇’𝗍 𝖽𝗈𝗐𝗇𝗅𝗈𝖺𝖽 𝗍𝗁𝖾 𝗌𝗈𝗇𝗀...")

    await message.edit("🎶 𝖲𝖾𝗇𝖽𝗂𝗇𝗀 𝗍𝗋𝖺𝖼𝗄...")

    await message.reply_audio(
        audio=file_path,
        title=title,
        performer="Space-X API",
        duration=duration,
        caption=f"📻 <b><a href=\"{url}\">{title}</a></b>\n🕒 <b>Duration:</b> {duration_str}\n🔧 <b>Powered by:</b> <a href=\"https://t.me/BillaSpace\">Space-X</a>",
        thumb=thumb_path if thumb_path else None,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎧 More Music", url="https://t.me/BillaCore")],
            [InlineKeyboardButton("💻 Assoiciated with, url="https://t.me/BillaSpace")]
        ])
)
