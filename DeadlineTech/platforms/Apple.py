import re
import aiohttp
import asyncio
from typing import Union, Dict, Any
from youtubesearchpython.__future__ import VideosSearch


class AppleAPI:
    def __init__(self):
        # Apple Music URLs (album, playlist, song, artist)
        self.regex = r"^(https:\/\/(?:embed\.)?music\.apple\.com\/(?:[a-z]{2}\/)?(?:album|playlist|song|artist)\/[^\s\/]+\/(\d+))"
        self.base = "https://music.apple.com/in/playlist/"
        self.itunes_api = "https://itunes.apple.com/lookup?id={}"

        # YouTube search throttling
        self.youtube_semaphore = asyncio.Semaphore(1)
        self.last_youtube_request = 0
        self.youtube_delay = 1.0

    # ---------------------- Compatibility Helper ----------------------

    def valid(self, url: str) -> bool:
        """Check if the given URL matches Apple Music pattern (synchronous)"""
        return re.match(self.regex, url) is not None

    # ---------------------- Handlers ----------------------

    def _normalize_url(self, url: str) -> str:
        return url.replace("embed.music.apple.com", "music.apple.com")

    def _extract_track_id(self, url: str) -> Union[str, None]:
        match = re.search(r"[?&]i=(\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"/song/[^/]+/(\d+)", url)
        return match.group(1) if match else None

    def _extract_album_id(self, url: str) -> Union[str, None]:
        match = re.search(r"/album/[^/]+/id?(\d+)", url)
        return match.group(1) if match else None

    def _extract_playlist_id(self, url: str) -> Union[str, None]:
        match = re.search(r"/playlist/[^/]+/(pl\.\w+)", url)
        return match.group(1) if match else None

    def _extract_artist_id(self, url: str) -> Union[str, None]:
        match = re.search(r"/artist/[^/]+/(\d+)", url)
        return match.group(1) if match else None

    async def fetch_itunes(self, entity_id: str, entity: str) -> Union[Dict[str, Any], None]:
        url = f"{self.itunes_api.format(entity_id)}&entity={entity}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

    async def yt_search(self, query: str) -> Union[Dict[str, Any], None]:
        async with self.youtube_semaphore:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.last_youtube_request
            if elapsed < self.youtube_delay:
                await asyncio.sleep(self.youtube_delay - elapsed)
            self.last_youtube_request = asyncio.get_event_loop().time()

            results = VideosSearch(query, limit=1)
            yt_data = await results.next()
            if not yt_data["result"]:
                return None
            return yt_data["result"][0]

    # ---------------------- Public Methods ----------------------

    async def track(self, url: str, playid: Union[bool, str] = None):
        track_id = self._extract_track_id(url)
        if not track_id:
            return False

        data = await self.fetch_itunes(track_id, "song")
        if not data or data.get("resultCount", 0) == 0:
            return False

        info = data["results"][0]
        search_query = f"{info['trackName']} {info['artistName']}"
        yt = await self.yt_search(search_query)
        if not yt:
            return False

        track_details = {
            "title": yt["title"],
            "link": yt["link"],
            "vidid": yt["id"],
            "duration_min": yt["duration"],
            "thumb": yt["thumbnails"][0]["url"].split("?")[0],
        }
        return track_details, yt["id"]

    async def album(self, url: str, playid: Union[bool, str] = None):
        album_id = self._extract_album_id(url)
        if not album_id:
            return False

        data = await self.fetch_itunes(album_id, "album")
        if not data or data.get("resultCount", 0) == 0:
            return False

        songs = []
        for track in data["results"][1:]:
            if "trackName" in track:
                songs.append(f"{track['trackName']} {track['artistName']}")

        return songs, album_id

    async def playlist(self, url: str, playid: Union[bool, str] = None):
        playlist_id = self._extract_playlist_id(url)
        if not playlist_id:
            return False

        data = await self.fetch_itunes(playlist_id, "playlist")
        if not data or data.get("resultCount", 0) == 0:
            return False

        songs = []
        for track in data["results"][1:]:
            if "trackName" in track:
                songs.append(f"{track['trackName']} {track['artistName']}")

        return songs, playlist_id

    async def artist(self, url: str, playid: Union[bool, str] = None):
        artist_id = self._extract_artist_id(url)
        if not artist_id:
            return False

        data = await self.fetch_itunes(artist_id, "musicArtist")
        if not data or data.get("resultCount", 0) == 0:
            return False

        songs = []
        for track in data["results"][1:]:
            if "trackName" in track:
                songs.append(f"{track['trackName']} {track['artistName']}")

        return songs, artist_id

    # ---------------------- Dispatcher ----------------------

    async def parse(self, url: str):
        url = self._normalize_url(url)

        # fix: valid() is synchronous, do NOT await
        if not self.valid(url):
            return False

        if self._extract_track_id(url):
            return await self.track(url)
        if self._extract_album_id(url):
            return await self.album(url)
        if self._extract_playlist_id(url):
            return await self.playlist(url)
        if self._extract_artist_id(url):
            return await self.artist(url)
        return False
