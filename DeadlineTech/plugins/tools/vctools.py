import asyncio
import json
import os
from typing import Dict, Set, Tuple, List
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from pytgcalls.exceptions import NoActiveGroupCall, AlreadyJoinedError
from config import BANNED_USERS
from DeadlineTech.core.call import Anony
from DeadlineTech.utils.admin_filters import admin_filter
from DeadlineTech.utils.database import group_assistant
from DeadlineTech import app

VC_CACHE_FILE = "vcusers.json"
VC_SETTINGS_FILE = "vcsettings.json"
VC_TRACKING_ENABLED: Set[int] = set()
VC_MONITOR_TASKS: Dict[int, asyncio.Task] = {}

def load_vc_cache() -> Dict[int, Set[int]]:
    if os.path.exists(VC_CACHE_FILE):
        try:
            with open(VC_CACHE_FILE, "r") as f:
                data = json.load(f)
                return {int(k): set(v) for k, v in data.items()}
        except (json.JSONDecodeError, ValueError):
            pass
    return {}

def save_vc_cache(cache_data: Dict[int, Set[int]]) -> None:
    try:
        json_data = {str(k): list(v) for k, v in cache_data.items()}
        with open(VC_CACHE_FILE, "w") as f:
            json.dump(json_data, f, indent=2)
    except Exception:
        pass

def get_vc_cache(chat_id: int) -> Set[int]:
    return load_vc_cache().get(chat_id, set())

def update_vc_cache(chat_id: int, user_ids: Set[int]) -> None:
    cache = load_vc_cache()
    cache[chat_id] = user_ids
    save_vc_cache(cache)

def remove_from_vc_cache(chat_id: int) -> None:
    cache = load_vc_cache()
    if chat_id in cache:
        del cache[chat_id]
        save_vc_cache(cache)

def load_vc_settings() -> Dict[int, bool]:
    if os.path.exists(VC_SETTINGS_FILE):
        try:
            with open(VC_SETTINGS_FILE, "r") as f:
                data = json.load(f)
                return {int(k): bool(v) for k, v in data.items()}
        except (json.JSONDecodeError, ValueError):
            pass
    return {}

def save_vc_settings(settings_data: Dict[int, bool]) -> None:
    try:
        json_data = {str(k): v for k, v in settings_data.items()}
        with open(VC_SETTINGS_FILE, "w") as f:
            json.dump(json_data, f, indent=2)
    except Exception:
        pass

def get_vc_setting(chat_id: int) -> bool:
    return load_vc_settings().get(chat_id, False)

def update_vc_setting(chat_id: int, enabled: bool) -> None:
    settings = load_vc_settings()
    settings[chat_id] = enabled
    save_vc_settings(settings)

async def fetch_participants(assistant, chat_id: int) -> Tuple[List, str, str]:
    try:
        participants = await assistant.get_participants(chat_id)
        return participants, "active", ""
    except NoActiveGroupCall:
        return [], "no_active", ""
    except AlreadyJoinedError:
        return [], "active", ""
    except Exception as e:
        return [], "error", str(e)

def fmt_status_line(p) -> str:
    status = ["Muted" if getattr(p, "muted", False) else "Unmuted"]
    if getattr(p, "screen_sharing", False):
        status.append("Screen Sharing")
    vol = getattr(p, "volume", None)
    if vol:
        status.append(f"Volume: {vol}")
    return ", ".join(status)

async def monitor_vc_changes(chat_id: int):
    try:
        assistant = await group_assistant(Anony, chat_id)
        if not assistant:
            await app.send_message(chat_id, "Assistant not found. Make sure it has joined the VC.")
            VC_TRACKING_ENABLED.discard(chat_id)
            update_vc_setting(chat_id, False)
            return

        prev_state = None
        update_vc_cache(chat_id, set())

        while chat_id in VC_TRACKING_ENABLED:
            await asyncio.sleep(5)
            participants, state, errmsg = await fetch_participants(assistant, chat_id)

            if state != prev_state:
                if state == "no_active":
                    await app.send_message(
                        chat_id,
                        "No active voice chat. Tracking is ON — I’ll start logging when a call starts."
                    )
                    update_vc_cache(chat_id, set())
                elif state == "error":
                    await app.send_message(
                        chat_id,
                        f"VC monitor hit an error. Tracking is ON.\nDetails: {errmsg}"
                    )
                elif state == "active":
                    await app.send_message(
                        chat_id,
                        f"Detected active VC. Tracking joins/leaves now."
                    )
                prev_state = state

            if state != "active":
                continue

            current_ids = set(p.user_id for p in participants)
            old_ids = get_vc_cache(chat_id)
            update_vc_cache(chat_id, current_ids)

            joined_lines, left_lines = [], []

            for uid in current_ids - old_ids:
                try:
                    user = await app.get_users(uid)
                    name = user.mention if user else f"{uid}"
                except Exception:
                    name = f"{uid}"
                joined_lines.append(f"#JoinedVC\nName: {name}")

            for uid in old_ids - current_ids:
                try:
                    user = await app.get_users(uid)
                    name = user.mention if user else f"{uid}"
                except Exception:
                    name = f"{uid}"
                left_lines.append(f"#LeftVC\nName: {name}")

            if joined_lines or left_lines:
                text = "\n\n".join(joined_lines + left_lines)
                text += f"\n\nNow in VC: {len(current_ids)}"
                try:
                    msg = await app.send_message(chat_id, text)
                    await asyncio.sleep(30)
                    await msg.delete()
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                except Exception:
                    pass

    except Exception as e:
        try:
            await app.send_message(chat_id, f"VC monitoring stopped due to error: {e}")
        except Exception:
            pass
        VC_TRACKING_ENABLED.discard(chat_id)
        update_vc_setting(chat_id, False)
        remove_from_vc_cache(chat_id)
    finally:
        VC_MONITOR_TASKS.pop(chat_id, None)

@app.on_message(filters.command(["vcinfo", "infovc", "vclogger"]) & filters.group & admin_filter & ~BANNED_USERS)
async def vc_info(client: Client, message: Message):
    chat_id = message.chat.id
    args = message.text.split(None, 1)

    if len(args) == 2 and args[1].lower() in ["settings", "status", "check"]:
        is_enabled = get_vc_setting(chat_id)
        active_text = "Active" if chat_id in VC_TRACKING_ENABLED else "Inactive"
        status_text = "Enabled" if is_enabled else "Disabled"
        return await message.reply_text(
            "VC Info Settings for this Group:\n\n"
            f"Status: {status_text}\n"
            f"Monitoring: {active_text}\n\n"
            "Commands:\n"
            "• /vcinfo on - Enable VC tracking\n"
            "• /vcinfo off - Disable VC tracking\n"
            "• /vcinfo - Show current VC members\n"
            "• /vcinfo settings - Show this settings page"
        )

    if len(args) == 2 and args[1].lower() in ["on", "enable"]:
        if chat_id in VC_TRACKING_ENABLED:
            return await message.reply_text("VC tracking is already enabled.")
        VC_TRACKING_ENABLED.add(chat_id)
        update_vc_setting(chat_id, True)
        task = asyncio.create_task(monitor_vc_changes(chat_id))
        VC_MONITOR_TASKS[chat_id] = task
        return await message.reply_text("VC tracking enabled. I’ll notify you about joins/leaves and VC state.")

    if len(args) == 2 and args[1].lower() in ["off", "disable"]:
        if chat_id not in VC_TRACKING_ENABLED:
            return await message.reply_text("VC tracking is already disabled.")
        VC_TRACKING_ENABLED.discard(chat_id)
        update_vc_setting(chat_id, False)
        remove_from_vc_cache(chat_id)
        task = VC_MONITOR_TASKS.pop(chat_id, None)
        if task:
            task.cancel()
        return await message.reply_text("VC tracking disabled and cache cleared.")

    try:
        assistant = await group_assistant(Anony, chat_id)
        if not assistant:
            return await message.reply_text("Assistant not found. Make sure it has joined the VC.")

        participants, state, errmsg = await fetch_participants(assistant, chat_id)
        if state == "no_active":
            return await message.reply_text("No active voice chat.")
        if state == "error":
            return await message.reply_text(f"Failed to fetch VC info.\nError: {errmsg}")

        if not participants:
            return await message.reply_text("No users found in the voice chat.")

        lines = []
        for p in participants:
            try:
                user = await app.get_users(p.user_id)
                name = user.mention if user else f"{p.user_id}"
            except Exception:
                name = f"{p.user_id}"
            lines.append(f"#InVC\nName: {name}\nStatus: {fmt_status_line(p)}")

        text = "\n\n".join(lines)
        text += f"\n\nTotal in VC: {len(participants)}"
        await message.reply_text(text)

    except FloodWait as fw:
        await asyncio.sleep(fw.value)
        return await vc_info(client, message)
    except Exception as e:
        await message.reply_text(f"Failed to fetch VC info.\nError: {e}")
