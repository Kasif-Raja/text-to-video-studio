import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from services.image_service import generate_scene_image
from services.tts_service import (
    get_audio_duration_seconds,
    get_voice_for_text,
    render_tts_audio,
    split_script_to_scenes,
)
from services.video_service import build_video_from_scenes, cleanup_job_directory


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
TMP_ROOT = Path("/tmp/text_to_video_jobs")
TMP_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Video Studio", version="1.0.0")
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")

JOB_REGISTRY: Dict[str, Dict[str, Any]] = {}
JOB_LOCK = asyncio.Lock()


class SceneRequest(BaseModel):
    text: str = Field(..., min_length=10)
    keyword: str = ""


class JobRequest(BaseModel):
    script: str = Field(..., min_length=20)
    voice: str = "auto"
    scenes: Optional[List[SceneRequest]] = None
    max_duration_seconds: int = 600


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_scenes(script: str, override_scenes: Optional[List[SceneRequest]] = None) -> List[Dict[str, Any]]:
    if override_scenes:
        normalized: List[Dict[str, Any]] = []
        for scene in override_scenes:
            text = scene.text.strip()
            if not text:
                continue
            normalized.append({
                "text": text,
                "keyword": (scene.keyword or "").strip() or text[:60],
            })
        if normalized:
            return normalized

    return split_script_to_scenes(script)


async def update_job(job_id: str, **changes: Any) -> Dict[str, Any]:
    async with JOB_LOCK:
        job = JOB_REGISTRY.get(job_id)
        if not job:
            raise KeyError(job_id)
        for key, value in changes.items():
            job[key] = value
        job["updated_at"] = utc_now()
        return job


async def process_video_job(job_id: str, request: JobRequest) -> None:
    job_dir = TMP_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        await update_job(job_id, status="processing", progress=5, error=None, output_path=None)

        scenes = normalize_scenes(request.script, request.scenes)
        if not scenes:
            raise ValueError("No valid scenes were generated from the script.")

        prepared_scenes: List[Dict[str, Any]] = []
        total_estimated = 0.0

        for index, scene in enumerate(scenes):
            text = scene["text"].strip()
            keyword = (scene.get("keyword") or text[:60]).strip() or "story scene"
            voice = get_voice_for_text(text, request.voice)

            image_path = generate_scene_image(keyword, job_dir, index)
            audio_path = str(job_dir / f"scene_{index:03d}.mp3")
            await render_tts_audio(text, voice, audio_path)
            duration = get_audio_duration_seconds(audio_path)

            prepared_scenes.append({
                "index": index,
                "text": text,
                "keyword": keyword,
                "voice": voice,
                "image_path": image_path,
                "audio_path": audio_path,
                "duration": duration,
            })

            total_estimated += duration
            if total_estimated > max(10, request.max_duration_seconds):
                raise ValueError("Generated video exceeds the allowed maximum duration limit of 10 minutes.")

            progress = min(95, 10 + int((index + 1) / max(1, len(scenes)) * 75))
            await update_job(job_id, progress=progress)

        final_video = build_video_from_scenes(job_dir, prepared_scenes)
        await update_job(
            job_id,
            status="completed",
            progress=100,
            output_path=final_video,
            final_duration=total_estimated,
            scenes=prepared_scenes,
            completed_at=utc_now(),
        )

    except Exception as exc:
        await update_job(job_id, status="failed", progress=100, error=str(exc), failed_at=utc_now())
    finally:
        try:
            current = JOB_REGISTRY.get(job_id)
            if current and current.get("status") in {"completed", "failed"}:
                cleanup_job_directory(job_dir)
        except Exception:
            pass


@app.get("/")
async def index() -> FileResponse:
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index file not found.")
    return FileResponse(str(index_file))


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "jobs": len(JOB_REGISTRY)})


@app.post("/api/submit")
async def submit_job(payload: JobRequest) -> JSONResponse:
    job_id = str(uuid.uuid4())
    JOB_REGISTRY[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "error": None,
        "output_path": None,
        "scenes": [],
        "final_duration": 0.0,
    }

    asyncio.create_task(process_video_job(job_id, payload))
    return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    job = JOB_REGISTRY.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    payload = {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "error": job.get("error"),
        "final_duration": job.get("final_duration", 0.0),
    }
    if job.get("status") == "completed" and job.get("output_path"):
        payload["download_url"] = f"/api/download/{job_id}"
    return JSONResponse(payload)


@app.get("/api/download/{job_id}")
async def download_job(job_id: str) -> FileResponse:
    job = JOB_REGISTRY.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    output_path = job.get("output_path")
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=404, detail="Video is not ready yet or has expired.")

    return FileResponse(output_path, media_type="video/mp4", filename=f"{job_id}.mp4")
