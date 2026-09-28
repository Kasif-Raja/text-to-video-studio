import shutil
import subprocess
from pathlib import Path
from typing import Dict, List


def build_scene_video(scene: Dict[str, str], scene_index: int, output_dir: Path) -> str:
    image_path = scene.get("image_path")
    audio_path = scene.get("audio_path")
    duration = float(scene.get("duration") or 3.0)

    if not image_path or not audio_path:
        raise ValueError(f"Scene {scene_index} is missing visual or audio assets.")

    scene_output = output_dir / f"scene_{scene_index:03d}.mp4"
    frames = max(25, int(round(duration * 25)))

    ffmpeg_command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-framerate",
        "25",
        "-t",
        str(duration),
        "-i",
        str(image_path),
        "-i",
        str(audio_path),
        "-vf",
        (
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
            f"zoompan=z='min(zoom+0.0007,1.15)':d={frames}:s=1920x1080:fps=25,"
            "format=yuv420p"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "25",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        "-shortest",
        str(scene_output),
    ]

    try:
        subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"FFmpeg timed out while rendering scene {scene_index}.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"FFmpeg failed for scene {scene_index}: {stderr}") from exc

    return str(scene_output)


def concatenate_videos(scene_paths: List[str], output_file: str) -> str:
    if not scene_paths:
        raise ValueError("No scenes were generated for concatenation.")

    concat_file = Path(output_file).parent / "concat_list.txt"
    with open(concat_file, "w", encoding="utf-8") as handle:
        for path in scene_paths:
            handle.write(f"file '{Path(path).as_posix()}'\n")

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(output_file),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=420)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("FFmpeg timed out while concatenating the final MP4.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"FFmpeg concat failed: {stderr}") from exc

    return str(output_file)


def build_video_from_scenes(job_dir: Path, scenes: List[Dict[str, str]]) -> str:
    job_dir.mkdir(parents=True, exist_ok=True)

    rendered_paths: List[str] = []
    for index, scene in enumerate(scenes):
        rendered_paths.append(build_scene_video(scene, index, job_dir))

    final_output = job_dir / "final_output.mp4"
    concatenate_videos(rendered_paths, str(final_output))
    return str(final_output)


def cleanup_job_directory(job_dir: Path) -> None:
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
