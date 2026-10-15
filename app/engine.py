"""Offline face engine.

Detection : YuNet (MIT licence), via OpenCV.
Recognition (picked automatically):
  * ArcFace R50 (InsightFace "w600k_r50", NON-COMMERCIAL licence) if models/w600k_r50.onnx exists. Most accurate.
  * SFace (Apache-2.0) otherwise. Safe to ship in a product you sell.
Everything runs through OpenCV's dnn module: no onnxruntime, no GPU, no internet.
"""
from __future__ import annotations
import os
import threading

import cv2
import numpy as np

from .paths import applog, model_path

DET_SIZE = 640
ARCFACE_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


class Face:
    __slots__ = ("box", "score", "kps", "embedding", "quality", "row")

    def __init__(self, box, score, kps):
        self.box = box          # x1,y1,x2,y2 (ints)
        self.score = float(score)
        self.kps = kps          # 5x2
        self.embedding = None
        self.quality = {}
        self.row = None         # engine-specific raw detection (used for alignment)


class _FaceMixin:
    """Checks shared by every engine: image quality and rough head pose."""

    @staticmethod
    def quality(bgr, face: Face, aligned) -> dict:
        x1, y1, x2, y2 = face.box
        crop = bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return {"ok": False, "reason": "No face area"}
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (112, 112))
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        bright = float(gray.mean())
        size = min(x2 - x1, y2 - y1)
        reason = None
        if size < 80:
            reason = "Move closer to the camera"
        elif bright < 55:
            reason = "Too dark - add more light"
        elif bright > 215:
            reason = "Too bright - reduce glare"
        elif blur < 25:
            reason = "Image is blurry - hold still"
        return {"ok": reason is None, "reason": reason, "blur": round(blur, 1),
                "brightness": round(bright, 1), "size": int(size)}

    @staticmethod
    def pose(face: Face) -> dict:
        """Rough head pose from 5 landmarks: yaw (left/right) and pitch (up/down) ratios."""
        le, re, nose, ml, mr = face.kps
        eye_c = (le + re) / 2
        mouth_c = (ml + mr) / 2
        eye_dist = np.linalg.norm(re - le) + 1e-6
        yaw = float((nose[0] - eye_c[0]) / eye_dist)             # + = nose toward image-right
        face_h = np.linalg.norm(mouth_c - eye_c) + 1e-6
        pitch = float((nose[1] - eye_c[1]) / face_h)              # larger = chin down
        return {"yaw": round(yaw, 3), "pitch": round(pitch, 3)}



class _YuNetEngine(_FaceMixin):
    """Shared detector. Subclasses provide embed() and model info."""
    backend = "opencv"

    def __init__(self):
        self.det = cv2.FaceDetectorYN.create(str(model_path("face_detection_yunet_2023mar.onnx")), "",
                                             (320, 320), 0.6, 0.3, 5000)
        self._lock = threading.Lock()

    def detect(self, bgr: np.ndarray, min_score: float = 0.6) -> list[Face]:
        h0, w0 = bgr.shape[:2]
        scale = min(1.0, DET_SIZE / max(h0, w0))
        img = cv2.resize(bgr, (int(w0 * scale), int(h0 * scale))) if scale < 1.0 else bgr
        h, w = img.shape[:2]
        with self._lock:
            self.det.setInputSize((w, h))
            self.det.setScoreThreshold(max(min_score, 0.6))
            _, rows = self.det.detect(img)
        faces = []
        if rows is None:
            return faces
        for r in rows:
            r = r.astype(np.float32).copy()
            r[:14] /= scale                      # back to original image coordinates
            x, y, bw, bh = r[:4]
            f = Face((int(max(0, x)), int(max(0, y)), int(min(w0, x + bw)), int(min(h0, y + bh))),
                     r[14], r[4:14].reshape(5, 2).astype(np.float32))
            f.row = r
            faces.append(f)
        faces.sort(key=lambda f: (f.box[2] - f.box[0]) * (f.box[3] - f.box[1]), reverse=True)
        return faces


class SFaceEngine(_YuNetEngine):
    """YuNet + SFace. Commercial-friendly (MIT / Apache-2.0)."""
    model_id = "sface"
    dim = 128
    default_threshold = 0.363            # cosine; value recommended by the SFace authors
    label = "Standard: YuNet + SFace (MIT / Apache-2.0)"

    def __init__(self):
        super().__init__()
        self.rec = cv2.FaceRecognizerSF.create(str(model_path("face_recognition_sface_2021dec.onnx")), "")
        applog(f"engine: {self.label}")

    def embed(self, bgr: np.ndarray, face: Face) -> np.ndarray:
        with self._lock:
            aligned = self.rec.alignCrop(bgr, face.row)
            e = self.rec.feature(aligned).reshape(-1).astype(np.float32)
        e /= (np.linalg.norm(e) + 1e-9)
        face.embedding = e
        face.quality = self.quality(bgr, face, aligned)
        return e


class ArcFaceR50Engine(_YuNetEngine):
    """YuNet + InsightFace ArcFace-R50 (WebFace600K). High accuracy. NON-COMMERCIAL model licence."""
    model_id = "arcface_r50"
    dim = 512
    default_threshold = 0.40
    label = "High accuracy: ArcFace R50 (InsightFace, non-commercial licence)"

    def __init__(self):
        super().__init__()
        self.net = cv2.dnn.readNetFromONNX(str(model_path("w600k_r50.onnx")))
        applog(f"engine: {self.label}")

    def embed(self, bgr: np.ndarray, face: Face) -> np.ndarray:
        M, _ = cv2.estimateAffinePartial2D(face.kps, ARCFACE_DST, method=cv2.LMEDS)
        aligned = cv2.warpAffine(bgr, M, (112, 112), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(aligned, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        with self._lock:
            self.net.setInput(blob)
            e = self.net.forward().reshape(-1).astype(np.float32)
        e /= (np.linalg.norm(e) + 1e-9)
        face.embedding = e
        face.quality = self.quality(bgr, face, aligned)
        return e


def FaceEngine(model: str | None = None):
    """Choose the recognition model. FA_MODEL=sface forces the standard (commercial-safe) one."""
    model = (model or os.environ.get("FA_MODEL", "auto")).lower()
    if model in ("auto", "arcface_r50") and model_path("w600k_r50.onnx").exists():
        try:
            return ArcFaceR50Engine()
        except Exception as ex:          # damaged download etc.
            applog(f"engine: high-accuracy model could not load ({ex}); using the standard model")
    return SFaceEngine()


def decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img
