"""Clon Docente — API y servidor web.

Ejecutar:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import hmac
import json
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, enrollment, jobs, media
from .engines import get_engine

app = FastAPI(title="Clon Docente", version="1.0.0")
engine = get_engine()
ID_RE = re.compile(r"^[a-z0-9_]{4,40}$")
COOKIE = "clon_token"


# ---------------------------------------------------------------- seguridad
@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    if config.APP_TOKEN and path.startswith("/api") and path not in ("/api/login", "/api/status"):
        supplied = request.cookies.get(COOKIE, "")
        h = request.headers.get("authorization", "")
        if h.lower().startswith("bearer "):
            supplied = h[7:].strip()
        if not hmac.compare_digest(supplied, config.APP_TOKEN):
            return JSONResponse({"detail": "No autorizado"}, status_code=401)
    return await call_next(request)


class Login(BaseModel):
    token: str


@app.post("/api/login")
def login(body: Login):
    if not config.APP_TOKEN:
        return {"ok": True}
    if not hmac.compare_digest(body.token, config.APP_TOKEN):
        raise HTTPException(401, "Clave incorrecta")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, body.token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30)
    return resp


@app.get("/api/status")
def status(request: Request):
    authed = not config.APP_TOKEN or hmac.compare_digest(request.cookies.get(COOKIE, ""), config.APP_TOKEN)
    return {"engine": engine.name, "engine_problems": engine.check(), "auth_required": bool(config.APP_TOKEN),
            "authenticated": authed, "limits": {"enroll_min": config.MIN_ENROLL_SECONDS,
                                                "enroll_max": config.MAX_ENROLL_SECONDS,
                                                "audio_max": config.MAX_AUDIO_SECONDS}}


# ---------------------------------------------------------------- utilidades
def _check_id(x: str) -> str:
    if not ID_RE.match(x or ""):
        raise HTTPException(400, "Identificador inválido")
    return x


async def _save_upload(up: UploadFile, dst: Path) -> None:
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    with dst.open("wb") as f:
        while chunk := await up.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                f.close()
                dst.unlink(missing_ok=True)
                raise HTTPException(413, f"Archivo mayor a {config.MAX_UPLOAD_MB} MB")
            f.write(chunk)
    if size == 0:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, "Archivo vacío")


def _ext(name: str | None, default: str) -> str:
    ext = Path(name or "").suffix.lower()
    return ext if re.match(r"^\.[a-z0-9]{2,5}$", ext) else default


def _read_meta(folder: Path) -> dict:
    return json.loads((folder / "meta.json").read_text())


def _write_meta(folder: Path, meta: dict) -> None:
    tmp = folder / "meta.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    tmp.replace(folder / "meta.json")


def _avatar_dir(avatar_id: str) -> Path:
    d = config.AVATARS_DIR / _check_id(avatar_id)
    if not (d / "meta.json").exists():
        raise HTTPException(404, "Avatar no encontrado")
    return d


# ---------------------------------------------------------------- avatares (sesión de aprendizaje)
@app.get("/api/avatars")
def list_avatars():
    out = []
    for d in sorted(config.AVATARS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if (d / "meta.json").exists():
            out.append(_read_meta(d))
    return out


@app.post("/api/avatars")
async def create_avatar(name: str = Form(...), consent: bool = Form(...), file: UploadFile = File(...)):
    if not consent:
        raise HTTPException(400, "Debe confirmar que es la persona del video o que cuenta con su autorización.")
    avatar_id = "a_" + uuid.uuid4().hex[:10]
    d = config.AVATARS_DIR / avatar_id
    d.mkdir(parents=True)
    raw = d / f"raw{_ext(file.filename, '.webm')}"
    try:
        await _save_upload(file, raw)
        media.normalize_enrollment(raw, d / "enroll.mp4")
        media.thumbnail(d / "enroll.mp4", d / "thumb.jpg", at=min(1.0, media.duration(d / "enroll.mp4") / 2))
        quality = enrollment.analyze(d / "enroll.mp4")
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(422, f"No se pudo procesar el video: {e}")
    finally:
        raw.unlink(missing_ok=True)
    meta = {"id": avatar_id, "name": name.strip()[:80] or "Sin nombre", "created": time.time(),
            "status": "analizado", "quality": quality, "job_id": None, "engine": engine.name}
    _write_meta(d, meta)
    return meta


@app.post("/api/avatars/{avatar_id}/train")
def train_avatar(avatar_id: str, force: bool = False):
    d = _avatar_dir(avatar_id)
    meta = _read_meta(d)
    if meta["status"] == "aprendiendo":
        raise HTTPException(409, "La sesión de aprendizaje ya está en curso")
    if not meta["quality"].get("ok") and not force:
        raise HTTPException(422, "El video no supera los controles críticos de calidad. Grabe de nuevo o use 'forzar'.")

    def task(job, log):
        m = _read_meta(d)
        m["status"] = "aprendiendo"
        _write_meta(d, m)
        try:
            t0 = time.time()
            engine.prepare(avatar_id, d / "enroll.mp4", log)
            m = _read_meta(d)
            m.update(status="listo", trained_at=time.time(), train_seconds=round(time.time() - t0, 1),
                     engine=engine.name)
            _write_meta(d, m)
            log("Sesión de aprendizaje completada.")
            return {"avatar_id": avatar_id}
        except Exception:
            m = _read_meta(d)
            m["status"] = "error"
            _write_meta(d, m)
            raise

    job = jobs.submit("aprendizaje", {"avatar_id": avatar_id, "name": meta["name"]}, task)
    meta.update(status="en_cola", job_id=job["id"])
    _write_meta(d, meta)
    return job


@app.get("/api/avatars/{avatar_id}/thumb")
def avatar_thumb(avatar_id: str):
    return FileResponse(_avatar_dir(avatar_id) / "thumb.jpg", media_type="image/jpeg")


@app.get("/api/avatars/{avatar_id}/video")
def avatar_video(avatar_id: str):
    return FileResponse(_avatar_dir(avatar_id) / "enroll.mp4", media_type="video/mp4")


@app.delete("/api/avatars/{avatar_id}")
def delete_avatar(avatar_id: str):
    d = _avatar_dir(avatar_id)
    if _read_meta(d)["status"] in ("en_cola", "aprendiendo"):
        raise HTTPException(409, "Espere a que termine la sesión de aprendizaje")
    engine.delete(avatar_id)
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


# ---------------------------------------------------------------- audios
@app.get("/api/audios")
def list_audios():
    out = []
    for p in sorted(config.AUDIOS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        out.append(json.loads(p.read_text()))
    return out


@app.post("/api/audios")
async def upload_audio(name: str = Form(""), file: UploadFile = File(...)):
    audio_id = "s_" + uuid.uuid4().hex[:10]
    raw = config.AUDIOS_DIR / f"{audio_id}_raw{_ext(file.filename, '.webm')}"
    wav = config.AUDIOS_DIR / f"{audio_id}.wav"
    try:
        await _save_upload(file, raw)
        if not media.has_stream(raw, "audio"):
            raise HTTPException(422, "El archivo no contiene pista de audio")
        media.normalize_audio(raw, wav)
        dur = media.duration(wav)
    except HTTPException:
        wav.unlink(missing_ok=True)
        raise
    except Exception as e:  # noqa: BLE001
        wav.unlink(missing_ok=True)
        raise HTTPException(422, f"No se pudo procesar el audio: {e}")
    finally:
        raw.unlink(missing_ok=True)
    if dur < 1:
        wav.unlink(missing_ok=True)
        raise HTTPException(422, "El audio dura menos de 1 segundo")
    meta = {"id": audio_id, "name": (name or Path(file.filename or "audio").stem).strip()[:80],
            "seconds": round(dur, 2), "created": time.time()}
    (config.AUDIOS_DIR / f"{audio_id}.json").write_text(json.dumps(meta, ensure_ascii=False))
    return meta


@app.get("/api/audios/{audio_id}/file")
def audio_file(audio_id: str):
    p = config.AUDIOS_DIR / f"{_check_id(audio_id)}.wav"
    if not p.exists():
        raise HTTPException(404, "Audio no encontrado")
    return FileResponse(p, media_type="audio/wav")


@app.delete("/api/audios/{audio_id}")
def delete_audio(audio_id: str):
    _check_id(audio_id)
    for p in (config.AUDIOS_DIR / f"{audio_id}.wav", config.AUDIOS_DIR / f"{audio_id}.json"):
        p.unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------- generación
class GenerateReq(BaseModel):
    avatar_id: str
    audio_id: str
    title: str = ""
    watermark: bool = True


@app.post("/api/generate")
def generate(req: GenerateReq):
    d = _avatar_dir(req.avatar_id)
    meta = _read_meta(d)
    if meta["status"] != "listo":
        raise HTTPException(409, "El avatar aún no completa la sesión de aprendizaje")
    if meta.get("engine") != engine.name:
        raise HTTPException(409, f"Este avatar aprendió con el motor '{meta.get('engine')}'. "
                                 f"Repita la sesión de aprendizaje con el motor actual ('{engine.name}').")
    wav = config.AUDIOS_DIR / f"{_check_id(req.audio_id)}.wav"
    if not wav.exists():
        raise HTTPException(404, "Audio no encontrado")
    audio_meta = json.loads((config.AUDIOS_DIR / f"{req.audio_id}.json").read_text())
    title = req.title.strip()[:100] or f"{meta['name']} – {audio_meta['name']}"

    def task(job, log):
        out_id = "v_" + uuid.uuid4().hex[:10]
        t0 = time.time()
        log(f"Generando video con sincronización labial ({engine.name}); audio de {audio_meta['seconds']} s")
        raw = engine.generate(req.avatar_id, wav, out_id, log)
        final = config.OUTPUTS_DIR / f"{out_id}.mp4"
        log("Postproceso: audio AAC" + (" + marca de agua de transparencia" if req.watermark else ""))
        media.finalize_video(raw, wav, final, req.watermark)
        raw.unlink(missing_ok=True)
        media.thumbnail(final, config.OUTPUTS_DIR / f"{out_id}.jpg", at=0.5)
        out = {"id": out_id, "title": title, "avatar_id": req.avatar_id, "audio_id": req.audio_id,
               "seconds": round(media.duration(final), 2), "created": time.time(),
               "render_seconds": round(time.time() - t0, 1), "watermark": req.watermark,
               "engine": engine.name}
        (config.OUTPUTS_DIR / f"{out_id}.json").write_text(json.dumps(out, ensure_ascii=False))
        log(f"Listo en {out['render_seconds']} s.")
        return out

    return jobs.submit("generacion", {"avatar_id": req.avatar_id, "audio_id": req.audio_id, "title": title}, task)


@app.get("/api/jobs")
def get_jobs(kind: str | None = None):
    return jobs.list_jobs(kind)[:50]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if not re.match(r"^[a-f0-9]{12}$", job_id):
        raise HTTPException(400, "Identificador inválido")
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Trabajo no encontrado")
    return j


@app.get("/api/outputs")
def list_outputs():
    return [json.loads(p.read_text()) for p in
            sorted(config.OUTPUTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)]


@app.get("/api/outputs/{out_id}/file")
def output_file(out_id: str, download: bool = False):
    p = config.OUTPUTS_DIR / f"{_check_id(out_id)}.mp4"
    if not p.exists():
        raise HTTPException(404, "Video no encontrado")
    if download:
        meta = json.loads((config.OUTPUTS_DIR / f"{out_id}.json").read_text())
        safe = re.sub(r"[^\w\-]+", "_", meta.get("title", out_id))[:60] or out_id
        return FileResponse(p, media_type="video/mp4", filename=f"{safe}.mp4")
    return FileResponse(p, media_type="video/mp4")


@app.get("/api/outputs/{out_id}/thumb")
def output_thumb(out_id: str):
    p = config.OUTPUTS_DIR / f"{_check_id(out_id)}.jpg"
    if not p.exists():
        raise HTTPException(404, "Miniatura no encontrada")
    return FileResponse(p, media_type="image/jpeg")


@app.delete("/api/outputs/{out_id}")
def delete_output(out_id: str):
    _check_id(out_id)
    for ext in (".mp4", ".jpg", ".json"):
        (config.OUTPUTS_DIR / f"{out_id}{ext}").unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------- arranque
@app.on_event("startup")
def _startup():
    jobs.start()


app.mount("/", StaticFiles(directory=config.BASE_DIR / "static", html=True), name="static")
