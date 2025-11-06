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
from DeadlineTech.platforms._httpx import (
    fetch_cookies_file,
    api_download_audio,
    api_download_video,
    DOWNLOAD_DIR,
)

logger = logging.getLogger(__name__)


def extract_video_id(link: str) -> str:
    logger.info("extract_video_id: input=%r", link)
    patterns = [
        r'youtube.com/(?:embed/|v/|watch\?v=|watch\?.+&v=)([0-9A-Za-z_-]{11})',
        r'youtu.be/([0-9A-Za-z_-]{11})',
        r'youtube.com/(?:playlist\?list=[^&]+&v=|v/)([0-9A-Za-z_-]{11})',
        r'youtube.com/(?:.*?\?v=|/.*/)([0-9A-Za-z_-]{11})',
    ]
    for idx, pattern in enumerate(patterns):
        match = re.search(pattern, link)
        if match:
            vid = match.group(1)
            logger.info("extract_video_id: matched pattern #%s -> %s", idx, vid)
            return vid
    logger.error("extract_video_id: failed for link=%r", link)
    raise ValueError("Invalid YouTube link provided.")


async def fetch_cookies() -> str:
    return await fetch_cookies_file(COOKIES_URL, cookies_dir="cookies")


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
        err_text = err.decode("utf-8").lower()
        if "unavailable videos are hidden" in err_text:
            return out.decode("utf-8")
        return err_text
    return out.decode("utf-8")


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None) -> bool:
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
        if offset is None:
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
            duration_sec = 0 if str(duration_min) == "None" else int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None) -> str:
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["title"]

    async def duration(self, link: str, videoid: Union[bool, str] = None) -> str:
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["duration"]

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None) -> str:
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            return result["thumbnails"][0]["url"].split("?")[0]

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
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
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
            logger.info("download: ytdlp video start link=%s", link)
            x = yt_dlp.YoutubeDL(ydl_optssx)
            info = x.extract_info(link, download=False)
            xyz = os.path.join(DOWNLOAD_DIR, f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                logger.info("download: ytdlp video cached path=%s", xyz)
                return xyz
            x.download([link])
            logger.info("download: ytdlp video saved path=%s", xyz)
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
            logger.info("download: ytdlp songvideo start link=%s format_id=%s", link, format_id)
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])
            logger.info("download: ytdlp songvideo saved path=%s.mp4", fpath)
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
            logger.info("download: ytdlp songaudio start link=%s format_id=%s", link, format_id)
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])
            mp3_path = f"{fpath.split('%(ext)s')[0]}.mp3"
            logger.info("download: ytdlp songaudio saved path=%s", mp3_path)
            return mp3_path

        def _audio_dl(cookiefile_path: str) -> str:
            ydl_optssx = {
                **common_opts(cookiefile_path),
                "format": "bestaudio/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
            }
            logger.info("download: ytdlp audio start link=%s", link)
            x = yt_dlp.YoutubeDL(ydl_optssx)
            info = x.extract_info(link, download=False)
            xyz = os.path.join(DOWNLOAD_DIR, f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                logger.info("download: ytdlp audio cached path=%s", xyz)
                return xyz
            x.download([link])
            logger.info("download: ytdlp audio saved path=%s", xyz)
            return xyz

        cookiefile_path = await fetch_cookies()

        if songvideo:
            logger.info("download: songvideo requested title=%r", title)
            path = await loop.run_in_executor(None, _song_video_dl, cookiefile_path)
            logger.info("download: songvideo done path=%s", path)
            return os.path.join(DOWNLOAD_DIR, f"{title}.mp4")

        if songaudio:
            logger.info("download: songaudio requested title=%r", title)
            path = await loop.run_in_executor(None, _song_audio_dl, cookiefile_path)
            logger.info("download: songaudio done path=%s", path)
            return os.path.join(DOWNLOAD_DIR, f"{title}.mp3")

        if video:
            logger.info("download: video requested link=%s", link)
            try:
                video_id = extract_video_id(link)
                logger.info("download: api video attempt id=%s", video_id)
                api_path = await api_download_video(
                    API_BASE_URL,
                    video_id,
                    format_str="720",
                    download_dir=DOWNLOAD_DIR,
                )
                if api_path:
                    logger.info("download: api video success path=%s", api_path)
                    return api_path, True
                logger.warning("download: api video returned no path id=%s", video_id)
            except Exception as e:
                logger.error("download: api video exception %s", e)

            file_size = await check_file_size(link)
            logger.info("download: probed size bytes=%s", file_size)
            if file_size and file_size / (1024 * 1024) > 500:
                logger.info("download: file large, returning direct url")
                proc = await asyncio.create_subprocess_exec(
                    "yt-dlp",
                    "--cookies",
                    cookiefile_path,
                    "-g",
                    "-f",
                    "best[height<=?720][width<=?1280]",
                    link,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if stdout:
                    direct_url = stdout.decode().split("\n")[0]
                    logger.info("download: direct url generated")
                    return direct_url, False
                logger.error("download: failed to get direct url")
                return None
            else:
                logger.info("download: ytdlp video fallback")
                downloaded_file = await loop.run_in_executor(None, _video_dl, cookiefile_path)
                logger.info("download: ytdlp video fallback done path=%s", downloaded_file)
                return downloaded_file, True

        try:
            video_id = extract_video_id(link)
            logger.info("download: api audio attempt id=%s", video_id)
            api_path = await api_download_audio(
                API_BASE_URL,
                video_id,
                download_dir=DOWNLOAD_DIR,
            )
            if api_path:
                logger.info("download: api audio success path=%s", api_path)
                return api_path, True
            logger.warning("download: api audio returned no path id=%s", video_id)
        except Exception as e:
            logger.error("download: api audio exception %s", e)

        logger.info("download: ytdlp audio fallback")
        downloaded_file = await loop.run_in_executor(None, _audio_dl, cookiefile_path)
        logger.info("download: ytdlp audio fallback done path=%s", downloaded_file)
        return downloaded_file, True
