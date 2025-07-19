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
    GroupCallNotFound,
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
db_locks = {}
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
        try:
            if await self.is_in_group_call(assistant, chat_id):
                await assistant.pause_stream(chat_id)
                LOGGER(__name__).info(f"Paused stream in chat {chat_id}")
            else:
                LOGGER(__name__).warning(f"Cannot pause stream: Bot not in VC for chat {chat_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error pausing stream in chat {chat_id}: {str(e)}")

    async def mute_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            if await self.is_in_group_call(assistant, chat_id):
                await assistant.mute_stream(chat_id)
                LOGGER(__name__).info(f"Muted stream in chat {chat_id}")
            else:
                LOGGER(__name__).warning(f"Cannot mute stream: Bot not in VC for chat {chat_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error muting stream in chat {chat_id}: {str(e)}")

    async def unmute_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            if await self.is_in_group_call(assistant, chat_id):
                await assistant.unmute_stream(chat_id)
                LOGGER(__name__).info(f"Unmuted stream in chat {chat_id}")
            else:
                LOGGER(__name__).warning(f"Cannot unmute stream: Bot not in VC for chat {chat_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error unmuting stream in chat {chat_id}: {str(e)}")

    async def get_participant(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            if await self.is_in_group_call(assistant, chat_id):
                participant = await assistant.get_participants(chat_id)
                return participant
            else:
                LOGGER(__name__).warning(f"Cannot get participants: Bot not in VC for chat {chat_id}")
                return []
        except Exception as e:
            LOGGER(__name__).error(f"Error getting participants in chat {chat_id}: {str(e)}")
            return []

    async def resume_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            if await self.is_in_group_call(assistant, chat_id):
                await assistant.resume_stream(chat_id)
                LOGGER(__name__).info(f"Resumed stream in chat {chat_id}")
            else:
                LOGGER(__name__).warning(f"Cannot resume stream: Bot not in VC for chat {chat_id}")
        except Exception as e:
            LOGGER(__name__).error(f"Error resuming stream in chat {chat_id}: {str(e)}")

    async def is_in_group_call(self, client, chat_id):
        """Check if the client is in a group call for the given chat_id."""
        try:
            await client.get_group_call(chat_id)
            return True
        except GroupCallNotFound:
            LOGGER(__name__).warning(f"Bot is not in group call for chat {chat_id}")
            return False
        except Exception as e:
            LOGGER(__name__).error(f"Error checking group call status for chat {chat_id}: {str(e)}")
            return False

    async def reboot(self, chat_id: int):
        """Forcefully reset the bot's VC state for the given chat_id."""
        try:
            await self.stop_stream_force(chat_id)
            LOGGER(__name__).info(f"Rebooted VC state for chat {chat_id}")
            await app.send_message(chat_id, text="Bot VC state reset. Please try playing again.")
        except Exception as e:
            LOGGER(__name__).error(f"Error rebooting VC state for chat {chat_id}: {str(e)}")
            await app.send_message(chat_id, text="Failed to reset bot state. Please try again later.")

    async def stop_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            if await self.is_in_group_call(assistant, chat_id):
                await _clear_(chat_id)
                await assistant.leave_group_call(chat_id)
                LOGGER(__name__).info(f"Stopped stream and left VC for chat {chat_id}")
            else:
                LOGGER(__name__).warning(f"Cannot stop stream: Bot not in VC for chat {chat_id}")
                await _clear_(chat_id)
        except GroupCallNotFound:
            LOGGER(__name__).warning(f"Group call not found when stopping stream for chat {chat_id}")
            await _clear_(chat_id)
        except Exception as e:
            LOGGER(__name__).error(f"Error stopping stream for chat {chat_id}: {str(e)}")
            await _clear_(chat_id)

    async def stop_stream_force(self, chat_id: int):
        for client in [self.one, self.two, self.three, self.four, self.five]:
            try:
                if await self.is_in_group_call(client, chat_id):
                    await client.leave_group_call(chat_id)
                    LOGGER(__name__).info(f"Assistant left VC for chat {chat_id}")
                else:
                    LOGGER(__name__).warning(f"Assistant not in VC for chat {chat_id}")
            except GroupCallNotFound:
                LOGGER(__name__).warning(f"Group call not found for assistant in chat {chat_id}")
            except Exception as e:
                LOGGER(__name__).error(f"Error leaving VC for chat {chat_id}: {str(e)}")
        await _clear_(chat_id)

    async def speedup_stream(self, chat_id: int, file_path, speed, playing):
        assistant = await group_assistant(self, chat_id)
        if not await self.is_in_group_call(assistant, chat_id):
            LOGGER(__name__).error(f"Cannot speedup stream: Bot not in VC for chat {chat_id}")
            return
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
            try:
                if await self.is_in_group_call(assistant, chat_id):
                    await assistant.change_stream(chat_id, stream)
                    LOGGER(__name__).info(f"Changed stream speed in chat {chat_id}")
                else:
                    LOGGER(__name__).error(f"Cannot change stream speed: Bot not in VC for chat {chat_id}")
                    return
            except GroupCallNotFound:
                LOGGER(__name__).error(f"Group call not found when changing stream speed in chat {chat_id}")
                await _clear_(chat_id)
                return
            except Exception as e:
                LOGGER(__name__).error(f"Error changing stream speed in chat {chat_id}: {str(e)}")
                raise AssistantErr("Failed to change stream speed due to an error.")
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
            if await self.is_in_group_call(assistant, chat_id):
                await assistant.leave_group_call(chat_id)
                LOGGER(__name__).info(f"Force stopped stream and left VC for chat {chat_id}")
            else:
                LOGGER(__name__).warning(f"Cannot force stop stream: Bot not in VC for chat {chat_id}")
        except GroupCallNotFound:
            LOGGER(__name__).warning(f"Group call not found when force stopping stream for chat {chat_id}")
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
        if not await self.is_in_group_call(assistant, chat_id):
            LOGGER(__name__).error(f"Cannot skip stream: Bot not in VC for chat {chat_id}")
            await app.send_message(chat_id, text="Bot is not in a voice chat. Please use /reboot and try again.")
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
        try:
            await assistant.change_stream(chat_id, stream)
            LOGGER(__name__).info(f"Skipped to new stream in chat {chat_id}")
        except GroupCallNotFound:
            LOGGER(__name__).error(f"Group call not found when skipping stream in chat {chat_id}")
            await app.send_message(chat_id, text="Bot is not in a voice chat. Please use /reboot and try again.")
            await _clear_(chat_id)
        except Exception as e:
            LOGGER(__name__).error(f"Error skipping stream in chat {chat_id}: {str(e)}")
            await app.send_message(chat_id, text="Failed to skip stream due to an error. Please use /reboot and try again.")
            await _clear_(chat_id)

    async def seek_stream(self, chat_id, file_path, to_seek, duration, mode):
        assistant = await group_assistant(self, chat_id)
        if not await self.is_in_group_call(assistant, chat_id):
            LOGGER(__name__).error(f"Cannot seek stream: Bot not in VC for chat {chat_id}")
            await app.send_message(chat_id, text="Bot is not in a voice chat. Please use /reboot and try again.")
            return
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
        except GroupCallNotFound:
            LOGGER(__name__).error(f"Group call not found when seeking stream in chat {chat_id}")
            await app.send_message(chat_id, text="Bot is not in a voice chat. Please use /reboot and try again.")
            await _clear_(chat_id)
        except Exception as e:
            LOGGER(__name__).error(f"Error seeking stream in chat {chat_id}: {str(e)}")
            await app.send_message(chat_id, text="Failed to seek stream due to an error. Please use /reboot and try again.")

    async def stream_call(self, link):
        assistant = await group_assistant(self, config.LOGGER_ID)
        try:
            await assistant.join_group_call(config.LOGGER_ID, MediaStream(link))
            await asyncio.sleep(0.2)
            await assistant.leave_group_call(config.LOGGER_ID)
            LOGGER(__name__).info(f"Test stream call successful for logger ID {config.LOGGER_ID}")
        except GroupCallNotFound:
            LOGGER(__name__).error(f"Group call not found for logger ID {config.LOGGER_ID}")
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
            await app.send_message(original_chat_id, text=_["call_8"])
            raise AssistantErr(_["call_8"])
        except AlreadyJoinedError:
            LOGGER(__name__).warning(f"Assistant already in VC for chat {chat_id}, attempting to change stream")
            try:
                if await self.is_in_group_call(assistant, chat_id):
                    await assistant.change_stream(chat_id, stream)
                    LOGGER(__name__).info(f"Changed stream in existing VC for chat {chat_id}")
                else:
                    LOGGER(__name__).error(f"State mismatch: Assistant not in VC for chat {chat_id}")
      
