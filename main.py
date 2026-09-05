import os, time, threading, asyncio
from display_progress import progress_for_pyrogram
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyromod import listen
from flask import Flask

import config
import storage
import promo_remover

# Must come from environment variables — if these are left blank, Pyrogram
# falls back to *interactively* asking for them on stdin, which is what was
# crashing the Render deploy with "EOFError: EOF when reading a line"
# (Render's process has no stdin to answer that prompt).
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")

Bot = Client(
    "Thumb-Bot",
    bot_token = BOT_TOKEN,
    api_id = API_ID,
    api_hash = API_HASH
)

# ─── Flask keep-alive server for Render ───────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return 'Bot is running!'

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

# Start Flask in background thread so Render detects open port
threading.Thread(target=run_flask, daemon=True).start()
# ─────────────────────────────────────────

START_TXT = """
Hi {}, I am video thumbnail changer Bot.

Send a video/file to get started.
Or use /MS to strip a promo/watermark tag from a video's cover without changing anything else.
"""

START_BTN = InlineKeyboardMarkup(
        [[
        InlineKeyboardButton('Source Code', url='https://github.com/soebb/thumb-change-bot'),
        ]]
    )


@Bot.on_message(filters.command(["start"]))
async def start(bot, update):
    text = START_TXT.format(update.from_user.mention)
    reply_markup = START_BTN
    await update.reply_text(
        text=text,
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )


# global variable to store path of the recent sended thumbnail
thumb = ""


async def _delete_after(message, seconds):
    """Delete a status message after a short delay, without blocking anything else."""
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except Exception:
        pass


@Bot.on_message(filters.private & (filters.video | filters.document))
async def thumb_change(bot, m):
    global thumb

    # Instant file-store backup: forward the ORIGINAL message straight to
    # the log channel server-side. This costs no download time at all —
    # it's Telegram copying the file on its own servers, not our bot
    # pulling bytes down. No-op if config.LOG_CHANNEL isn't set.
    asyncio.create_task(storage.forward_to_log_channel(bot, m))

    task_dir = storage.get_task_dir("thumb")
    try:
        msg = await m.reply("`Downloading..`")
        c_time = time.time()
        # This download IS still needed for the actual thumb-change: Telegram
        # only lets you attach a new thumbnail when the file is freshly
        # uploaded (multipart), never when reusing an existing file_id — so
        # there's no way to skip pulling the bytes down if the cover has to
        # change. Downloaded straight into our own task_dir on disk (not
        # Pyrogram's shared cache) so it's guaranteed to get cleaned up.
        file_dl_path = await storage.download_to_disk(bot, m, task_dir, progress=progress_for_pyrogram, progress_args=("Downloading file..", msg, c_time))
        await msg.delete()

        # NOTE: this was previously `'a' + 'b' if thumb else ''`, which due to
        # Python operator precedence evaluates as `('a' + 'b') if thumb else
        # ''` — so whenever `thumb` was empty (e.g. right after a fresh
        # deploy) this sent an EMPTY string to bot.ask(), and Telegram
        # rejected it with "400 MESSAGE_EMPTY", crashing the handler. Fixed
        # by parenthesizing the optional part explicitly.
        prompt = "Now send the thumbnail" + (" or /keep to keep the previous thumb" if thumb else "")
        answer = await bot.ask(m.chat.id, prompt, filters=filters.photo | filters.text)
        if answer.photo:
            try:
                os.remove(thumb)
            except:
                pass
            thumb = await bot.download_media(message=answer.photo)
            saved_msg = await answer.reply("Cover Saved ✅")
            asyncio.create_task(_delete_after(saved_msg, 7))

        msg = await m.reply("`Uploading..`")
        c_time = time.time()
        if m.document:
            sent = await bot.send_document(chat_id=m.chat.id, document=file_dl_path, thumb=thumb, caption=m.caption if m.caption else None, progress=progress_for_pyrogram, progress_args=("Uploading file..", msg, c_time))
        elif m.video:
            sent = await bot.send_video(chat_id=m.chat.id, video=file_dl_path, thumb=thumb, caption=m.caption if m.caption else None, progress=progress_for_pyrogram, progress_args=("Uploading file..", msg, c_time))
        await msg.delete()
    finally:
        storage.cleanup_task_dir(task_dir)


@Bot.on_message(filters.private & filters.command(["ms", "MS"]))
async def remove_promo(bot, m):
    """
    /MS — send a video right after this command and get it back with its
    cover's promo/watermark tag erased. No custom thumbnail needed: the
    default cover Telegram would have shown is used, just cleaned up.
    """
    answer = await bot.ask(m.chat.id, "Send the video/file — I'll remove the promo tag from its cover and send it back.", filters=filters.video | filters.document)

    # Instant file-store backup of the original, same as the normal flow —
    # a server-side forward, no download involved.
    asyncio.create_task(storage.forward_to_log_channel(bot, answer))

    task_dir = storage.get_task_dir("ms")
    try:
        msg = await answer.reply("`Downloading..`")
        c_time = time.time()
        # Still required: cleaning the cover means editing an actual image
        # and re-attaching it, which — same as the normal flow — Telegram
        # only accepts on a fresh multipart upload, not on an existing file_id.
        file_dl_path = await storage.download_to_disk(bot, answer, task_dir, progress=progress_for_pyrogram, progress_args=("Downloading file..", msg, c_time))
        await msg.edit("`Cleaning up the cover..`")

        clean_thumb = promo_remover.make_clean_thumbnail(file_dl_path, task_dir)
        if clean_thumb is None:
            await msg.edit("`Couldn't read a cover frame from this file, sending it back unchanged..`")

        msg2 = await answer.reply("`Uploading..`")
        c_time = time.time()
        if answer.document:
            sent = await bot.send_document(chat_id=m.chat.id, document=file_dl_path, thumb=clean_thumb, caption=answer.caption if answer.caption else None, progress=progress_for_pyrogram, progress_args=("Uploading file..", msg2, c_time))
        else:
            sent = await bot.send_video(chat_id=m.chat.id, video=file_dl_path, thumb=clean_thumb, caption=answer.caption if answer.caption else None, progress=progress_for_pyrogram, progress_args=("Uploading file..", msg2, c_time))
        await msg.delete()
        await msg2.delete()
    finally:
        storage.cleanup_task_dir(task_dir)


Bot.run()
