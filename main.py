import os, time
from display_progress import progress_for_pyrogram
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyromod import listen

import config
import storage
import promo_remover

BOT_TOKEN = ""
API_ID = "22518279"
API_HASH = "61e5cc94bc5e6318643707054e54caf4"

Bot = Client(
    "Thumb-Bot",
    bot_token = BOT_TOKEN,
    api_id = API_ID,
    api_hash = API_HASH
)

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

@Bot.on_message(filters.private & (filters.video | filters.document))
async def thumb_change(bot, m):
    global thumb
    task_dir = storage.get_task_dir("thumb")
    try:
        msg = await m.reply("`Downloading..`")
        c_time = time.time()
        # Downloaded straight to our own temp folder on disk (task_dir)
        # instead of Pyrogram's shared default cache, so the file lives
        # somewhere we fully control and is guaranteed to get cleaned up.
        file_dl_path = await storage.download_to_disk(bot, m, task_dir, progress=progress_for_pyrogram, progress_args=("Downloading file..", msg, c_time))
        await msg.delete()
        answer = await bot.ask(m.chat.id,'Now send the thumbnail' + ' or /keep to keep the previous thumb' if thumb else '', filters=filters.photo | filters.text)
        if answer.photo:
            try:
                os.remove(thumb)
            except:
                pass
            thumb = await bot.download_media(message=answer.photo)
        msg = await m.reply("`Uploading..`")
        c_time = time.time()
        if m.document:
            sent = await bot.send_document(chat_id=m.chat.id, document=file_dl_path, thumb=thumb, caption=m.caption if m.caption else None, progress=progress_for_pyrogram, progress_args=("Uploading file..", msg, c_time))
        elif m.video:
            sent = await bot.send_video(chat_id=m.chat.id, video=file_dl_path, thumb=thumb, caption=m.caption if m.caption else None, progress=progress_for_pyrogram, progress_args=("Uploading file..", msg, c_time))
        await msg.delete()
        # optional file-store channel backup (no-op unless config.LOG_CHANNEL is set)
        await storage.backup_to_log_channel(bot, file_dl_path, caption="Thumb-change backup")
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

    task_dir = storage.get_task_dir("ms")
    try:
        msg = await answer.reply("`Downloading..`")
        c_time = time.time()
        file_dl_path = await storage.download_to_disk(bot, answer, task_dir, progress=progress_for_pyrogram, progress_args=("Downloading file..", msg, c_time))
        await msg.edit("`Cleaning up the cover..`")

        clean_thumb = promo_remover.make_clean_thumbnail(file_dl_path, task_dir)

        msg2 = await answer.reply("`Uploading..`")
        c_time = time.time()
        if answer.document:
            sent = await bot.send_document(chat_id=m.chat.id, document=file_dl_path, thumb=clean_thumb, caption=answer.caption if answer.caption else None, progress=progress_for_pyrogram, progress_args=("Uploading file..", msg2, c_time))
        else:
            sent = await bot.send_video(chat_id=m.chat.id, video=file_dl_path, thumb=clean_thumb, caption=answer.caption if answer.caption else None, progress=progress_for_pyrogram, progress_args=("Uploading file..", msg2, c_time))
        await msg.delete()
        await msg2.delete()
        # optional file-store channel backup (no-op unless config.LOG_CHANNEL is set)
        await storage.backup_to_log_channel(bot, file_dl_path, caption="/MS clean copy")
    finally:
        storage.cleanup_task_dir(task_dir)


Bot.run()
