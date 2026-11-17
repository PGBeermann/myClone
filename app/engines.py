"""Motores de síntesis de video con sincronización labial.

MuseTalkEngine  — motor real (MuseTalk 1.5, Tencent Music Lyra Lab, licencia MIT).
                  Inpainting en espacio latente de la región de la boca a 30 fps+ en GPU.
MockEngine      — motor de prueba sin GPU: repite el video de aprendizaje con el audio.
                  Sirve para validar la instalación, la interfaz y el flujo de trabajo.

Ambos exponen la misma interfaz:
    prepare(avatar_id, video_path, log)           -> None   (sesión de aprendizaje)
    generate(avatar_id, audio_path, name, log)    -> Path   (video crudo sin postproceso)
    delete(avatar_id)                             -> None
"""
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

import yaml

from . import config

Log = Callable[[str], None]


class EngineError(RuntimeError):
    pass


class MuseTalkEngine:
    name = "musetalk"

    def __init__(self):
        self.root = config.MUSETALK_DIR
        v = config.MUSETALK_VERSION
        model_dir = "musetalkV15" if v == "v15" else "musetalk"
        weights = "unet.pth" if v == "v15" else "pytorch_model.bin"
        self.unet = self.root / "models" / model_dir / weights
        self.unet_cfg = self.root / "models" / model_dir / "musetalk.json"
        self.avatars_root = self.root / "results" / v / "avatars" if v == "v15" else self.root / "results" / "avatars"

    # -- utilidades ---------------------------------------------------------
    def check(self) -> list[str]:
        problems = []
        if not (self.root / "scripts" / "realtime_inference.py").exists():
            problems.append(f"No se encontró MuseTalk en {self.root}")
        for p in (self.unet, self.unet_cfg, self.root / "models" / "whisper" / "config.json",
                  self.root / "models" / "sd-vae" / "config.json",
                  self.root / "models" / "dwpose" / "dw-ll_ucoco_384.pth",
                  self.root / "models" / "face-parse-bisent" / "79999_iter.pth"):
            if not p.exists():
                problems.append(f"Falta el archivo de pesos: {p.relative_to(self.root) if self.root in p.parents else p}")
        return problems

    def _avatar_dir(self, avatar_id: str) -> Path:
        return self.avatars_root / avatar_id

    def _run(self, cfg: dict, log: Log, tag: str) -> None:
        problems = self.check()
        if problems:
            raise EngineError("Motor MuseTalk no instalado correctamente: " + "; ".join(problems))
        cfg_path = config.JOBS_DIR / f"musetalk_{tag}_{int(time.time()*1000)}.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
        cmd = [config.MUSETALK_PYTHON, "-m", "scripts.realtime_inference",
               "--inference_config", str(cfg_path),
               "--result_dir", "./results",
               "--unet_model_path", str(self.unet),
               "--unet_config", str(self.unet_cfg),
               "--version", config.MUSETALK_VERSION,
               "--fps", str(config.FPS),
               "--gpu_id", str(config.GPU_ID),
               "--batch_size", str(config.BATCH_SIZE)]
        log("$ " + " ".join(cmd))
        proc = subprocess.Popen(cmd, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, bufsize=1)
        assert proc.stdout
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(line)
        rc = proc.wait()
        cfg_path.unlink(missing_ok=True)
        if rc != 0:
            raise EngineError(f"MuseTalk terminó con código {rc}. Revise la bitácora.")

    # -- interfaz -----------------------------------------------------------
    def prepare(self, avatar_id: str, video_path: Path, log: Log) -> None:
        # Si ya existe, se borra para que MuseTalk no pida confirmación interactiva.
        shutil.rmtree(self._avatar_dir(avatar_id), ignore_errors=True)
        cfg = {avatar_id: {"preparation": True, "bbox_shift": 0,
                           "video_path": str(video_path.resolve()), "audio_clips": {}}}
        log("Aprendiendo facciones: detección de landmarks (DWPose), codificación latente (VAE) y máscaras de fusión…")
        self._run(cfg, log, "prep")
        if not (self._avatar_dir(avatar_id) / "latents.pt").exists():
            raise EngineError("La preparación no produjo latents.pt; revise la bitácora.")

    def generate(self, avatar_id: str, audio_path: Path, name: str, log: Log) -> Path:
        if not (self._avatar_dir(avatar_id) / "latents.pt").exists():
            raise EngineError("El avatar no ha completado la sesión de aprendizaje.")
        info = yaml.safe_load((self._avatar_dir(avatar_id) / "avator_info.json").read_text())
        cfg = {avatar_id: {"preparation": False, "bbox_shift": 0,
                           "video_path": info.get("video_path", ""),
                           "audio_clips": {name: str(audio_path.resolve())}}}
        self._run(cfg, log, "gen")
        out = self._avatar_dir(avatar_id) / "vid_output" / f"{name}.mp4"
        if not out.exists():
            raise EngineError("MuseTalk no generó el video de salida.")
        return out

    def delete(self, avatar_id: str) -> None:
        shutil.rmtree(self._avatar_dir(avatar_id), ignore_errors=True)


class Wav2LipEngine:
    """Motor para equipos SIN GPU NVIDIA (CPU, o Apple Silicon vía MPS).

    Pesos de Wav2Lip: licencia solo para uso personal/académico/investigación (no comercial).
    """
    name = "wav2lip"

    def __init__(self):
        self.root = config.WAV2LIP_DIR
        self.ckpt = self.root / "checkpoints" / "wav2lip_gan.pth"
        self.s3fd = self.root / "face_detection" / "detection" / "sfd" / "s3fd.pth"
        self.runner = Path(__file__).with_name("w2l_runner.py")

    def check(self) -> list[str]:
        problems = []
        if not (self.root / "models" / "wav2lip.py").exists():
            problems.append(f"No se encontró Wav2Lip en {self.root}")
        for p in (self.ckpt, self.s3fd):
            if not p.exists():
                problems.append(f"Falta el archivo de pesos: {p.name}")
        return problems

    def _avatar_dir(self, avatar_id: str) -> Path:
        return config.AVATARS_DIR / avatar_id / "w2l"

    def _run(self, args: list[str], log: Log) -> None:
        problems = self.check()
        if problems:
            raise EngineError("Motor Wav2Lip no instalado correctamente: " + "; ".join(problems))
        cmd = [config.WAV2LIP_PYTHON, str(self.runner), *args, "--w2l", str(self.root),
               "--batch", str(config.W2L_BATCH)]
        log("$ " + " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, bufsize=1)
        assert proc.stdout
        last_pct = -1
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("PROGRESO"):
                _, label, frac = line.split()
                a, b = (int(x) for x in frac.split("/"))
                pct = int(100 * a / max(1, b))
                if pct // 5 != last_pct // 5 or a == b:  # registra cada 5 %
                    log(f"{label}: {pct} % ({a}/{b})")
                    last_pct = pct
            elif line:
                log(line)
        rc = proc.wait()
        if rc != 0:
            raise EngineError(f"Wav2Lip terminó con código {rc}. Revise la bitácora.")

    def prepare(self, avatar_id: str, video_path: Path, log: Log) -> None:
        d = self._avatar_dir(avatar_id)
        shutil.rmtree(d, ignore_errors=True)
        log("Aprendiendo facciones: detección facial S3FD cuadro a cuadro y suavizado temporal de la región del rostro…")
        self._run(["prepare", "--video", str(video_path.resolve()), "--avatar", str(d.resolve())], log)

    def generate(self, avatar_id: str, audio_path: Path, name: str, log: Log) -> Path:
        d = self._avatar_dir(avatar_id)
        if not (d / "boxes.npy").exists():
            raise EngineError("El avatar no ha completado la sesión de aprendizaje con este motor.")
        out = (config.JOBS_DIR / f"{name}_raw.mp4").resolve()
        self._run(["generate", "--avatar", str(d.resolve()), "--audio", str(audio_path.resolve()),
                   "--out", str(out), "--checkpoint", str(self.ckpt)], log)
        return out

    def delete(self, avatar_id: str) -> None:
        shutil.rmtree(self._avatar_dir(avatar_id), ignore_errors=True)


class MockEngine:
    """Motor de prueba: no modifica los labios. Solo valida el flujo completo."""
    name = "mock"

    def check(self) -> list[str]:
        return []

    def prepare(self, avatar_id: str, video_path: Path, log: Log) -> None:
        for step in ("Detectando rostro", "Calculando landmarks", "Codificando latentes", "Creando máscaras"):
            log(f"[simulado] {step}…")
            time.sleep(0.2)
        (config.AVATARS_DIR / avatar_id / "mock_ready").write_text("ok")

    def generate(self, avatar_id: str, audio_path: Path, name: str, log: Log) -> Path:
        src = config.AVATARS_DIR / avatar_id / "enroll.mp4"
        out = config.JOBS_DIR / f"{name}_raw.mp4"
        log("[simulado] Repitiendo el video de aprendizaje en bucle a lo largo del audio…")
        cmd = ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src),
               "-i", str(audio_path), "-map", "0:v", "-map", "1:a", "-shortest",
               "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(out)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise EngineError(p.stderr[-500:])
        return out

    def delete(self, avatar_id: str) -> None:
        pass


def get_engine():
    return {"mock": MockEngine, "wav2lip": Wav2LipEngine, "musetalk": MuseTalkEngine}.get(
        config.ENGINE, MuseTalkEngine)()
