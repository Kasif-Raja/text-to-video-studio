import hashlib
import os
import time
from collections import deque
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont


PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
RATE_LIMIT_SLOTS = deque(maxlen=3)


def apply_rate_limit() -> None:
    now = time.monotonic()
    if RATE_LIMIT_SLOTS:
        elapsed = now - RATE_LIMIT_SLOTS[-1]
        if elapsed < 0.9:
            time.sleep(0.9 - elapsed)
    RATE_LIMIT_SLOTS.append(now)


def make_placeholder_image(keyword: str, output_path: Path) -> str:
    width, height = 1920, 1080
    seed = int(hashlib.md5(keyword.encode("utf-8")).hexdigest()[:8], 16)
    bg = (20 + (seed % 30), 25 + ((seed // 5) % 30), 35 + ((seed // 9) % 40))
    hue = seed % 360
    accent = (
        int((hue * 0.7) % 256),
        int((hue * 0.5 + 30) % 256),
        int((hue * 0.35 + 60) % 256),
    )

    image = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(image)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for i in range(1, 9):
        x1 = i * 200
        y1 = i * 120
        overlay_draw.rectangle([x1, y1, x1 + 900, y1 + 520], outline=accent, width=2)
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    lines = [keyword[:40].strip()] if keyword else ["Scene"]
    if len(keyword) > 40:
        lines = [keyword[:40].strip(), keyword[40:80].strip()]
    if not lines[0]:
        lines = ["Story frame"]

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 100)
    text = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=12)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (width - text_width) / 2
    y = (height - text_height) / 2 - 30

    draw.multiline_text((x, y), text, fill=(255, 255, 255), font=font, spacing=12, align="center")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return str(output_path)


def fetch_pexels_photo(keyword: str, output_path: Path) -> Optional[str]:
    if not PEXELS_API_KEY:
        return None

    try:
        apply_rate_limit()
        response = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": keyword, "per_page": 1, "orientation": "landscape"},
            timeout=20,
        )
        if response.status_code != 200:
            return None

        payload = response.json()
        photos = payload.get("photos", [])
        if not photos:
            return None

        photo = photos[0]
        image_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
        if not image_url:
            return None

        image_response = requests.get(image_url, timeout=30)
        if image_response.status_code != 200:
            return None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as image_file:
            image_file.write(image_response.content)

        try:
            with Image.open(output_path) as img:
                image = img.convert("RGB").resize((1920, 1080), Image.LANCZOS)
                image.save(output_path, format="JPEG", quality=88, optimize=True)
        except Exception:
            pass

        return str(output_path)
    except Exception:
        return None


def generate_scene_image(keyword: str, output_dir: Path, scene_index: int) -> str:
    safe_keyword = (keyword or "story scene").strip()
    output_path = output_dir / f"scene_{scene_index:03d}_visual.jpg"
    pexels_image = fetch_pexels_photo(safe_keyword, output_path)
    if pexels_image:
        return pexels_image

    fallback_path = output_dir / f"scene_{scene_index:03d}_fallback.png"
    return make_placeholder_image(safe_keyword, fallback_path)
