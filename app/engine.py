"""Offline face engine: SCRFD detection + MobileFaceNet (ArcFace) embeddings.

Runs the models with onnxruntime when it loads safely, otherwise with OpenCV's dnn module (same models,
same results). onnxruntime is probed in a separate process first, because on some PCs its native
library crashes Python on import.
"""
from __future__ import annotations
import os
import subprocess
import sys
import threading
import cv2
import numpy as np

from .paths import MODELS_DIR, applog

DET_SIZE = 640
STRIDES = (8, 16, 32)
ARCFACE_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def _nms(dets: np.ndarray, thresh: float) -> list[int]:
    x1, y1, x2, y2, s = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = s.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]]); yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]]); yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1 + 1) * np.maximum(0, yy2 - yy1 + 1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[1:][iou <= thresh]
    return keep


class Face:
    __slots__ = ("box", "score", "kps", "embedding", "quality", "row")

    def __init__(self, box, score, kps):
        self.box = box          # x1,y1,x2,y2 (ints)
        self.score = float(score)
        self.kps = kps          # 5x2
        self.embedding = None
        self.quality = {}
        self.row = None         # engine-specific raw detection (used for alignment)


def ort_is_safe() -> bool:
    """True if 'import onnxruntime' works in a child process (a native crash there cannot hurt us)."""
    forced = os.environ.get("FA_BACKEND", "").lower()
    if forced == "opencv":
        return False
    if forced == "onnxruntime":
        return True
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--probe-ort"]
    else:
        cmd = [sys.executable, "-c", "import onnxruntime"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90, creationflags=flags)
        ok = r.returncode == 0
        applog(f"engine: onnxruntime probe exit code {r.returncode} -> {'usable' if ok else 'NOT usable, using OpenCV backend'}")
        return ok
    except Exception as ex:
        applog(f"engine: onnxruntime probe failed ({ex}); using OpenCV backend")
        return False


def _key(a: np.ndarray):
    a = a.reshape(-1, a.shape[-1])
    return a.shape


class _OrtRunner:
    name = "onnxruntime"

    def __init__(self, model: str, threads: int):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.s = ort.InferenceSession(str(MODELS_DIR / model), opts, providers=["CPUExecutionProvider"])
        self.inp = self.s.get_inputs()[0].name

    def run(self, blob):
        return self.s.run(None, {self.inp: blob})


class _CvRunner:
    name = "opencv"

    def __init__(self, model: str, threads: int):
        self.net = cv2.dnn.readNetFromONNX(str(MODELS_DIR / model))
        self.names = self.net.getUnconnectedOutLayersNames()

    def run(self, blob):
        self.net.setInput(blob)
        out = self.net.forward(self.names)
        return list(out) if isinstance(out, (list, tuple)) else [out]


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


class ArcFaceEngine(_FaceMixin):
    """InsightFace SCRFD + MobileFaceNet. Optional, NON-COMMERCIAL models: only used if their files are present."""
    model_id = "arcface"
    dim = 512
    default_threshold = 0.45
    label = "InsightFace ArcFace (research licence)"

    def __init__(self, backend: str | None = None):
        threads = max(1, (os.cpu_count() or 2) // 2)
        backend = backend or ("onnxruntime" if ort_is_safe() else "opencv")
        applog(f"engine: backend={backend}, numpy {np.__version__}, cv2 {cv2.__version__}")
        Runner = _OrtRunner if backend == "onnxruntime" else _CvRunner
        # OpenCV needs the fixed-size (640x640) detector; onnxruntime can use the original
        det_model = "det_500m.onnx" if backend == "onnxruntime" else "det_500m_static.onnx"
        applog("engine: loading detector...")
        self.det = Runner(det_model, threads)
        applog("engine: loading recognizer...")
        self.rec = Runner("w600k_mbf.onnx", threads)
        applog("engine: models ready")
        self.backend = backend
        self._lock = threading.Lock()   # onnx sessions are fine, but keep CPU use predictable
        self._anchor_cache: dict = {}

    # ---------- detection ----------
    def _anchors(self, h, w, stride):
        key = (h, w, stride)
        if key not in self._anchor_cache:
            ys, xs = np.mgrid[0:h, 0:w]
            c = np.stack([xs, ys], axis=-1).astype(np.float32).reshape(-1, 2) * stride
            self._anchor_cache[key] = np.repeat(c, 2, axis=0)  # 2 anchors / cell
        return self._anchor_cache[key]

    def detect(self, bgr: np.ndarray, min_score: float = 0.5) -> list[Face]:
        h0, w0 = bgr.shape[:2]
        scale = DET_SIZE / max(h0, w0)
        nw, nh = int(w0 * scale), int(h0 * scale)
        resized = cv2.resize(bgr, (nw, nh))
        canvas = np.zeros((DET_SIZE, DET_SIZE, 3), np.uint8)
        canvas[:nh, :nw] = resized
        blob = cv2.dnn.blobFromImage(canvas, 1 / 128.0, (DET_SIZE, DET_SIZE),
                                     (127.5, 127.5, 127.5), swapRB=True)
        with self._lock:
            raw = self.det.run(blob)
        out = {_key(o): o for o in raw}
        scores_l, boxes_l, kps_l = [], [], []
        for idx, stride in enumerate(STRIDES):
            g = DET_SIZE // stride
            n = g * g * 2
            sc = out[(n, 1)].reshape(-1)
            bb = out[(n, 4)].reshape(-1, 4) * stride
            kp = out[(n, 10)].reshape(-1, 10) * stride
            anc = self._anchors(g, g, stride)
            pos = np.where(sc >= min_score)[0]
            if pos.size == 0:
                continue
            a = anc[pos]
            b = bb[pos]
            boxes = np.stack([a[:, 0] - b[:, 0], a[:, 1] - b[:, 1],
                              a[:, 0] + b[:, 2], a[:, 1] + b[:, 3]], axis=1)
            k = kp[pos].reshape(-1, 5, 2) + a[:, None, :]
            scores_l.append(sc[pos]); boxes_l.append(boxes); kps_l.append(k)
        if not scores_l:
            return []
        scores = np.concatenate(scores_l); boxes = np.concatenate(boxes_l) / scale
        kps = np.concatenate(kps_l) / scale
        dets = np.hstack([boxes, scores[:, None]])
        keep = _nms(dets, 0.4)
        faces = []
        for i in keep:
            x1, y1, x2, y2 = boxes[i]
            f = Face((int(max(0, x1)), int(max(0, y1)), int(min(w0, x2)), int(min(h0, y2))),
                     scores[i], kps[i].astype(np.float32))
            faces.append(f)
        faces.sort(key=lambda f: (f.box[2] - f.box[0]) * (f.box[3] - f.box[1]), reverse=True)
        return faces

    # ---------- recognition ----------
    def embed(self, bgr: np.ndarray, face: Face) -> np.ndarray:
        M, _ = cv2.estimateAffinePartial2D(face.kps, ARCFACE_DST, method=cv2.LMEDS)
        aligned = cv2.warpAffine(bgr, M, (112, 112), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(aligned, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        with self._lock:
            e = self.rec.run(blob)[0].reshape(-1)
        e = e.astype(np.float32)
        e /= (np.linalg.norm(e) + 1e-9)
        face.embedding = e
        face.quality = self.quality(bgr, face, aligned)
        return e



class SFaceEngine(_FaceMixin):
    """OpenCV Zoo YuNet (MIT) detector + SFace (Apache-2.0) recogniser. Commercial-friendly; needs only OpenCV."""
    model_id = "sface"
    dim = 128
    default_threshold = 0.363          # cosine; value recommended by the SFace authors
    label = "YuNet + SFace (MIT / Apache-2.0)"

    def __init__(self):
        applog(f"engine: YuNet+SFace, numpy {np.__version__}, cv2 {cv2.__version__}")
        self.det = cv2.FaceDetectorYN.create(str(MODELS_DIR / "face_detection_yunet_2023mar.onnx"), "",
                                             (320, 320), 0.6, 0.3, 5000)
        self.rec = cv2.FaceRecognizerSF.create(str(MODELS_DIR / "face_recognition_sface_2021dec.onnx"), "")
        self.backend = "opencv"
        self._lock = threading.Lock()
        applog("engine: models ready")

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

    def embed(self, bgr: np.ndarray, face: Face) -> np.ndarray:
        with self._lock:
            aligned = self.rec.alignCrop(bgr, face.row)
            e = self.rec.feature(aligned).reshape(-1).astype(np.float32)
        e /= (np.linalg.norm(e) + 1e-9)
        face.embedding = e
        face.quality = self.quality(bgr, face, aligned)
        return e


def FaceEngine(model: str | None = None):
    """Pick the engine. Default: YuNet+SFace (commercial-safe). InsightFace only if its files are present."""
    model = (model or os.environ.get("FA_MODEL", "")).lower()
    have_sface = (MODELS_DIR / "face_recognition_sface_2021dec.onnx").exists()
    have_arc = (MODELS_DIR / "w600k_mbf.onnx").exists()
    if model == "arcface" and have_arc:
        return ArcFaceEngine()
    if have_sface:
        return SFaceEngine()
    if have_arc:
        return ArcFaceEngine()
    raise FileNotFoundError(f"No face models found in {MODELS_DIR}")


def decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img
