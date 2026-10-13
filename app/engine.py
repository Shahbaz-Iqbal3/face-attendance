"""Offline face engine: SCRFD detection + MobileFaceNet (ArcFace) embeddings via onnxruntime."""
from __future__ import annotations
import os
import threading
import cv2
import numpy as np
import onnxruntime as ort

from .paths import MODELS_DIR

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
    __slots__ = ("box", "score", "kps", "embedding", "quality")

    def __init__(self, box, score, kps):
        self.box = box          # x1,y1,x2,y2 (ints)
        self.score = float(score)
        self.kps = kps          # 5x2
        self.embedding = None
        self.quality = {}


class FaceEngine:
    def __init__(self):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
        prov = ["CPUExecutionProvider"]
        self.det = ort.InferenceSession(str(MODELS_DIR / "det_500m.onnx"), opts, providers=prov)
        self.rec = ort.InferenceSession(str(MODELS_DIR / "w600k_mbf.onnx"), opts, providers=prov)
        self.det_input = self.det.get_inputs()[0].name
        self.rec_input = self.rec.get_inputs()[0].name
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
            out = self.det.run(None, {self.det_input: blob})
        scores_l, boxes_l, kps_l = [], [], []
        for idx, stride in enumerate(STRIDES):
            sc = out[idx].reshape(-1)
            bb = out[idx + 3].reshape(-1, 4) * stride
            kp = out[idx + 6].reshape(-1, 10) * stride
            g = DET_SIZE // stride
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
            e = self.rec.run(None, {self.rec_input: blob})[0][0]
        e = e.astype(np.float32)
        e /= (np.linalg.norm(e) + 1e-9)
        face.embedding = e
        face.quality = self.quality(bgr, face, aligned)
        return e

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


def decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img
