import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import edge_tts


def normalize_whitespace(text: str) -> str:
    return " ".join(text.strip().split())


def infer_scene_keyword(text: str) -> str:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return "story scene"

    words = re.findall(r"[A-Za-z0-9\u0900-\u097F]+", cleaned)
    if not words:
        return "story scene"

    keyword = " ".join(words[:8])
    return keyword[:80] if len(keyword) > 80 else keyword


def split_script_to_scenes(script: str, max_chars_per_scene: int = 420) -> List[Dict[str, Any]]:
    if not script or not script.strip():
        raise ValueError("Script cannot be empty.")

    paragraphs = re.split(r"\n{2,}|\r\n{2,}", script.strip())
    chunks: List[str] = []

    for paragraph in paragraphs:
        sentence_parts = re.split(r"(?<=[.!?])\s+|\n+", paragraph)
        for part in sentence_parts:
            cleaned = normalize_whitespace(part)
            if cleaned:
                chunks.append(cleaned)

    scenes: List[Dict[str, Any]] = []
    current = ""

    for chunk in chunks:
        if len(current) + len(chunk) + 1 <= max_chars_per_scene:
            current = f"{current} {chunk}".strip() if current else chunk
        else:
            if current:
                scenes.append({"text": current, "keyword": infer_scene_keyword(current)})
            current = chunk

    if current:
        scenes.append({"text": current, "keyword": infer_scene_keyword(current)})

    if not scenes:
        normalized = normalize_whitespace(script)
        scenes.append({"text": normalized, "keyword": infer_scene_keyword(normalized)})

    return scenes


def get_voice_for_text(text: str, preferred_voice: str = "auto") -> str:
    if preferred_voice and preferred_voice != "auto":
        return preferred_voice

    if re.search(r"[\u0900-\u097F]", text):
        return "hi-IN-MadhurNeural"

    return "en-US-ChristopherNeural"


async def render_tts_audio(text: str, voice: str, output_path: str) -> str:
    text = normalize_whitespace(text)
    if not text:
        raise ValueError("Text cannot be empty for voiceover generation.")

    audio_data = bytearray()
    communicate = edge_tts.Communicate(text, voice)

    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio_blob = chunk.get("data")
            if isinstance(audio_blob, (bytes, bytearray)):
                audio_data.extend(audio_blob)

    if not audio_data:
        raise RuntimeError(f"Failed to generate audio for text: {text[:120]}")

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(bytes(audio_data))
    return str(output_file)


def get_audio_duration_seconds(audio_path: str) -> float:
    path = Path(audio_path)
    if not path.exists():
        return 1.5

    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=False, timeout=30)
        if result.returncode != 0:
            return 1.5
        value = result.stdout.strip()
        if not value:
            return 1.5
        return max(1.0, float(value))
    except (subprocess.TimeoutExpired, ValueError):
        return 1.5
