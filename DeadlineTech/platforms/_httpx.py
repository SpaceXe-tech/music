"""
Async HTTP download helpers using the `httpx` library with:
- Global exponential backoff + jitter
- 8 MiB chunked streaming
- Centralized download directory handling
"""
from __future__ import annotations

import asyncio
import os
import random
from typing import Dict, Optional

import httpx

# Defaults
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB
DEFAULT_TIMEOUT = 40.0  # seconds
MAX_RETRIES = 2
BACKOFF_FACTOR = 0.5  # base seconds, exponential


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


async def _sleep_with_jitter(base_seconds: float) -> None:
    # Add a small jitter to reduce thundering herd
    await asyncio.sleep(base_seconds + random.uniform(0, 0.25))


async def download_with_retries(
    url: str,
    dest_path: str,
    headers: Optional[Dict[str, str]] = None,
    max_retries: int = MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    """
    Stream a URL to file with retries, backoff, and 8 MiB chunks.

    Returns the dest_path on success, or None on failure.
    """
    ensure_dir(os.path.dirname(dest_path) or ".")

    attempt = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                # use streaming to avoid loading whole body into memory
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code >= 400:
                        # server error or client error – retry for 5xx, else fail
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


# NOTE: Kept exactly as before (no changes) per "except fetch cookies"
async def fetch_cookies_file(cookies_url: str, cookies_dir: str = "cookies") -> str:
    """
    Downloads cookies.txt to `cookies_dir/cookies.txt` with retries.
    Raises FileNotFoundError if we cannot fetch it after retries.
    """
    ensure_dir(cookies_dir)
    dest_path = os.path.join(cookies_dir, "cookies.txt")

    result = await download_with_retries(cookies_url, dest_path)
    if not result:
        raise FileNotFoundError(f"Failed to fetch cookies from {cookies_url}")
    return dest_path
