import asyncio
import os
import re
import json
from typing import Union, Optional, Tuple

import yt_dlp
import httpx
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch

from config import API_BASE_URL, COOKIES_URL, API_KEY
from DeadlineTech.utils.database import is_on_off
from DeadlineTech.utils.formatters import time_to_seconds
from DeadlineTech.platforms._httpx import fetch_cookies_file, download_with_retries



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
    return await fetch_cookies_file(COOKIES_URL, cookies_dir=os.path.join(os.getcwd(), "cookies"))


async def check_file_size(link: str) -> Optional[int]:
    async def get_format_info(link: str) -> Optional[dict]:
        cookies_path = await fetch_cookies()
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--cookies", cookies_path,
            "-J",
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        try:
            return json.loads(stdout.decode())
        except Exception:
            return None

    def parse_size(formats) -> int:
        total_size = 0
        for f in formats or []:
            if 'filesize' in f and isinstance(f['filesize'], int):
                total_size += f['filesize']
        return total_size

    info = await get_format_info(link)
    if not info:
        return None
    return parse_size(info.get('formats', []))


async def shell_cmd(cmd: str) -> str:
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


# -------------------------
# Core API
# -------------------------

class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    # ---- normalization helpers to avoid "str + NoneType" ----
    def _normalize_watch_link(self, link: Optional[str], videoid: Union[bool, str, None]) -> str:
        if isinstance(videoid, str) and len(videoid) == 11:
            return self.base + videoid
        if link:
            return link
        raise ValueError("Missing YouTube link or 11-char video id.")

    def _normalize_playlist_link(self, link: Optional[str], pl_id: Union[bool, str, None]) -> str:
        if isinstance(pl_id, str) and pl_id:
            return self.listbase + pl_id
        if link:
            return link
        raise ValueError("Missing playlist link or playlist id.")

    async def exists(self, link: Optional[str], videoid: Union[bool, str] = None):
        try:
            link = self._normalize_watch_link(link, videoid)
        except ValueError:
            return False
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
                        text = (message.text or message.caption) or ""
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset: offset + length]

    async def details(self, link: Optional[str], videoid: Union[bool, str] = None):
        link = self._normalize_watch_link(link, videoid)
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result.get("title")
            duration_min = result.get("duration")
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result.get("id")
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: Optional[str], videoid: Union[bool, str] = None):
        link = self._normalize_watch_link(link, videoid)
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
        return title

    async def duration(self, link: Optional[str], videoid: Union[bool, str] = None):
        link = self._normalize_watch_link(link, videoid)
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            duration = result["duration"]
        return duration

    async def thumbnail(self, link: Optional[str], videoid: Union[bool, str] = None):
        link = self._normalize_watch_link(link, videoid)
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail

    async def video(self, link: Optional[str], videoid: Union[bool, str] = None) -> Tuple[int, str]:
        link = self._normalize_watch_link(link, videoid)
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

    async def playlist(self, link: Optional[str], limit: int, user_id, videoid: Union[bool, str] = None):
        link = self._normalize_playlist_link(link, videoid)
        if "&" in link:
            link = link.split("&")[0]
        cookies_path = await fetch_cookies()
        playlist = await shell_cmd(
            f"yt-dlp -i --get-id --flat-playlist --cookies {cookies_path} --playlist-end {limit} --skip-download {link}"
        )
        try:
            result = playlist.split("\n")
            result = [x for x in result if x]
        except Exception:
            result = []
        return result

    async def track(self, link: Optional[str], videoid: Union[bool, str] = None):
        link = self._normalize_watch_link(link, videoid)
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

    async def formats(self, link: Optional[str], videoid: Union[bool, str] = None):
        link = self._normalize_watch_link(link, videoid)
        if "&" in link:
            link = link.split("&")[0]
        cookies_path = await fetch_cookies()
        ytdl_opts = {"quiet": True, "cookiefile": cookies_path}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for fmt in r.get("formats", []):
                try:
                    str(fmt.get("format"))
                except Exception:
                    continue
                if "dash" in str(fmt.get("format", "")).lower():
                    continue
                needed = ("format", "filesize", "format_id", "ext", "format_note")
                if not all(k in fmt for k in needed):
                    continue
                formats_available.append(
                    {
                        "format": fmt["format"],
                        "filesize": fmt["filesize"],
                        "format_id": fmt["format_id"],
                        "ext": fmt["ext"],
                        "format_note": fmt["format_note"],
                        "yturl": link,
                    }
                )
        return formats_available, link

    async def slider(self, link: Optional[str], query_type: int, videoid: Union[bool, str] = None):
        link = self._normalize_watch_link(link, videoid)
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
        link: Optional[str],
        mystic,  # kept for signature 
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> Union[str, Tuple[str, bool], None]:
        os.makedirs("downloads", exist_ok=True)

        # Normalize watch link early; return None if neither link nor id provided
        try:
            link = self._normalize_watch_link(link, videoid)
        except ValueError:
            return None

        loop = asyncio.get_running_loop()
        cookies_path = await fetch_cookies()

        # Common yt-dlp opts
        common_opts = {
            "quiet": True,
            "no_warnings": True,
            "geo_bypass": True,
            "geo_bypass_country": "IN",
            "nocheckcertificate": True,
            "cookiefile": cookies_path,
            "concurrent_fragment_downloads": 8,
            "prefer_ffmpeg": True,
        }

        def video_dl():
            ydl_optssx = {
                **common_opts,
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "merge_output_format": "mp4",
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            info = x.extract_info(link, download=False)
            xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                return xyz
            x.download([link])
            return xyz

        def song_video_dl():
            formats = f"{format_id}+140"
            fpath = f"downloads/{title}"
            ydl_optssx = {
                **common_opts,
                "format": formats,
                "outtmpl": fpath,
                "merge_output_format": "mp4",
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])
            return f"{fpath}.mp4"

        def song_audio_dl():
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
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])
            return f"{fpath.split('%(ext)s')[0]}.mp3"

        def audio_dl():
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


        if songvideo:
            await loop.run_in_executor(None, song_video_dl)
            fpath = f"downloads/{title}.mp4"
            return fpath

        if songaudio:
            await loop.run_in_executor(None, song_audio_dl)
            fpath = f"downloads/{title}.mp3"
            return fpath

        if video:
            file_size = await check_file_size(link)
            if file_size and file_size / (1024 * 1024) > 500:
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
                stdout, _ = await proc.communicate()
                if stdout:
                    downloaded_file = stdout.decode().split("\n")[0]
                    direct = False
                else:
                    return None
            else:
                direct = True
                downloaded_file = await loop.run_in_executor(None, video_dl)
            return downloaded_file, direct

        try:
            vid = None
            try:
                vid = extract_video_id(link)
            except Exception:
                pass
            if vid:
                api_url = f"{API_BASE_URL.rstrip('/')}/mp3?id={vid}"
                headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else None
                async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True) as client:
                    resp = await client.get(api_url, headers=headers or {})
                    if resp.status_code == 200:
                        data = resp.json()
                        dl = data.get("downloadUrl")
                        if dl:
                            out_path = os.path.join("downloads", f"{vid}.mp3")
                            if not os.path.exists(out_path):
                                path = await download_with_retries(dl, out_path, headers=None)
                                if not path:
                                    pass
                            if os.path.exists(out_path):
                                return out_path, True
        except Exception:
            pass

        direct = True
        downloaded_file = await loop.run_in_executor(None, audio_dl)
        return downloaded_file, direct
