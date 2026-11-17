"""Cola de trabajos con un único trabajador (la GPU procesa un trabajo a la vez).

El estado se persiste en JSON para sobrevivir a reinicios del contenedor.
"""
import json
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Callable

from . import config

_lock = threading.Lock()
_queue: "queue.Queue[tuple[str, Callable]]" = queue.Queue()


def _path(job_id: str) -> Path:
    return config.JOBS_DIR / f"{job_id}.json"


def _log_path(job_id: str) -> Path:
    return config.JOBS_DIR / f"{job_id}.log"


def save(job: dict) -> None:
    with _lock:
        tmp = _path(job["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1))
        tmp.replace(_path(job["id"]))


def get(job_id: str) -> dict | None:
    p = _path(job_id)
    if not p.exists():
        return None
    job = json.loads(p.read_text())
    lp = _log_path(job_id)
    job["log"] = lp.read_text(errors="replace").splitlines()[-40:] if lp.exists() else []
    return job


def list_jobs(kind: str | None = None) -> list[dict]:
    out = []
    for p in sorted(config.JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            j = json.loads(p.read_text())
        except Exception:
            continue
        if kind is None or j.get("kind") == kind:
            out.append(j)
    return out


def submit(kind: str, payload: dict, fn: Callable[[dict, Callable[[str], None]], dict]) -> dict:
    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "status": "en_cola",
           "created": time.time(), "started": None, "finished": None,
           "payload": payload, "result": None, "error": None}
    save(job)
    _queue.put((job["id"], fn))
    return job


def _worker():
    while True:
        job_id, fn = _queue.get()
        job = get(job_id)
        if not job:
            continue
        job.pop("log", None)
        job.update(status="procesando", started=time.time())
        save(job)
        lp = _log_path(job_id)

        def log(msg: str, _lp=lp):
            with _lp.open("a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

        try:
            job["result"] = fn(job, log)
            job["status"] = "completado"
        except Exception as e:  # noqa: BLE001
            log(traceback.format_exc())
            job["status"] = "error"
            job["error"] = str(e)
        job["finished"] = time.time()
        save(job)


def recover_interrupted() -> None:
    """Marca como error los trabajos que quedaron a medias tras un reinicio."""
    for j in list_jobs():
        if j["status"] in ("en_cola", "procesando"):
            j["status"] = "error"
            j["error"] = "Interrumpido por reinicio del servidor. Vuelva a enviarlo."
            save(j)


def start() -> None:
    recover_interrupted()
    threading.Thread(target=_worker, daemon=True, name="gpu-worker").start()
