import asyncio
import os
from datetime import datetime, timedelta
from typing import Union

from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup
from ntgcalls import TelegramServerError
from pytgcalls import PyTgCalls
from pytgcalls.exceptions import (
    AlreadyJoinedError,
    NoActiveGroupCall,
)
from pytgcalls.types import (
    MediaStream,
    AudioQuality,
    VideoQuality,
    Update,
)
from pytgcalls.types.stream import StreamAudioEnded

import config
from DeadlineTech import LOGGER, YouTube, app
from DeadlineTech.misc import db
from DeadlineTech.utils.database import (
    add_active_chat,
    add_active_video_chat,
    get_lang,
    get_loop,
    group_assistant,
    is_autoend,
    music_on,
    remove_active_chat,
    remove_active_video_chat,
    set_loop,
)
from DeadlineTech.utils.exceptions import AssistantErr
from DeadlineTech.utils.formatters import check_duration, seconds_to_min, speed_converter
from DeadlineTech.utils.inline.play import stream_markup, stream_markup2
from DeadlineTech.utils.stream.autoclear import auto_clean
from DeadlineTech.utils.thumbnails import get_thumb
from strings import get_string

autoend = {}
counter = {}
db_locks = {}  # Added for thread-safe queue operations
loop = asyncio.get_event_loop_policy().get_event_loop()

async def _clear_(chat_id):
    try:
        if chat_id in db:
            del db[chat_id]
        await remove_active_video_chat(chat_id)
        await remove_active_chat(chat_id)
        LOGGER(__name__).info(f"Cleared chat {chat_id} from database")
    except Exception as e:
        LOGGER(__name__).error(f"Error clearing chat {chat_id}: {str(e)}")

class Call(PyTgCalls):
    def __init__(self):
        self.userbot1 = Client(
            name="DeadlineXAss1",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING1),
        )
        self.one = PyTgCalls(
            self.userbot1,
            cache_duration=100,
        )
        self.userbot2 = Client(
            name="DeadlineXAss2",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING2),
        )
        self.two = PyTgCalls(
            self.userbot2,
            cache_duration=100,
        )
        self.userbot3 = Client(
            name="DeadlineXAss3",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING3),
        )
        self.three = PyTgCalls(
            self.userbot3,
            cache_duration=100,
        )
        self.userbot4 = Client(
            name="DeadlineXAss4",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING4),
        )
        self.four = PyTgCalls(
            self.userbot4,
            cache_duration=100,
        )
        self.userbot5 = Client(
            name="DeadlineXAss5",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING5),
        )
        self.five = PyTgCalls(
            self.userbot5,
            cache_duration=100,
        )

    async def pause_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        await assistant.pause_stream(chat_id)

    async def mute_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        await assistant.mute_stream(chat_id)

    async def unmute_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        await assistant.unmute_stream(chat_id)

    async def get_participant(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        participant = await assistant.get_participants(chat_id)
        return participant

    async def resume_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        await assistant.resume_stream(chat_id)

    async def stop_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            await _clear_(chat_id)
            await assistant.leave_group_call(chat_id)
            LOGGER(__name__).info(f"Stopped stream and left VC for chat {chat_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error stopping stream for chat {chat_id}: {str(e)}")

    async def stop_stream_force(self, chat_id: int):
        for client in [self.one, self.two, self.three, self.four, self.five]:
            try:
                await client.leave_group_call(chat_id)
                LOGGER(__name__).info(f"Assistant left VC for chat {chat_id}")
            except Exception as e:
                LOGGER(__name__).error(f"Error leaving VC for chat {chat_id}: {str(e)}")
        await _clear_(chat_id)

    async def speedup_stream(self, chat_id: int, file_path, speed, playing):
        assistant = await group_assistant(self, chat_id)
        if str(speed) != "1.0":
            base = os.path.basename(file_path)
            chatdir = os.path.join(os.getcwd(), "playback", str(speed))
            if not os.path.isdir(chatdir):
                os.makedirs(chatdir)
            out = os.path.join(chatdir, base)
            if not os.path.isfile(out):
                if str(speed) == "0.5":
                    vs = 2.0
                if str(speed) == "0.75":
                    vs = 1.35
                if str(speed) == "1.5":
                    vs = 0.68
                if str(speed) == "2.0":
                    vs = 0.5
                proc = await asyncio.create_subprocess_shell(
                    cmd=(
                        "ffmpeg "
                        "-i "
                        f"{file_path} "
                        "-filter:v "
                        f"setpts={vs}*PTS "
                        "-filter:a "
                        f"atempo={speed} "
                        f"{out}"
                    ),
                    stdin=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
        else:
            out = file_path
        dur = await loop.run_in_executor(None, check_duration, out)
        dur = int(dur)
        played, con_seconds = speed_converter(playing[0]["played"], speed)
        duration = seconds_to_min(dur)
        stream = (
            MediaStream(
                out,
                audio_parameters=AudioQuality.HIGH,
                video_parameters=VideoQuality.SD_480p,
                ffmpeg_parameters=f"-ss {played} -to {duration}",
            )
            if playing[0]["streamtype"] == "video"
            else MediaStream(
                out,
                audio_parameters=AudioQuality.HIGH,
                ffmpeg_parameters=f"-ss {played} -to {duration}",
                video_flags=MediaStream.IGNORE,
            )
        )
        if str(db[chat_id][0]["file"]) == str(file_path):
            await assistant.change_stream(chat_id, stream)
        else:
            raise AssistantErr("Umm")
        if str(db[chat_id][0]["file"]) == str(file_path):
            exis = (playing[0]).get("old_dur")
            if not exis:
                db[chat_id][0]["old_dur"] = db[chat_id][0]["dur"]
                db[chat_id][0]["old_second"] = db[chat_id][0]["seconds"]
            db[chat_id][0]["played"] = con_seconds
            db[chat_id][0]["dur"] = duration
            db[chat_id][0]["seconds"] = dur
            db[chat_id][0]["speed_path"] = out
            db[chat_id][0]["speed"] = speed

    async def force_stop_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            check = db.get(chat_id)
            check.pop(0)
        except:
            pass
        await remove_active_video_chat(chat_id)
        await remove_active_chat(chat_id)
        try:
            await assistant.leave_group_call(chat_id)
            LOGGER(__name__).info(f"Force stopped stream and left VC for chat {chat_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error force stopping stream for chat {chat_id}: {str(e)}")

    async def skip_stream(
        self,
        chat_id: int,
        link: str,
        video: Union[bool, str] = None,
        image: Union[bool, str] = None,
    ):
        assistant = await group_assistant(self, chat_id)
        if video:
            stream = MediaStream(
                link,
                audio_parameters=AudioQuality.HIGH,
                video_parameters=VideoQuality.SD_480p,
            )
        else:
            stream = MediaStream(
                link,
                audio_parameters=AudioQuality.HIGH,
                video_flags=MediaStream.IGNORE,
            )
        try:
            await assistant.change_stream(chat_id, stream)
            LOGGER(__name__).info(f"Skipped to new stream in chat {chat_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error skipping stream in chat {chat_id}: {str(e)}")
            await app.send_message(chat_id, text="Failed to skip stream due to an error.")

    async def seek_stream(self, chat_id, file_path, to_seek, duration, mode):
        assistant = await group_assistant(self, chat_id)
        stream = (
            MediaStream(
                file_path,
                audio_parameters=AudioQuality.HIGH,
                video_parameters=VideoQuality.SD_480p,
                ffmpeg_parameters=f"-ss {to_seek} -to {duration}",
            )
            if mode == "video"
            else MediaStream(
                file_path,
                audio_parameters=AudioQuality.HIGH,
                ffmpeg_parameters=f"-ss {to_seek} -to {duration}",
                video_flags=MediaStream.IGNORE,
            )
        )
        try:
            await assistant.change_stream(chat_id, stream)
            LOGGER(__name__).info(f"Seeked stream in chat {chat_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error seeking stream in chat {chat_id}: {str(e)}")

    async def stream_call(self, link):
        assistant = await group_assistant(self, config.LOGGER_ID)
        try:
            await assistant.join_group_call(config.LOGGER_ID, MediaStream(link))
            await asyncio.sleep(0.2)
            await assistant.leave_group_call(config.LOGGER_ID)
            LOGGER(__name__).info(f"Test stream call successful for logger ID {config.LOGGER_ID}")
        except Exception as e:
            LOGGER(__name__).error(f"Error in stream call for logger ID {config.LOGGER_ID}: {str(e)}")

    async def join_call(
        self,
        chat_id: int,
        original_chat_id: int,
        link,
        video: Union[bool, str] = None,
        image: Union[bool, str] = None,
    ):
        assistant = await group_assistant(self, chat_id)
        language = await get_lang(chat_id)
        _ = get_string(language)
        if video:
            stream = MediaStream(
                link,
                audio_parameters=AudioQuality.HIGH,
                video_parameters=VideoQuality.SD_480p,
            )
        else:
            stream = MediaStream(
                link,
                audio_parameters=AudioQuality.HIGH,
                video_flags=MediaStream.IGNORE,
            )
        try:
            await assistant.join_group_call(chat_id, stream)
            LOGGER(__name__).info(f"Joined VC and started stream in chat {chat_id}")
        except NoActiveGroupCall:
            LOGGER(__name__).error(f"No active group call in chat {chat_id}")
            raise AssistantErr(_["call_8"])
        except AlreadyJoinedError:
            LOGGER(__name__).error(f"Already joined VC in chat {chat_id}")
            raise AssistantErr(_["call_9"])
        except TelegramServerError:
            LOGGER(__name__).error(f"Telegram server error in chat {chat_id}")
            raise AssistantErr(_["call_10"])
        except Exception as e:
            LOGGER(__name__).error(f"Unexpected error joining VC in chat {chat_id}: {str(e)}")
            if "phone.CreateGroupCall" in str(e):
                raise AssistantErr(_["call_8"])
            raise AssistantErr("Failed to join voice chat due to an unexpected error.")
        await add_active_chat(chat_id)
        await music_on(chat_id)
        if video:
            await add_active_video_chat(chat_id)
        if await is_autoend():
            counter[chat_id] = {}
            users = len(await assistant.get_participants(chat_id))
            if users == 1:
                autoend[chat_id] = datetime.now() + timedelta(minutes=1)

    async def attempt_stream(self, client, chat_id, stream, retries=3):
        for attempt in range(retries):
            try:
                await client.change_stream(chat_id, stream)
                LOGGER(__name__).info(f"Stream changed successfully in chat {chat_id} on attempt {attempt + 1}")
                return True
            except Exception as e:
                LOGGER(__name__).error(f"Stream attempt {attempt + 1} failed in chat {chat_id}: {str(e)}")
                await asyncio.sleep(1)
        return False

    async def check_autoend(self, chat_id):
        if await is_autoend() and chat_id in autoend:
            users = len(await (await group_assistant(self, chat_id)).get_participants(chat_id))
            if users <= 1:
                if chat_id not in autoend:
                    autoend[chat_id] = datetime.now()
                elif datetime.now() - autoend[chat_id] > timedelta(minutes=1):
                    await self.stop_stream(chat_id)
                    LOGGER(__name__).info(f"Auto-ended stream for chat {chat_id}")
            else:
                autoend.pop(chat_id, None)

    async def change_stream(self, client, chat_id):
        if chat_id not in db_locks:
            db_locks[chat_id] = asyncio.Lock()
        async with db_locks[chat_id]:
            check = db.get(chat_id)
            popped = None
            loop = await get_loop(chat_id)
            try:
                if loop == 0:
                    popped = check.pop(0)
                else:
                    loop = loop - 1
                    await set_loop(chat_id, loop)
                await auto_clean(popped)
                if not check:
                    await _clear_(chat_id)
                    await client.leave_group_call(chat_id)
                    LOGGER(__name__).info(f"No more tracks in queue, left VC for chat {chat_id}")
                    return
            except:
                await _clear_(chat_id)
                await client.leave_group_call(chat_id)
                LOGGER(__name__).info(f"Error in queue, cleared and left VC for chat {chat_id}")
                return
            else:
                queued = check[0]["file"]
                language = await get_lang(chat_id)
                _ = get_string(language)
                title = (check[0]["title"]).title()
                user = check[0]["by"]
                original_chat_id = check[0]["chat_id"]
                streamtype = check[0]["streamtype"]
                videoid = check[0]["vidid"]
                db[chat_id][0]["played"] = 0
                if exis := (check[0]).get("old_dur"):
                    db[chat_id][0]["dur"] = exis
                    db[chat_id][0]["seconds"] = check[0]["old_second"]
                    db[chat_id][0]["speed_path"] = None
                    db[chat_id][0]["speed"] = 1.0
                video = str(streamtype) == "video"
                if "live_" in queued:
                    n, link = await YouTube.video(videoid, True)
                    if n == 0:
                        LOGGER(__name__).error(f"Failed to get YouTube video link for {videoid}")
                        await app.send_message(original_chat_id, text=_["call_6"])
                        await _clear_(chat_id)
                        return
                    if video:
                        stream = MediaStream(
                            link,
                            audio_parameters=AudioQuality.HIGH,
                            video_parameters=VideoQuality.SD_480p,
                        )
                    else:
                        stream = MediaStream(
                            link,
                            audio_parameters=AudioQuality.HIGH,
                            video_flags=MediaStream.IGNORE,
                        )
                    if not await self.attempt_stream(client, chat_id, stream):
                        await app.send_message(original_chat_id, text=_["call_6"])
                        await _clear_(chat_id)
                        return
                    img = await get_thumb(videoid)
                    button = stream_markup(_, chat_id)
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=img,
                        caption=_["stream_1"].format(
                            f"https://t.me/{app.username}?start=info_{videoid}",
                            title[:23],
                            check[0]["dur"],
                            user,
                        ),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "tg"
                elif "vid_" in queued:
                    mystic = await app.send_message(original_chat_id, _["call_7"])
                    try:
                        file_path, direct = await YouTube.download(
                            videoid,
                            mystic,
                            videoid=True,
                            video=str(streamtype) == "video",
                        )
                        if not os.path.exists(file_path):
                            LOGGER(__name__).error(f"File {file_path} does not exist")
                            await mystic.edit_text(_["call_6"], disable_web_page_preview=True)
                            await _clear_(chat_id)
                            return
                    except Exception as e:
                        LOGGER(__name__).error(f"Error downloading video {videoid}: {str(e)}")
                        await mystic.edit_text(_["call_6"], disable_web_page_preview=True)
                        await _clear_(chat_id)
                        return
                    if video:
                        stream = MediaStream(
                            file_path,
                            audio_parameters=AudioQuality.HIGH,
                            video_parameters=VideoQuality.SD_480p,
                        )
                    else:
                        stream = MediaStream(
                            file_path,
                            audio_parameters=AudioQuality.HIGH,
                            video_flags=MediaStream.IGNORE,
                        )
                    if not await self.attempt_stream(client, chat_id, stream):
                        await app.send_message(original_chat_id, text=_["call_6"])
                        await _clear_(chat_id)
                        return
                    img = await get_thumb(videoid)
                    button = stream_markup(_, chat_id)
                    await mystic.delete()
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=img,
                        caption=_["stream_1"].format(
                            f"https://t.me/{app.username}?start=info_{videoid}",
                            title[:23],
                            check[0]["dur"],
                            user,
                        ),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "stream"
                elif "index_" in queued:
                    stream = (
                        MediaStream(
                            videoid,
                            audio_parameters=AudioQuality.HIGH,
                            video_parameters=VideoQuality.SD_480p,
                        )
                        if str(streamtype) == "video"
                        else MediaStream(
                            videoid,
                            audio_parameters=AudioQuality.HIGH,
                            video_flags=MediaStream.IGNORE,
                        )
                    )
                    if not await self.attempt_stream(client, chat_id, stream):
                        await app.send_message(original_chat_id, text=_["call_6"])
                        await _clear_(chat_id)
                        return
                    button = stream_markup(_, chat_id)
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=config.STREAM_IMG_URL,
                        caption=_["stream_2"].format(user),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "tg"
                else:
                    if video:
                        stream = MediaStream(
                            queued,
                            audio_parameters=AudioQuality.HIGH,
                            video_parameters=VideoQuality.SD_480p,
                        )
                    else:
                        stream = MediaStream(
                            queued,
                            audio_parameters=AudioQuality.HIGH,
                            video_flags=MediaStream.IGNORE,
                        )
                    if not await self.attempt_stream(client, chat_id, stream):
                        await app.send_message(original_chat_id, text=_["call_6"])
                        await _clear_(chat_id)
                        return
                    if videoid == "telegram":
                        button = stream_markup(_, chat_id)
                        run = await app.send_photo(
                            chat_id=original_chat_id,
                            photo=(
                                config.TELEGRAM_AUDIO_URL
                                if str(streamtype) == "audio"
                                else config.TELEGRAM_VIDEO_URL
                            ),
                            caption=_["stream_1"].format(
                                config.SUPPORT_CHAT, title[:23], check[0]["dur"], user
                            ),
                            reply_markup=InlineKeyboardMarkup(button),
                        )
                        db[chat_id][0]["mystic"] = run
                        db[chat_id][0]["markup"] = "tg"
                    elif videoid == "soundcloud":
                        button = stream_markup(_, chat_id)
                        run = await app.send_photo(
                            chat_id=original_chat_id,
                            photo=config.SOUNCLOUD_IMG_URL,
                            caption=_["stream_1"].format(
                                config.SUPPORT_CHAT, title[:23], check[0]["dur"], user
                            ),
                            reply_markup=InlineKeyboardMarkup(button),
                        )
                        db[chat_id][0]["mystic"] = run
                        db[chat_id][0]["markup"] = "tg"
                    else:
                        img = await get_thumb(videoid)
                        button = stream_markup(_, chat_id)
                        run = await app.send_photo(
                            chat_id=original_chat_id,
                            photo=img,
                            caption=_["stream_1"].format(
                                f"https://t.me/{app.username}?start=info_{videoid}",
                                title[:23],
                                check[0]["dur"],
                                user,
                            ),
                            reply_markup=InlineKeyboardMarkup(button),
                        )
                        db[chat_id][0]["mystic"] = run
                        db[chat_id][0]["markup"] = "stream"

    async def ping(self):
        pings = []
        if config.STRING1:
            pings.append(await self.one.ping)
        if config.STRING2:
            pings.append(await self.two.ping)
        if config.STRING3:
            pings.append(await self.three.ping)
        if config.STRING4:
            pings.append(await self.four.ping)
        if config.STRING5:
            pings.append(await self.five.ping)
        return str(round(sum(pings) / len(pings), 3))

    async def start(self):
        LOGGER(__name__).info("Starting PyTgCalls Client...\n")
        if config.STRING1:
            await self.one.start()
        if config.STRING2:
            await self.two.start()
        if config.STRING3:
            await self.three.start()
        if config.STRING4:
            await self.four.start()
        if config.STRING5:
            await self.five.start()

    async def decorators(self):
        @self.one.on_kicked()
        @self.two.on_kicked()
        @self.three.on_kicked()
        @self.four.on_kicked()
        @self.five.on_kicked()
        @self.one.on_closed_voice_chat()
        @self.two.on_closed_voice_chat()
        @self.three.on_closed_voice_chat()
        @self.four.on_closed_voice_chat()
        @self.five.on_closed_voice_chat()
        @self.one.on_left()
        @self.two.on_left()
        @self.three.on_left()
        @self.four.on_left()
        @self.five.on_left()
        async def stream_services_handler(_, chat_id: int):
            await self.stop_stream(chat_id)

        @self.one.on_stream_end()
        @self.two.on_stream_end()
        @self.three.on_stream_end()
        @self.four.on_stream_end()
        @self.five.on_stream_end()
        async def stream_end_handler(client, update: Update):
            if not isinstance(update, StreamAudioEnded):
                LOGGER(__name__).info(f"Non-audio stream end event: {update}")
                return
            chat_id = update.chat_id
            LOGGER(__name__).info(f"Stream ended for chat {chat_id}")
            await self.change_stream(client, chat_id)
            if not db.get(chat_id):
                await _clear_(chat_id)
                await client.leave_group_call(chat_id)
                LOGGER(__name__).info(f"No more tracks in queue, left VC for chat {chat_id}")
        # Removed on_update handler as PyTgCalls does not support it

Anony = Call()
