import re
import os

# ── Disk storage for downloads ──────────────────────────────────────────
# Every download/re-upload task (normal thumb-change flow or /MS) gets its
# own throwaway subfolder under this directory (see storage.get_task_dir).
# Nothing here is meant to survive beyond a single task — it's deleted
# right after the file is re-sent, success or failure.
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloads")

# Optional "file store channel": id of a private channel/group the bot is
# admin of. When set (a real chat id, not 0), every file the bot re-sends
# also gets forwarded there as a durable backup living on Telegram's side
# instead of only on local disk. Leave as 0 to disable this completely.
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1004367489178") or 0)

# ── Promo / watermark removal (used by the /MS command) ────────────────
# Any OCR text found on the auto-generated video-cover frame that matches
# one of these is treated as a reseller/promo tag and erased. Add more
# handles or phrases any time a new tag shows up — no code change needed,
# just add a line here.
PROMO_KEYWORDS = [
    "THEKMX",
    "RIYO",
    "SumitTripathi",
]

# Generic patterns that catch "@anything" style channel handles, t.me
# links and "join our channel" banners even when the exact handle isn't
# in PROMO_KEYWORDS above — this is what makes removal work for "any
# other" tag, not just the one example seen so far.
PROMO_PATTERNS = [
    re.compile(r"@[A-Za-z0-9_]{3,32}"),
    re.compile(r"t\.me/\S+", re.IGNORECASE),
    re.compile(r"\bjoin\b.{0,20}\bchannel\b", re.IGNORECASE),
]

# Which second of the video to grab as the base thumbnail frame for /MS.
THUMB_FRAME_SECOND = float(os.environ.get("THUMB_FRAME_SECOND", "2"))
