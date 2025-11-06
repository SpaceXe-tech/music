from __future__ import annotations

import asyncio
import os
import random
import logging
from typing import Dict, Optional

import httpx

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_TIMEOUT = 40.0
MAX_RETRIES = 2
BACKOFF_FACTOR = 0.5

logger = logging.getLogger(__name__)

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

async def _sleep_with_jitter(base_seconds: float) -> None:
    await asyncio.sleep(base_seconds + random.uniform(0, 0.25))

async def download_with_retries(
    url: str,
    dest_path: str,
    headers: Optional[Dict[str, str]] = None,
    max_retries: int = MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    ensure_dir(os.path.dirname(dest_path) or ".")
    attempt = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code >= 400:
                        if 500 <= resp.status_code < 600 and attempt < max_retries:
                            attempt += 1
                            await _sleep_with_jitter((2 ** (attempt - 1)) * BACKOFF_FACTOR)
                            continue
                        return None
                    with open(dest_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                            if chunk:
                                f.write(chunk)
            return dest_path
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.HTTPError):
            if attempt < max_retries:
                attempt += 1
                await _sleep_with_jitter((2 ** (attempt - 1)) * BACKOFF_FACTOR)
                continue
            return None

async def fetch_json(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> Optional[dict]:
    attempt = 0
    logger.info("fetch_json: requesting %s", url)
    while True:
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code >= 400:
                    logger.warning("fetch_json: HTTP %s for %s", resp.status_code, url)
                    if 500 <= resp.status_code < 600 and attempt < max_retries:
                        attempt += 1
                        await _sleep_with_jitter((2 ** (attempt - 1)) * BACKOFF_FACTOR)
                        continue
                    return None
                data = resp.json()
                logger.debug("fetch_json: success %s", url)
                return data
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.HTTPError, ValueError) as e:
            logger.error("fetch_json: error %s (%s)", url, e)
            if attempt < max_retries:
                attempt += 1
                await _sleep_with_jitter((2 ** (attempt - 1)) * BACKOFF_FACTOR)
                continue
            return None

async def fetch_to_path(
    url: str,
    dest_dir: str,
    filename: str = "file.bin",
    headers: Optional[Dict[str, str]] = None,
    max_retries: int = MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    ensure_dir(dest_dir)
    dest_path = os.path.join(dest_dir, filename)
    return await download_with_retries(
        url,
        dest_path,
        headers=headers,
        max_retries=max_retries,
        timeout=timeout,
    )

async def fetch_cookies_file(cookies_url: str, cookies_dir: str = "cookies") -> str:
    ensure_dir(cookies_dir)
    dest_path = os.path.join(cookies_dir, "cookies.txt")
    result = await download_with_retries(cookies_url, dest_path)
    if not result:
        raise FileNotFoundError(f"Failed to fetch cookies from {cookies_url}")
    return dest_path

async def api_download_audio(
    api_base_url: str,
    video_id: str,
    download_dir: str = DOWNLOAD_DIR,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    if not video_id or not isinstance(video_id, str) or len(video_id) != 11:
        logger.warning("api_download_audio: invalid video_id=%r", video_id)
        return None
    ensure_dir(download_dir)
    dest_path = os.path.join(download_dir, f"{video_id}.mp3")
    if os.path.exists(dest_path):
        logger.info("api_download_audio: already exists at %s", dest_path)
        return dest_path
    url = f"{api_base_url.rstrip('/')}/mp3?id={video_id}"
    logger.info("api_download_audio: requesting metadata %s", url)
    data = await fetch_json(url, timeout=timeout)
    if not data or "downloadUrl" not in data:
        logger.error("api_download_audio: metadata missing downloadUrl for video_id=%s", video_id)
        return None
    dl_url = data["downloadUrl"]
    logger.info("api_download_audio: downloading from %s", dl_url)
    result = await fetch_to_path(dl_url, download_dir, f"{video_id}.mp3", timeout=timeout)
    if result:
        logger.info("api_download_audio: saved to %s", result)
    else:
        logger.error("api_download_audio: download failed for video_id=%s", video_id)
    return result

async def api_download_video(
    api_base_url: str,
    video_id: str,
    format_str: str = "720",
    download_dir: str = DOWNLOAD_DIR,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    if not video_id or not isinstance(video_id, str) or len(video_id) != 11:
        logger.warning("api_download_video: invalid video_id=%r", video_id)
        return None
    ensure_dir(download_dir)
    dest_path = os.path.join(download_dir, f"{video_id}.mp4")
    if os.path.exists(dest_path):
        logger.info("api_download_video: already exists at %s", dest_path)
        return dest_path
    url = f"{api_base_url.rstrip('/')}/download?id={video_id}&format={format_str}"
    logger.info("api_download_video: requesting metadata %s", url)
    data = await fetch_json(url, timeout=timeout)
    if not data or "downloadUrl" not in data:
        logger.error("api_download_video: metadata missing downloadUrl for video_id=%s", video_id)
        return None
    dl_url = data["downloadUrl"]
    logger.info("api_download_video: downloading from %s", dl_url)
    result = await fetch_to_path(dl_url, download_dir, f"{video_id}.mp4", timeout=timeout)
    if result:
        logger.info("api_download_video: saved to %s", result)
    else:
        logger.error("api_download_video: download failed for video_id=%s", video_id)
    return result
