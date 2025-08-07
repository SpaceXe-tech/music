import asyncio
import json
import os
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from config import BANNED_USERS
from DeadlineTech.core.call import Anony
from DeadlineTech.utils.admin_filters import admin_filter
from DeadlineTech.utils.database import group_assistant
from DeadlineTech import app

VC_CACHE_FILE = "vcusers.json"
VC_SETTINGS_FILE = "vcsettings.json"
VC_TRACKING_ENABLED = set()
VC_MONITOR_TASKS = {}

def load_vc_cache():
    """Load VC cache from JSON file."""
    if os.path.exists(VC_CACHE_FILE):
        try:
            with open(VC_CACHE_FILE, 'r') as f:
                data = json.load(f)
                # Convert string keys back to integers and values to sets
                return {int(k): set(v) for k, v in data.items()}
        except (json.JSONDecodeError, ValueError):
            pass
    return {}

def save_vc_cache(cache_data):
    """Save VC cache to JSON file."""
    try:
        # Convert integer keys to strings and sets to lists for JSON serialization
        json_data = {str(k): list(v) for k, v in cache_data.items()}
        with open(VC_CACHE_FILE, 'w') as f:
            json.dump(json_data, f, indent=2)
    except Exception:
        pass

def load_vc_settings():
    """Load VC settings from JSON file."""
    if os.path.exists(VC_SETTINGS_FILE):
        try:
            with open(VC_SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                # Convert string keys back to integers
                return {int(k): v for k, v in data.items()}
        except (json.JSONDecodeError, ValueError):
            pass
    return {}

def save_vc_settings(settings_data):
    """Save VC settings to JSON file."""
    try:
        # Convert integer keys to strings for JSON serialization
        json_data = {str(k): v for k, v in settings_data.items()}
        with open(VC_SETTINGS_FILE, 'w') as f:
            json.dump(json_data, f, indent=2)
    except Exception:
        pass

def get_vc_cache(chat_id):
    """Get VC cache for a specific chat."""
    cache = load_vc_cache()
    return cache.get(chat_id, set())

def update_vc_cache(chat_id, user_ids):
    """Update VC cache for a specific chat."""
    cache = load_vc_cache()
    cache[chat_id] = user_ids
    save_vc_cache(cache)

def remove_from_vc_cache(chat_id):
    """Remove a chat from VC cache."""
    cache = load_vc_cache()
    if chat_id in cache:
        del cache[chat_id]
        save_vc_cache(cache)

def get_vc_setting(chat_id):
    """Get VC tracking setting for a specific chat."""
    settings = load_vc_settings()
    return settings.get(chat_id, False)

def update_vc_setting(chat_id, enabled):
    """Update VC tracking setting for a specific chat."""
    settings = load_vc_settings()
    settings[chat_id] = enabled
    save_vc_settings(settings)

def remove_vc_setting(chat_id):
    """Remove VC setting for a specific chat."""
    settings = load_vc_settings()
    if chat_id in settings:
        del settings[chat_id]
        save_vc_settings(settings)

async def monitor_vc_changes(chat_id: int):
    """Background task to monitor voice chat changes."""
    try:
        assistant = await group_assistant(Anony, chat_id)
        if not assistant:
            raise Exception("Assistant not found or not initialized.")

        # Initial log of current VC members
        participants = await assistant.get_participants(chat_id)
        current_ids = set()
        joined_lines = []

        if participants:
            for p in participants:
                current_ids.add(p.user_id)
                try:
                    user = await app.get_users(p.user_id)
                    name = user.mention if user else f"<code>{p.user_id}</code>"
                except Exception:
                    name = f"<code>{p.user_id}</code>"

                status = ["Muted" if p.muted else "Unmuted"]
                if getattr(p, "screen_sharing", False):
                    status.append("Screen Sharing")

                vol = getattr(p, "volume", None)
                if vol:
                    status.append(f"Volume: {vol}")

                joined_lines.append(f"#InVC\n<b>Name:</b> {name}\n<b>Status:</b> {', '.join(status)}")

            if joined_lines:
                result = "\n\n".join(joined_lines)
                result += f"\n\n👥 <b>Now in VC:</b> {len(participants)}"
                try:
                    msg = await app.send_message(chat_id, result)
                    await asyncio.sleep(30)
                    await msg.delete()
                except Exception:
                    pass

        update_vc_cache(chat_id, current_ids)

        # Begin monitoring loop
        while chat_id in VC_TRACKING_ENABLED:
            await asyncio.sleep(5)

            assistant = await group_assistant(Anony, chat_id)
            if not assistant:
                raise Exception("Assistant not found or not initialized.")
            try:
                participants = await assistant.get_participants(chat_id)
            except Exception as e:
                raise Exception(f"Could not fetch participants: {e}")

            current_ids = set(p.user_id for p in participants)
            old_ids = get_vc_cache(chat_id)
            update_vc_cache(chat_id, current_ids)

            joined_lines = []
            left_lines = []

            for user_id in current_ids - old_ids:
                try:
                    user = await app.get_users(user_id)
                    name = user.mention if user else f"<code>{user_id}</code>"
                except Exception:
                    name = f"<code>{user_id}</code>"
                joined_lines.append(f"#JoinedVC\n<b>Name:</b> {name}")

            for user_id in old_ids - current_ids:
                try:
                    user = await app.get_users(user_id)
                    name = user.mention if user else f"<code>{user_id}</code>"
                except Exception:
                    name = f"<code>{user_id}</code>"
                left_lines.append(f"#LeftVC\n<b>Name:</b> {name}")

            if joined_lines or left_lines:
                result = "\n\n".join(joined_lines + left_lines)
                result += f"\n\n👥 <b>Now in VC:</b> {len(current_ids)}"
                try:
                    msg = await app.send_message(chat_id, result)
                    await asyncio.sleep(30)
                    await msg.delete()
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                    msg = await app.send_message(chat_id, result)
                    await asyncio.sleep(30)
                    await msg.delete()
                except Exception:
                    pass

    except Exception as e:
        try:
            await app.send_message(chat_id, f"❌ VC monitoring stopped due to error: {e}")
        except Exception:
            pass
        VC_TRACKING_ENABLED.discard(chat_id)
        remove_from_vc_cache(chat_id)
        update_vc_setting(chat_id, False)
        VC_MONITOR_TASKS.pop(chat_id, None)


@app.on_message(filters.command(["vcinfo", "infovc", "vclogger"]) & filters.group & admin_filter & ~BANNED_USERS)
async def vc_info(client: Client, message: Message):
    chat_id = message.chat.id
    args = message.text.split(None, 1)

    # Check if user wants to see settings
    if len(args) == 2 and args[1].lower() in ["settings", "status", "check"]:
        is_enabled = get_vc_setting(chat_id)
        status_text = "✅ **Enabled**" if is_enabled else "❌ **Disabled**"
        active_text = "🔴 **Active**" if chat_id in VC_TRACKING_ENABLED else "⚫ **Inactive**"
        
        settings_msg = f"**VC Info Settings for this Group:**\n\n"
        settings_msg += f"📊 **Status:** {status_text}\n"
        settings_msg += f"🔄 **Monitoring:** {active_text}\n\n"
        settings_msg += "**Commands:**\n"
        settings_msg += "• `/vcinfo on` - Enable VC tracking\n"
        settings_msg += "• `/vcinfo off` - Disable VC tracking\n"
        settings_msg += "• `/vcinfo` - Show current VC members\n"
        settings_msg += "• `/vcinfo settings` - Show this settings page"
        
        return await message.reply_text(settings_msg)

    if len(args) == 2 and args[1].lower() in ["on", "enable"]:
        if chat_id not in VC_TRACKING_ENABLED:
            VC_TRACKING_ENABLED.add(chat_id)
            update_vc_setting(chat_id, True)
            task = asyncio.create_task(monitor_vc_changes(chat_id))
            VC_MONITOR_TASKS[chat_id] = task
            return await message.reply_text("✅ VC tracking enabled for this group. Now I'll track & notify #JoinedVC and #LeftVC users.")
        return await message.reply_text("✅ VC tracking is already enabled.")

    elif len(args) == 2 and args[1].lower() in ["off", "disable"]:
        if chat_id in VC_TRACKING_ENABLED:
            VC_TRACKING_ENABLED.discard(chat_id)
            remove_from_vc_cache(chat_id)
            update_vc_setting(chat_id, False)
            if chat_id in VC_MONITOR_TASKS:
                VC_MONITOR_TASKS[chat_id].cancel()
                VC_MONITOR_TASKS.pop(chat_id, None)
            return await message.reply_text("❌ VC tracking disabled and cache cleared.")
        return await message.reply_text("❌ VC tracking is already disabled.")

    try:
        assistant = await group_assistant(Anony, chat_id)
        if not assistant:
            return await message.reply_text("❌ Assistant not found. Make sure it has joined the VC.")
        participants = await assistant.get_participants(chat_id)

        if not participants:
            if chat_id not in VC_TRACKING_ENABLED:
                return await message.reply_text("❌ No users found in the voice chat.")
            else:
                update_vc_cache(chat_id, set())
                return

        current_ids = set()
        joined_lines = []

        for p in participants:
            user_id = p.user_id
            current_ids.add(user_id)

            if chat_id not in VC_TRACKING_ENABLED:
                try:
                    user = await app.get_users(user_id)
                    name = user.mention if user else f"<code>{user_id}</code>"
                except Exception:
                    name = f"<code>{user_id}</code>"

                status = ["Muted" if p.muted else "Unmuted"]
                if getattr(p, "screen_sharing", False):
                    status.append("Screen Sharing")

                vol = getattr(p, "volume", None)
                if vol:
                    status.append(f"Volume: {vol}")

                joined_lines.append(f"#InVC\n<b>Name:</b> {name}\n<b>Status:</b> {', '.join(status)}")

        if joined_lines:
            result = "\n\n".join(joined_lines)
            result += f"\n\n👥 <b>Total in VC:</b> {len(participants)}"
            await message.reply_text(result)

    except FloodWait as fw:
        await asyncio.sleep(fw.value)
        return await vc_info(client, message)
    except Exception as e:
        await message.reply_text(f"❌ Failed to fetch VC info.\n<b>Error:</b> {e}")


# Auto-load VC tracking on bot startup using event decorator
@app.on_ready()
async def load_vc_tracking_on_startup():
    """Load VC tracking enabled chats on bot startup."""
    print("🔄 Loading VC tracking settings...")
    settings = load_vc_settings()
    loaded_count = 0
    
    for chat_id, enabled in settings.items():
        if enabled:
            try:
                VC_TRACKING_ENABLED.add(chat_id)
                # Restart monitoring task
                task = asyncio.create_task(monitor_vc_changes(chat_id))
                VC_MONITOR_TASKS[chat_id] = task
                loaded_count += 1
            except Exception as e:
                print(f"❌ Failed to load VC tracking for chat {chat_id}: {e}")
    
    print(f"✅ VC tracking Sets loaded for {loaded_count} chats!")
