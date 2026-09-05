"""
Disk-based temp storage for one download -> process -> re-upload task.

Instead of letting videos pile up in Pyrogram's default downloads/ cache,
every task (a normal thumb-change, or a /MS run) gets its own throwaway
folder on disk that we fully control and always wipe afterwards. This also
adds an optional "file store channel" backup: when config.LOG_CHANNEL is
set, a copy of every processed file is forwarded there too, so a durable
copy exists on Telegram's side and not only on local disk.
"""
import os
import shutil
import uuid

import config


def get_task_dir(prefix: str = "task") -> str:
    """Create and return a fresh, uniquely-named temp directory for one task."""
    task_dir = os.path.join(config.DOWNLOAD_DIR, f"{prefix}_{uuid.uuid4().hex}")
    os.makedirs(task_dir, exist_ok=True)
    return task_dir


def cleanup_task_dir(task_dir: str) -> None:
    """Remove a task's temp directory and everything inside it. Never raises."""
    shutil.rmtree(task_dir, ignore_errors=True)


async def download_to_disk(bot, message, task_dir, file_name: str = None, progress=None, progress_args=None) -> str:
    """
    Download a Telegram media message straight into our own task_dir on
    disk, instead of Pyrogram's shared default cache folder, so the file
    lives in a place we fully own and are guaranteed to clean up.
    """
    dest = os.path.join(task_dir, file_name) if file_name else task_dir + os.sep
    return await bot.download_media(
        message=message,
        file_name=dest,
        progress=progress,
        progress_args=progress_args,
    )


async def backup_to_log_channel(bot, file_path: str, caption: str = None):
    """
    Optional 'file store channel' backup. Forwards a copy of the finished
    file to config.LOG_CHANNEL so a durable copy exists on Telegram (can be
    re-served by file_id later without downloading again). No-op if
    LOG_CHANNEL isn't configured, and never raises — this is best-effort.
    """
    if not config.LOG_CHANNEL:
        return None
    try:
        return await bot.send_document(
            chat_id=config.LOG_CHANNEL,
            document=file_path,
            caption=caption,
        )
    except Exception:
        return None
