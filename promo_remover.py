"""
Auto-thumbnail generation for /MS.

Grabs a frame straight out of the video itself (this becomes the cover,
same as Telegram's own auto-thumbnail would), then erases only the promo /
reseller tag text burned into that frame (things like "@THEKMX", other
@handles, t.me links, "join our channel" banners...) using OCR text
detection + OpenCV inpainting. Only the pixels of the matched text are
touched — everything else in the frame (lecture title cards, branding,
etc.) is left exactly as it was. The video file itself is never re-encoded
or modified — only the still-image cover is.
"""
import os

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

import config


def grab_frame(video_path: str, out_path: str, second: float = None):
    """Pull a single frame from the video and save it as a JPEG. Returns
    out_path on success, None if the video couldn't be read at all."""
    if second is None:
        second = config.THUMB_FRAME_SECOND

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    target_frame = int(second * fps)
    if frame_count and target_frame >= frame_count:
        target_frame = int(frame_count // 2)

    cap.set(cv2.CAP_PROP_POS_FRAMES, max(target_frame, 0))
    ok, frame = cap.read()
    if not ok:
        # fall back to the very first frame if seeking failed
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = cap.read()
    cap.release()

    if not ok:
        return None
    cv2.imwrite(out_path, frame)
    return out_path


def _is_promo_text(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    upper = text.upper()
    for kw in config.PROMO_KEYWORDS:
        if kw.upper() in upper:
            return True
    for pattern in config.PROMO_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _detect_promo_boxes(image, min_conf: int = 30):
    """
    Runs OCR and groups words back into their original text lines (Tesseract
    gives us block/paragraph/line numbers), then checks each *line* against
    the promo rules. Grouping by line (instead of per-word) means a tag like
    "@ THEKMX" that OCR splits into two tokens still gets matched and fully
    erased together, not just the half that happened to match on its own.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Bold overlay text tends to be high-contrast against the video frame;
    # a small contrast boost helps Tesseract pick it out from a busy scene.
    gray = cv2.convertScaleAbs(gray, alpha=1.3, beta=10)

    try:
        data = pytesseract.image_to_data(gray, output_type=Output.DICT)
    except Exception as e:
        # Most commonly pytesseract.TesseractNotFoundError — the tesseract-ocr
        # system package isn't installed on this host (see requirements.txt).
        # Degrade gracefully instead of crashing the whole /MS flow: treat it
        # as "no promo text found" so the video still gets sent back with its
        # plain, unedited cover rather than failing outright.
        print(f"[promo_remover] OCR unavailable, skipping text removal: {e}")
        return []

    lines = {}
    for i in range(len(data["text"])):
        text = (data["text"][i] or "").strip()
        conf_raw = str(data["conf"][i])
        conf = int(conf_raw) if conf_raw.lstrip("-").isdigit() else -1
        if not text or conf < min_conf:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        lines.setdefault(key, {"boxes": [], "texts": []})
        lines[key]["boxes"].append((x, y, w, h))
        lines[key]["texts"].append(text)

    promo_boxes = []
    for line in lines.values():
        full_text = " ".join(line["texts"])
        if not _is_promo_text(full_text):
            continue
        xs0 = min(b[0] for b in line["boxes"])
        ys0 = min(b[1] for b in line["boxes"])
        xs1 = max(b[0] + b[2] for b in line["boxes"])
        ys1 = max(b[1] + b[3] for b in line["boxes"])
        promo_boxes.append((xs0, ys0, xs1 - xs0, ys1 - ys0))
    return promo_boxes


def remove_promo_text(frame_path: str, out_path: str, padding: int = 8) -> bool:
    """Erase only the detected promo-text regions from the frame. Returns
    True if anything was actually found and removed."""
    image = cv2.imread(frame_path)
    if image is None:
        return False

    boxes = _detect_promo_boxes(image)
    if not boxes:
        cv2.imwrite(out_path, image)
        return False

    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    for x, y, w, h in boxes:
        x0, y0 = max(x - padding, 0), max(y - padding, 0)
        x1 = min(x + w + padding, image.shape[1])
        y1 = min(y + h + padding, image.shape[0])
        mask[y0:y1, x0:x1] = 255

    cleaned = cv2.inpaint(image, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
    cv2.imwrite(out_path, cleaned)
    return True


def _fit_telegram_thumb(src_path: str, dst_path: str) -> str:
    """Resize/compress to what Telegram accepts as a video thumb: JPEG,
    <=320px on the long side, under 200KB."""
    image = cv2.imread(src_path)
    h, w = image.shape[:2]
    scale = 320 / max(h, w)
    if scale < 1:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    quality = 90
    buf = None
    while quality > 30:
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok and buf.nbytes < 200 * 1024:
            break
        quality -= 10

    with open(dst_path, "wb") as f:
        f.write(buf.tobytes())
    return dst_path


def make_clean_thumbnail(video_path: str, task_dir: str):
    """
    Full /MS pipeline: grab a frame from the video, strip any promo text
    from it, fit it to Telegram's thumbnail limits, and return the path.
    Returns None if a frame couldn't even be read from the video.
    """
    raw_frame = os.path.join(task_dir, "raw_frame.jpg")
    if grab_frame(video_path, raw_frame) is None:
        return None

    cleaned_frame = os.path.join(task_dir, "clean_frame.jpg")
    remove_promo_text(raw_frame, cleaned_frame)

    return _fit_telegram_thumb(cleaned_frame, os.path.join(task_dir, "thumb.jpg"))
