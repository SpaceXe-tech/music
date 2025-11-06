import asyncio
import os
import re
import json
from typing import Union, Optional

import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch

from config import API_BASE_URL, COOKIES_URL, API_KEY
from DeadlineTech.utils.database import is_on_off
from DeadlineTech.utils.formatters import time_to_seconds

from DeadlineTech.platforms._httpx import (
    fetch_cookies_file,
    download_with_retries,
)


def extract_video_id(link: str) -> str:
    patterns = [
        r'youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=)([0-9A-Za-z_-]{11})',
        r'youtu\.be\/([0-9A-Za-z_-]{11})',
        r'youtube\.com\/(?:playlist\?list=[^&]+&v=|v\/)([0-9A-Za-z_-]{11})',
        r'youtube\.com\/(?:.*\?v=|.*\/)([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    raise ValueError("Invalid YouTube link provided.")


async def fetch_cookies() -> str:
    """Async: fetch cookies.txt via httpx helpers."""
    return await fetch_cookies_file(COOKIES_URL, cookies_dir=os.path.join(os.getcwd(), "cookies"))


async def api_dl(video_id: str, api_key: Optional[str] = API_KEY) -> Optional[str]:
    """
    Async: download MP3 via API gateway using httpx streaming.
    Returns file path if successful else None.
    """
    if not video_id or not isinstance(video_id, str) or len(video_id) != 11:
        return None

    api_url = API_BASE_URL.format(video_id=video_id)
    file_path = os.path.join("downloads", f"{video_id}.mp3")
    if os.path.exists(file_path):
        return file_path

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    return await download_with_retries(api_url, file_path, headers=headers)


async def check_file_size(link):
    async def get_format_info(link):
        cookies_path = await fetch_cookies()
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--cookies", cookies_path,
            "-J",
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return None
        return json.loads(stdout.decode())

    def parse_size(formats):
        total_size = 0
        for format in formats:
            if 'filesize' in format:
                total_size += format['filesize']
        return total_size

    info = await get_format_info(link)
    if info is None:
        return None

    formats = info.get('formats', [])
    if not formats:
        return None

    total_size = parse_size(formats)
    return total_size


async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset: offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
        return title

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            duration = result["duration"]
        return duration

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        cookies_path = await fetch_cookies()
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--cookies", cookies_path,
            "-g",
            "-f",
            "best[height<=?720][width<=?1280]",
            f"{link}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
        else:
            return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        cookies_path = await fetch_cookies()
        playlist = await shell_cmd(
            f"yt-dlp -i --get-id --flat-playlist --cookies {cookies_path} --playlist-end {limit} --skip-download {link}"
        )
        try:
            result = playlist.split("\n")
            for key in result:
                if key == "":
                    result.remove(key)
        except Exception:
            result = []
        return result

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            vidid = result["id"]
            yturl = result["link"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        cookies_path = await fetch_cookies()
        ytdl_opts = {"quiet": True, "cookiefile": cookies_path}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])
                except Exception:
                    continue
                if "dash" not in str(format["format"]).lower():
                    try:
                        format["format"]; format["filesize"]; format["format_id"]; format["ext"]; format["format_note"]
                    except Exception:
                        continue
                    formats_available.append(
                        {
                            "format": format["format"],
                            "filesize": format["filesize"],
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        }
                    )
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        a = VideosSearch(link, limit=10)
        result = (await a.next()).get("result")
        title = result[query_type]["title"]
        duration_min = result[query_type]["duration"]
        vidid = result[query_type]["id"]
        thumbnail = result[query_type]["thumbnails"][0]["url"].split("?")[0]
        return title, duration_min, thumbnail, vidid

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            link = self.base + link
        loop = asyncio.get_running_loop()

        cookies_path = await fetch_cookies()

        # common opts shared with executor-bound ytdlp tasks
        common_opts = {
            "quiet": True,
            "no_warnings": True,
            "geo_bypass": True,
            "geo_bypass_country": "IN",
            "nocheckcertificate": True,
            "cookiefile": cookies_path,
            "concurrent_fragment_downloads": 8,
        }

        # ---- helpers run in executor (blocking ytdlp) ----
        def _video_dl():
            ydl_optssx = {
                **common_opts,
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "merge_output_format": "mp4",
                "prefer_ffmpeg": True,
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            info = x.extract_info(link, download=False)
            xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                return xyz
            x.download([link])
            return xyz

        def _song_video_dl():
            formats = f"{format_id}+140"
            fpath = f"downloads/{title}"
            ydl_optssx = {
                **common_opts,
                "format": formats,
                "outtmpl": fpath,
                "merge_output_format": "mp4",
                "prefer_ffmpeg": True,
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])
            return f"{fpath}.mp4"

        def _song_audio_dl():
            fpath = f"downloads/{title}.%(ext)s"
            ydl_optssx = {
                **common_opts,
                "format": format_id,
                "outtmpl": fpath,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                "prefer_ffmpeg": True,
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])
            return f"{fpath.split('%(ext)s')[0]}.mp3"

        # ---- main logic ----
        if songvideo:
            await loop.run_in_executor(None, _song_video_dl)
            fpath = f"downloads/{title}.mp4"
            return fpath
        elif songaudio:
            await loop.run_in_executor(None, _song_audio_dl)
            fpath = f"downloads/{title}.mp3"
            return fpath
        elif video:
            file_size = await check_file_size(link)
            if file_size and file_size / (1024 * 1024) > 500:
                # Stream URL for large videos (no local file)
                proc = await asyncio.create_subprocess_exec(
                    "yt-dlp",
                    "--cookies", cookies_path,
                    "-g",
                    "-f",
                    "best[height<=?720][width<=?1280]",
                    f"{link}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if stdout:
                    downloaded_file = stdout.decode().split("\n")[0]
                    direct = False
                else:
                    return None
            else:
                # Download as file for smaller sizes
                direct = True
                downloaded_file = await loop.run_in_executor(None, _video_dl)
            return downloaded_file, direct
        else:
            # AUDIO: try API first (async httpx). If it fails, fall back to ytdlp (executor)
            try:
                sexid = extract_video_id(link)
            except Exception:
                sexid = None

            if sexid:
                api_path = await api_dl(sexid, API_KEY)
                if api_path:
                    return api_path, True

            # Fallback to ytdlp bestaudio
            def _audio_dl():
                ydl_optssx = {
                    **common_opts,
                    "format": "bestaudio/best",
                    "outtmpl": "downloads/%(id)s.%(ext)s",
                }
                x = yt_dlp.YoutubeDL(ydl_optssx)
                info = x.extract_info(link, download=False)
                xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
                if os.path.exists(xyz):
                    return xyz
                x.download([link])
                return xyz

            downloaded_file = await loop.run_in_executor(None, _audio_dl)
            return downloaded_file, True
