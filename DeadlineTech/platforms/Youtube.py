import asyncio
import os
import re
import json
import logging
from typing import Optional, Tuple, Union

import httpx
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch

from config import API_BASE_URL, COOKIES_URL
from DeadlineTech.utils.formatters import time_to_seconds
from DeadlineTech.platforms._httpx import fetch_to_path, fetch_cookies_file, DOWNLOAD_DIR

# --- logging (API downloads only) ---
logger = logging.getLogger(__name__)
# Leave config to app; if you want defaults during local runs, uncomment:
# logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def extract_video_id(link: str) -> str:
    patterns = [
        r'youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=)([0-9A-Za-z_-]{11})',
        r'youtu\.be\/([0-9A-Za-z_-]{11})',
        r'youtube\.com\/(?:playlist\?list=[^&]+&v=|v\/)([0-9A-Za-z_-]{11})',
        r'youtube\.com\/(?:.*\?v=|.*\/)([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    raise ValueError("Invalid YouTube link provided.")


async def fetch_cookies() -> str:
    return await fetch_cookies_file(COOKIES_URL, cookies_dir="cookies")


def _api_base() -> str:
    return API_BASE_URL.rstrip("/")


async def _fetch_json(url: str, timeout: float = 40.0) -> Optional[dict]:
    # logging limited to API path fetches
    logger.debug("API GET %s", url)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            logger.debug("API GET %s -> %s", url, resp.status_code)
            if resp.status_code >= 400:
                # include a tiny slice of body for diagnostics
                body = resp.text[:256] if resp.text else ""
                logger.warning("API error %s for %s; body=%r", resp.status_code, url, body)
                return None
            try:
                data = resp.json()
                logger.debug("API JSON parsed for %s (keys=%s)", url, list(data.keys()) if isinstance(data, dict) else type(data))
                return data
            except ValueError:
                logger.error("API invalid JSON from %s", url)
                return None
    except httpx.HTTPError as e:
        logger.error("API HTTP exception for %s: %s", url, e)
        return None


async def api_audio_download(video_id: str) -> Optional[str]:
    # logging only for API-backed audio path
    if not video_id or not isinstance(video_id, str) or len(video_id) != 11:
        logger.warning("api_audio_download: invalid video_id=%r", video_id)
        return None

    dest_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    if os.path.exists(dest_path):
        logger.info("api_audio_download: cache hit %s", dest_path)
        return dest_path

    url = f"{_api_base()}/mp3?id={video_id}"
    logger.info("api_audio_download: requesting %s", url)
    data = await _fetch_json(url)
    if not data:
        logger.warning("api_audio_download: no data for %s", video_id)
        return None
    if "downloadUrl" not in data:
        logger.warning("api_audio_download: missing downloadUrl in response for %s; keys=%s", video_id, list(data.keys()))
        return None

    dl_url = data["downloadUrl"]
    logger.debug("api_audio_download: fetching to path from %s", dl_url)
    try:
        out = await fetch_to_path(dl_url, DOWNLOAD_DIR, f"{video_id}.mp3")
        if out:
            logger.info("api_audio_download: saved -> %s", out)
        else:
            logger.error("api_audio_download: fetch_to_path returned None for %s", video_id)
        return out
    except Exception as e:
        logger.exception("api_audio_download: failed to fetch %s -> %s", dl_url, e)
        return None


async def api_video_download(video_id: str, format_str: str = "720") -> Optional[str]:
    # logging only for API-backed video path
    if not video_id or not isinstance(video_id, str) or len(video_id) != 11:
        logger.warning("api_video_download: invalid video_id=%r", video_id)
        return None

    dest_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    if os.path.exists(dest_path):
        logger.info("api_video_download: cache hit %s", dest_path)
        return dest_path

    url = f"{_api_base()}/download?id={video_id}&format={format_str}"
    logger.info("api_video_download: requesting %s", url)
    data = await _fetch_json(url)
    if not data:
        logger.warning("api_video_download: no data for %s", video_id)
        return None
    if "downloadUrl" not in data:
        logger.warning("api_video_download: missing downloadUrl in response for %s; keys=%s", video_id, list(data.keys()))
        return None

    dl_url = data["downloadUrl"]
    logger.debug("api_video_download: fetching to path from %s", dl_url)
    try:
        out = await fetch_to_path(dl_url, DOWNLOAD_DIR, f"{video_id}.mp4")
        if out:
            logger.info("api_video_download: saved -> %s", out)
        else:
            logger.error("api_video_download: fetch_to_path returned None for %s", video_id)
        return out
    except Exception as e:
        logger.exception("api_video_download: failed to fetch %s -> %s", dl_url, e)
        return None


async def check_file_size(link: str) -> Optional[int]:
    async def get_format_info(link: str) -> Optional[dict]:
        cookies_path = await fetch_cookies()
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--cookies",
            cookies_path,
            "-J",
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return None
        try:
            return json.loads(stdout.decode())
        except Exception:
            return None

    def parse_size(formats):
        total = 0
        for fmt in formats or []:
            if "filesize" in fmt and isinstance(fmt["filesize"], int):
                total += fmt["filesize"]
        return total or None

    info = await get_format_info(link)
    if not info:
        return None
    return parse_size(info.get("formats", []))


async def shell_cmd(cmd: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if err:
        if "unavailable videos are hidden" in (err.decode("utf-8")).lower():
            return out.decode("utf-8")
        return err.decode("utf-8")
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

    async def video(self, link: str, videoid: Union[bool, str] = None) -> Tuple[int, str]:
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        cookies_path = await fetch_cookies()
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--cookies",
            cookies_path,
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
            f'yt-dlp -i --get-id --flat-playlist --cookies "{cookies_path}" --playlist-end {limit} --skip-download "{link}"'
        )
        try:
            result = [x for x in playlist.split("\n") if x]
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
            for format in r.get("formats", []):
                try:
                    str(format.get("format"))
                except Exception:
                    continue
                if "dash" not in str(format.get("format", "")).lower():
                    try:
                        _ = (
                            format["format"],
                            format["filesize"],
                            format["format_id"],
                            format["ext"],
                            format["format_note"],
                        )
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
    ) -> Union[str, Tuple[str, bool]]:
        if videoid:
            link = self.base + link
        loop = asyncio.get_running_loop()

        def common_opts(cookiefile_path: str):
            return {
                "quiet": True,
                "no_warnings": True,
                "geo_bypass": True,
                "geo_bypass_country": "IN",
                "nocheckcertificate": True,
                "cookiefile": cookiefile_path,
                "concurrent_fragment_downloads": 8,
            }

        def _video_dl(cookiefile_path: str) -> str:
            ydl_optssx = {
                **common_opts(cookiefile_path),
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
                "merge_output_format": "mp4",
                "prefer_ffmpeg": True,
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            info = x.extract_info(link, download=False)
            xyz = os.path.join(DOWNLOAD_DIR, f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                return xyz
            x.download([link])
            return xyz

        def _song_video_dl(cookiefile_path: str) -> str:
            formats = f"{format_id}+140"
            fpath = os.path.join(DOWNLOAD_DIR, f"{title}")
            ydl_optssx = {
                **common_opts(cookiefile_path),
                "format": formats,
                "outtmpl": fpath,
                "merge_output_format": "mp4",
                "prefer_ffmpeg": True,
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])
            return f"{fpath}.mp4"

        def _song_audio_dl(cookiefile_path: str) -> str:
            fpath = os.path.join(DOWNLOAD_DIR, f"{title}.%(ext)s")
            ydl_optssx = {
                **common_opts(cookiefile_path),
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

        cookiefile_path = await fetch_cookies()

        if songvideo:
            await loop.run_in_executor(None, _song_video_dl, cookiefile_path)
            return os.path.join(DOWNLOAD_DIR, f"{title}.mp4")

        if songaudio:
            await loop.run_in_executor(None, _song_audio_dl, cookiefile_path)
            return os.path.join(DOWNLOAD_DIR, f"{title}.mp3")

        if video:
            try:
                sexid = extract_video_id(link)
                api_path = await api_video_download(sexid, format_str="720")
                if api_path:
                    return api_path, True
            except Exception:
                pass
            file_size = await check_file_size(link)
            if file_size and file_size / (1024 * 1024) > 500:
                proc = await asyncio.create_subprocess_exec(
                    "yt-dlp",
                    "--cookies",
                    cookiefile_path,
                    "-g",
                    "-f",
                    "best[height<=?720][width<=?1280]",
                    f"{link}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if stdout:
                    direct_url = stdout.decode().split("\n")[0]
                    return direct_url, False
                return None
            else:
                downloaded_file = await loop.run_in_executor(None, _video_dl, cookiefile_path)
                return downloaded_file, True

        try:
            sexid = extract_video_id(link)
            api_path = await api_audio_download(sexid)
            if api_path:
                return api_path, True
        except Exception:
            pass

        def _audio_dl(cookiefile_path: str) -> str:
            ydl_optssx = {
                **common_opts(cookiefile_path),
                "format": "bestaudio/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            info = x.extract_info(link, download=False)
            xyz = os.path.join(DOWNLOAD_DIR, f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                return xyz
            x.download([link])
            return xyz

        downloaded_file = await loop.run_in_executor(None, _audio_dl, cookiefile_path)
        return downloaded_file, True
