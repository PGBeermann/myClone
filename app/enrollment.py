"""Análisis de calidad del video de la sesión de aprendizaje facial.

Antes de que el motor construya el avatar (detección de landmarks, codificación
latente de cada cuadro y máscaras de fusión), se verifica que el material sea
apto: un único rostro, frontal, bien iluminado, nítido y estable.
"""
from pathlib import Path

import cv2
import numpy as np

_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def analyze(video: Path, sample_every: int = 5) -> dict:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return {"ok": False, "score": 0, "checks": [], "error": "No se pudo abrir el video."}

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    sampled = one_face = multi_face = 0
    face_ratios, brightness, sharpness, centers = [], [], [], []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % sample_every == 0:
            sampled += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = _CASCADE.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6,
                                              minSize=(int(height * 0.12),) * 2)
            if len(faces) == 1:
                one_face += 1
                x, y, w, h = faces[0]
                face_ratios.append(h / height)
                roi = gray[y:y + h, x:x + w]
                brightness.append(float(roi.mean()))
                sharpness.append(float(cv2.Laplacian(roi, cv2.CV_64F).var()))
                centers.append(((x + w / 2) / width, (y + h / 2) / height))
            elif len(faces) > 1:
                multi_face += 1
        idx += 1
    cap.release()

    total_frames = idx
    seconds = total_frames / fps if fps else 0
    if sampled == 0:
        return {"ok": False, "score": 0, "checks": [], "error": "El video no contiene cuadros legibles."}

    pct_face = one_face / sampled
    pct_multi = multi_face / sampled
    med_ratio = float(np.median(face_ratios)) if face_ratios else 0.0
    med_bright = float(np.median(brightness)) if brightness else 0.0
    med_sharp = float(np.median(sharpness)) if sharpness else 0.0
    motion = float(np.std(np.array(centers), axis=0).mean()) if len(centers) > 2 else 0.0

    checks = [
        _check("duracion", "Duración", 10 <= seconds <= 90, f"{seconds:.1f} s",
               "Entre 10 y 90 s (ideal: 20–40 s)."),
        _check("rostro", "Rostro visible y frontal", pct_face >= 0.85, f"{pct_face*100:.0f} % de cuadros",
               "Mire a la cámara; evite girar la cabeza más de ~20°."),
        _check("unico", "Una sola persona", pct_multi <= 0.05, f"{pct_multi*100:.0f} % con varios rostros",
               "Solo usted debe aparecer en el encuadre."),
        _check("tamano", "Tamaño del rostro", 0.18 <= med_ratio <= 0.80, f"{med_ratio*100:.0f} % de la altura",
               "Encuadre tipo presentador: rostro entre 18 % y 80 % de la altura del cuadro."),
        _check("luz", "Iluminación del rostro", 70 <= med_bright <= 200, f"{med_bright:.0f}/255",
               "Luz frontal difusa; evite contraluz y sombras duras."),
        _check("nitidez", "Nitidez", med_sharp >= 40, f"{med_sharp:.0f}",
               "Limpie la lente, enfoque y evite movimientos bruscos."),
        _check("estabilidad", "Estabilidad de la cabeza", motion <= 0.06, f"{motion*100:.1f} % de desplazamiento",
               "Movimientos naturales y suaves; sin desplazarse en el encuadre."),
        _check("resolucion", "Resolución", height >= 480, f"{width}×{height}",
               "Mínimo 480 p; recomendado 720 p o 1080 p."),
    ]
    critical = {"duracion", "rostro", "unico", "resolucion"}
    ok = all(c["passed"] for c in checks if c["id"] in critical)
    score = round(100 * sum(c["passed"] for c in checks) / len(checks))
    return {"ok": ok, "score": score, "seconds": round(seconds, 2), "width": width,
            "height": height, "checks": checks}


def _check(cid, label, passed, value, hint):
    return {"id": cid, "label": label, "passed": bool(passed), "value": value, "hint": hint}
