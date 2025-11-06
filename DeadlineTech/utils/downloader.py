import asyncio
import contextlib
import os
import re
from typing import Dict, Optional, Union

import aiofiles
import httpx
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = "downloads"
CACHE_DIR = "cache"
COOKIE_PATH = "cookies.txt"
CHUNK_SIZE = 8 * 1024 * 1024
SEM = asyncio.Semaphore(5)
USE_API = False
API_URL = ""
API_KEY = ""

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


def file_exists(video_id: str) -> Optional[str]:
    for ext in ("mp3", "m4a", "webm"):
        path = f"{DOWNLOAD_DIR}/{video_id}.{ext}"
        if os.path.exists(path):
            return path
    return None


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]+', "_", (name or "").strip())[:200]


def _ytdlp_base_opts() -> Dict[str, Union[str, int, bool]]:
    opts: Dict[str, Union[str, int, bool]] = {
        "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "overwrites": True,
        "continuedl": True,
        "noprogress": True,
        "concurrent_fragment_downloads": 16,
        "http_chunk_size": 1 << 20,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "cachedir": str(CACHE_DIR),
    }
    cookiefile = _cookiefile_path()
    if cookiefile:
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
            timeout=httpx.Timeout(600.0, connect=20.0, read=60.0),
            limits=httpx.Limits(max_keepalive_connections=None, max_connections=None, keepalive_expiry=300.0),
            follow_redirects=True,
        )
        return _client


async def api_download_song(link: str) -> Optional[str]:
    if not USE_API or not API_URL or not API_KEY:
        return None
    vid = extract_video_id(link)
    poll_url = f"{API_URL}/song/{vid}?api={API_KEY}"
    try:
        client = await _get_client()
        while True:
            r = await client.get(poll_url)
            if r.status_code != 200:
                return None
            data = r.json()
            s = str(data.get("status", "")).lower()
            if s == "downloading":
                await asyncio.sleep(1.5)
                continue
            if s != "done":
                return None
            dl = data.get("link")
            fmt = str(data.get("format", "mp3")).lower()
            out_path = f"{DOWNLOAD_DIR}/{vid}.{fmt}"
            async with client.stream("GET", dl) as fr:
                if fr.status_code != 200:
                    return None
                os.makedirs(DOWNLOAD_DIR, exist_ok=True)
                async with aiofiles.open(out_path, "wb") as f:
                    async for chunk in fr.aiter_bytes(CHUNK_SIZE):
                        if not chunk:
                            break
                        await f.write(chunk)
            return out_path
    except Exception:
        return None


def _download_ytdlp(link: str, opts: Dict) -> Optional[str]:
    try:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=False)
            ext = info.get("ext") or "webm"
            vid = info.get("id")
            path = f"{DOWNLOAD_DIR}/{vid}.{ext}"
            if os.path.exists(path):
                return path
            ydl.download([link])
            return path
    except Exception:
        return None


async def _with_sem(coro):
    async with SEM:
        return await coro


async def _dedup(key: str, runner):
    async with _inflight_lock:
        fut = _inflight.get(key)
        if fut:
            return await fut
        fut = asyncio.get_running_loop().create_future()
        _inflight[key] = fut
    try:
        res = await runner()
        fut.set_result(res)
        return res
    except Exception:
        fut.set_result(None)
        return None
    finally:
        async with _inflight_lock:
            _inflight.pop(key, None)


async def yt_dlp_download(
    link: str, type: str, format_id: str = None, title: str = None
) -> Optional[str]:
    loop = asyncio.get_running_loop()
    if type == "audio":
        key = f"a:{link}"

        async def run():
            opts = _ytdlp_base_opts()
            opts.update({"format": "bestaudio/best"})
            return await _with_sem(loop.run_in_executor(None, _download_ytdlp, link, opts))

        return await _dedup(key, run)

    if type == "video":
        key = f"v:{link}"

        async def run():
            opts = _ytdlp_base_opts()
            opts.update({"format": "best[height<=?720][width<=?1280]"})
            return await _with_sem(loop.run_in_executor(None, _download_ytdlp, link, opts))

        return await _dedup(key, run)

    if type == "song_video" and format_id and title:
        safe_title = _safe_filename(title)
        key = f"sv:{link}:{format_id}:{safe_title}"

        async def run():
            opts = _ytdlp_base_opts()
            opts.update(
                {
                    "format": f"{format_id}+140",
                    "outtmpl": f"{DOWNLOAD_DIR}/{safe_title}.mp4",
                    "prefer_ffmpeg": True,
                    "merge_output_format": "mp4",
                }
            )
            await _with_sem(loop.run_in_executor(None, lambda: YoutubeDL(opts).download([link])))
            return f"{DOWNLOAD_DIR}/{safe_title}.mp4"

        return await _dedup(key, run)

    if type == "song_audio" and format_id and title:
        safe_title = _safe_filename(title)
        key = f"sa:{link}:{format_id}:{safe_title}"

        async def run():
            opts = _ytdlp_base_opts()
            opts.update(
                {
                    "format": format_id,
                    "outtmpl": f"{DOWNLOAD_DIR}/{safe_title}.%(ext)s",
                    "prefer_ffmpeg": True,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
            )
            await _with_sem(loop.run_in_executor(None, lambda: YoutubeDL(opts).download([link])))
            return f"{DOWNLOAD_DIR}/{safe_title}.mp3"

        return await _dedup(key, run)

    return None


async def download_audio_concurrent(link: str) -> Optional[str]:
    vid = extract_video_id(link)
    cached = file_exists(vid)
    if cached:
        return cached
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    if not USE_API:
        return await yt_dlp_download(link, type="audio")
    key = f"rac:{link}"

    async def run():
        yt_task = asyncio.create_task(yt_dlp_download(link, type="audio"))
        api_task = asyncio.create_task(api_download_song(link))
        done, pending = await asyncio.wait({yt_task, api_task}, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            with contextlib.suppress(Exception):
                res = t.result()
                if res:
                    for p in pending:
                        p.cancel()
                        with contextlib.suppress(Exception, asyncio.CancelledError):
                            await p
                    return res
        for t in pending:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                res = await t
                if res:
                    return res
        return None

    return await _dedup(key, lambda: _with_sem(run()))
