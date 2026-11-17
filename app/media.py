"""Utilidades de audio/video basadas en FFmpeg."""
import json
import subprocess
from pathlib import Path

from . import config


class MediaError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int = 1800) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise MediaError(f"FFmpeg falló: {p.stderr.strip()[-600:]}")
    return p.stdout


def probe(path: Path) -> dict:
    out = _run(["ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path)], timeout=120)
    return json.loads(out)


def duration(path: Path) -> float:
    info = probe(path)
    d = info.get("format", {}).get("duration")
    if d in (None, "N/A"):
        # webm grabado en navegador a veces no trae duración en el contenedor
        for s in info.get("streams", []):
            if s.get("duration") not in (None, "N/A"):
                return float(s["duration"])
        return 0.0
    return float(d)


def has_stream(path: Path, kind: str) -> bool:
    return any(s.get("codec_type") == kind for s in probe(path).get("streams", []))


def normalize_enrollment(src: Path, dst: Path) -> None:
    """Video de aprendizaje → MP4 H.264, 25 fps constantes, alto máx. configurable, sin audio."""
    h = config.ENROLL_MAX_HEIGHT
    vf = f"scale=-2:'min({h},ih)':flags=lanczos,fps={config.FPS},format=yuv420p"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
          "-t", str(config.MAX_ENROLL_SECONDS), "-vf", vf, "-an",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", str(dst)])


def normalize_audio(src: Path, dst: Path) -> None:
    """Cualquier audio (o video con audio) → WAV PCM 16 kHz mono, volumen normalizado."""
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn",
          "-t", str(config.MAX_AUDIO_SECONDS),
          "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
          "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])


def thumbnail(src: Path, dst: Path, at: float = 1.0) -> None:
    _run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(src),
          "-frames:v", "1", "-vf", "scale=320:-2", str(dst)])


def finalize_video(src: Path, audio: Path, dst: Path, watermark: bool) -> None:
    """Re-multiplexa con el audio original en AAC y, opcionalmente, añade marca de agua."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(audio),
           "-map", "0:v:0", "-map", "1:a:0"]
    # El motor puede producir unos cuadros menos que el audio: se congela el último
    # cuadro (máx. 1 s) para no recortar el final de la voz.
    filters = ["tpad=stop_mode=clone:stop_duration=1"]
    if watermark and config.WATERMARK_TEXT:
        text = config.WATERMARK_TEXT.replace(":", r"\:").replace("'", "")
        font = f"fontfile={config.FONT_FILE}:" if Path(config.FONT_FILE).exists() else ""
        filters.append(f"drawtext={font}text='{text}':fontcolor=white@0.85:fontsize=h/28:"
                       f"box=1:boxcolor=black@0.45:boxborderw=8:x=w-tw-20:y=h-th-20")
    cmd += ["-vf", ",".join(filters)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(dst)]
    _run(cmd)
