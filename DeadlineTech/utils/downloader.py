import asyncio
import contextlib
import os
import re
from typing import Dict, Optional, Union
import aiofiles
import httpx
from yt_dlp import YoutubeDL
from config import API_BASE_URL

DOWNLOAD_DIR = "downloads"
CACHE_DIR = "cache"
COOKIE_PATH = "DeadlineTech/cookies.txt"
CHUNK_SIZE = 8 * 1024 * 1024
SEM = asyncio.Semaphore(1)
USE_API = True

_inflight: Dict[str, asyncio.Future] = {}
_inflight_lock = asyncio.Lock()
_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


def extract_video_id(link: str) -> str:
    if "v=" in link:
        return link.split("v=")[-1].split("&")[0]
    return link.split("/")[-1].split("?")[0]


def _cookiefile_path() -> Optional[str]:
    try:
        if COOKIE_PATH and os.path.exists(COOKIE_PATH) and os.path.getsize(COOKIE_PATH) > 0:
            return COOKIE_PATH
    except Exception:
        pass
    return None


def file_exists(video_id: str, ext: str = None) -> Optional[str]:
    exts = [ext] if ext else ("mp3", "m4a", "webm", "mp4")
    for e in exts:
        path = f"{DOWNLOAD_DIR}/{video_id}.{e}"
        if os.path.exists(path):
            return path
    return None


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]+', "_", (name or "").strip())[:200]


def _ytdlp_base_opts() -> Dict[str, Union[str, int, bool]]:
    opts = {
        "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "overwrites": True,
        "continuedl": True,
        "noprogress": True,
        "concurrent_fragment_downloads": 10,
        "http_chunk_size": 1 << 20,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "cachedir": str(CACHE_DIR),
    }
    if cookiefile := _cookiefile_path():
        opts["cookiefile"] = cookiefile
    return opts


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client and not _client.is_closed:
        return _client
    async with _client_lock:
        if _client and not _client.is_closed:
            return _client
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=15.0, read=60.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100, keepalive_expiry=300),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"}
        )
    return _client


async def api_download_audio(video_id: str) -> Optional[str]:
    if not USE_API or not API_BASE_URL:
        return None
    url = f"{API_BASE_URL.rstrip('/')}/mp3?id={video_id}"
    try:
        client = await _get_client()
        r = await client.get(url, timeout=30)
        if r.status_code != 200:
            return None
        data = r.json()
        dl_url = data.get("downloadUrl")
        if not dl_url:
            return None
        out_path = f"{DOWNLOAD_DIR}/{video_id}.mp3"
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        async with client.stream("GET", dl_url, timeout=120) as resp:
            if resp.status_code != 200:
                return None
            async with aiofiles.open(out_path, "wb") as f:
                async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                    if chunk:
                        await f.write(chunk)
        return out_path if os.path.exists(out_path) else None
    except Exception:
        return None


async def api_download_video(video_id: str, quality: str = "720p") -> Optional[str]:
    if not USE_API or not API_BASE_URL:
        return None
    url = f"{API_BASE_URL.rstrip('/')}/video?id={video_id}&quality={quality}"
    try:
        client = await _get_client()
        r = await client.get(url, timeout=30)
        if r.status_code != 200:
            return None
        data = r.json()
        dl_url = data.get("downloadUrl")
        if not dl_url:
            return None
        out_path = f"{DOWNLOAD_DIR}/{video_id}.mp4"
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        async with client.stream("GET", dl_url, timeout=300) as resp:
            if resp.status_code != 200:
                return None
            async with aiofiles.open(out_path, "wb") as f:
                async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                    if chunk:
                        await f.write(chunk)
        return out_path if os.path.exists(out_path) else None
    except Exception:
        return None


def _download_ytdlp_sync(link: str, opts: dict) -> Optional[str]:
    try:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=False)
            vid = info["id"]
            ext = info.get("ext", "webm")
            path = f"{DOWNLOAD_DIR}/{vid}.{ext}"
            if os.path.exists(path):
                return path
            ydl.download([link])
            return path if os.path.exists(path) else None
    except Exception:
        return None


async def _run_ytdlp(link: str, opts: dict) -> Optional[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _download_ytdlp_sync, link, opts)


async def _dedup(key: str, runner):
    async with _inflight_lock:
        if key in _inflight:
            return await _inflight[key]
        fut = asyncio.get_event_loop().create_future()
        _inflight[key] = fut
    try:
        result = await runner()
        fut.set_result(result)
        return result
    except Exception as e:
        fut.set_exception(e)
        return None
    finally:
        async with _inflight_lock:
            _inflight.pop(key, None)


async def download_audio(link: str) -> Optional[str]:
    video_id = extract_video_id(link)
    if cached := file_exists(video_id, "mp3"):
        return cached
    key = f"audio:{video_id}"
    async def run():
        async with SEM:
            api_result = await api_download_audio(video_id)
            if api_result and os.path.exists(api_result):
                return api_result
            opts = _ytdlp_base_opts()
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "outtmpl": f"{DOWNLOAD_DIR}/{video_id}.%(ext)s",
            })
            return await _run_ytdlp(link, opts)
    return await _dedup(key, run)


async def download_video(link: str, quality: int = 720) -> Optional[str]:
    video_id = extract_video_id(link)
    if cached := file_exists(video_id, "mp4"):
        return cached
    key = f"video:{video_id}:{quality}"
    async def run():
        async with SEM:
            api_result = await api_download_video(video_id, f"{quality}p")
            if api_result and os.path.exists(api_result):
                return api_result
            height = min(quality, 720)
            opts = _ytdlp_base_opts()
            opts.update({
                "format": f"best[height<={height}]/best",
                "merge_output_format": "mp4",
            })
            return await _run_ytdlp(link, opts)
    return await _dedup(key, run)


async def download_song_video(link: str, format_id: str, title: str) -> Optional[str]:
    safe_title = _safe_filename(title)
    video_id = extract_video_id(link)
    out_path = f"{DOWNLOAD_DIR}/{safe_title}.mp4"
    if os.path.exists(out_path):
        return out_path
    key = f"song_video:{video_id}:{format_id}:{safe_title}"
    async def run():
        async with SEM:
            api_vid = await api_download_video(video_id)
            if api_vid and os.path.exists(api_vid):
                final_path = f"{DOWNLOAD_DIR}/{safe_title}.mp4"
                os.replace(api_vid, final_path)
                return final_path
            opts = _ytdlp_base_opts()
            opts.update({
                "format": f"{format_id}+140",
                "outtmpl": out_path,
                "merge_output_format": "mp4",
            })
            await _run_ytdlp(link, opts)
            return out_path if os.path.exists(out_path) else None
    return await _dedup(key, run)


async def download_song_audio(link: str, format_id: str, title: str) -> Optional[str]:
    safe_title = _safe_filename(title)
    video_id = extract_video_id(link)
    out_path = f"{DOWNLOAD_DIR}/{safe_title}.mp3"
    if os.path.exists(out_path):
        return out_path
    key = f"song_audio:{video_id}:{format_id}:{safe_title}"
    async def run():
        async with SEM:
            api_audio = await api_download_audio(video_id)
            if api_audio and os.path.exists(api_audio):
                final_path = f"{DOWNLOAD_DIR}/{safe_title}.mp3"
                os.replace(api_audio, final_path)
                return final_path
            opts = _ytdlp_base_opts()
            opts.update({
                "format": format_id,
                "outtmpl": f"{DOWNLOAD_DIR}/{safe_title}.%(ext)s",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
            await _run_ytdlp(link, opts)
            return out_path if os.path.exists(out_path) else None
    return await _dedup(key, run)
