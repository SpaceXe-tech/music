from pyrogram import Client
import config
from ..logging import LOGGER

assistants = []
assistantids = []


class Userbot(Client):
    def __init__(self):
        self.one = Client(
            name="DeadlineXAss1",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING1),
            no_updates=True,
        )
        self.two = Client(
            name="DeadlineXAss2",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING2),
            no_updates=True,
        )
        self.three = Client(
            name="DeadlineXAss3",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING3),
            no_updates=True,
        )
        self.four = Client(
            name="DeadlineXAss4",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING4),
            no_updates=True,
        )
        self.five = Client(
            name="DeadlineXAss5",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING5),
            no_updates=True,
        )

    async def start(self):
        LOGGER(__name__).info("🚀 Starting assistant clients...")

        async def setup_assistant(client, number):
            try:
                await client.start()
                # warm up self info for later attributes
                await client.get_me()
                # best-effort joins (ignore failures)
                try:
                    await client.join_chat("BillaSpace")
                except Exception:
                    pass
                try:
                    await client.join_chat("BillaCore")
                except Exception:
                    pass
            except Exception as e:
                LOGGER(__name__).error(f"Assistant {number} failed to start: {type(e).__name__}: {e}")
                return

            assistants.append(number)

            # --- ensure LOGGER_ID is int before sending ---
            try:
                log_id = int(config.LOGGER_ID)
            except Exception:
                LOGGER(__name__).error(f"LOGGER_ID must be an integer, got: {config.LOGGER_ID!r}")
                return

            # try to send the online message; show the real reason on failure
            try:
                await client.send_message(log_id, f"✅ Assistant {number} is now online.")
            except Exception as e:
                LOGGER(__name__).error(
                    f"❌ Assistant {number} failed to send a message to the log group {log_id}: "
                    f"{type(e).__name__}: {e}"
                )
                # don't kill the whole app; just skip this assistant
                return

            # cache identity fields
            client.id = client.me.id
            client.name = client.me.mention
            client.username = client.me.username
            assistantids.append(client.id)

            LOGGER(__name__).info(f"🤖 Assistant {number} is active as {client.name}")

        if config.STRING1:
            await setup_assistant(self.one, 1)
        if config.STRING2:
            await setup_assistant(self.two, 2)
        if config.STRING3:
            await setup_assistant(self.three, 3)
        if config.STRING4:
            await setup_assistant(self.four, 4)
        if config.STRING5:
            await setup_assistant(self.five, 5)

        LOGGER(__name__).info("✅ All available assistants are now online.")

    async def stop(self):
        LOGGER(__name__).info("🛑 Shutting down assistant clients...")
        try:
            if config.STRING1:
                await self.one.stop()
            if config.STRING2:
                await self.two.stop()
            if config.STRING3:
                await self.three.stop()
            if config.STRING4:
                await self.four.stop()
            if config.STRING5:
                await self.five.stop()
        except Exception as e:
            LOGGER(__name__).warning(f"⚠️ Error while stopping assistants: {e}")
