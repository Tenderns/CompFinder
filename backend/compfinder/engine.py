import logging
import threading

import numpy as np
from PIL import Image

from .config import MODEL_FILES, Settings, model_files
from .db import Database
from .imaging import INPUT_SIZE, preprocess
from .model_setup import digest

log = logging.getLogger(__name__)
PATCH_SIZE = 16
REGISTER_TOKENS = 4
HIDDEN_SIZE = 384
VECTOR_VERSION = f"dinov3-vits16:{MODEL_FILES['model.onnx_data']}:white-margin-square{INPUT_SIZE}-cls-mean-v1"


class OnnxEncoder:
    version = VECTOR_VERSION

    def __init__(self, path):
        files = model_files(path)
        if not all(file.is_file() for file in files.values()):
            raise RuntimeError("缺少图片模型，请运行 scripts/setup.ps1 配置模型")
        if any(digest(file) != MODEL_FILES[name] for name, file in files.items()):
            raise RuntimeError("图片模型校验失败，请重新运行 scripts/setup.ps1")
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        # The export does not document its outputs; confirm the token layout once at the working resolution.
        expected = (1, 1 + REGISTER_TOKENS + (INPUT_SIZE // PATCH_SIZE) ** 2, HIDDEN_SIZE)
        try:
            shape = self.tokens(np.zeros((1, 3, INPUT_SIZE, INPUT_SIZE), dtype=np.float32)).shape
        except Exception as exc:
            raise RuntimeError(f"图片模型无法处理 {INPUT_SIZE}×{INPUT_SIZE} 输入：{exc}") from exc
        if shape != expected:
            raise RuntimeError(f"图片模型输出为 {shape}，应为 {expected}")

    def tokens(self, batch):
        """Final hidden states: CLS, register tokens, then the patch grid."""
        return next(output for output in self.session.run(None, {self.input: batch}) if output.ndim == 3)

    def embed(self, images):
        vectors = []
        for image in images:
            hidden = self.tokens(preprocess(image)[None])
            # Register tokens carry no image location and stay out of the patch mean.
            vectors.append(np.concatenate([hidden[:, 0], hidden[:, 1 + REGISTER_TOKENS:].mean(axis=1)], axis=1)[0])
        matrix = np.asarray(vectors, dtype=np.float32)
        return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


class ImageEngine:
    def __init__(self, settings: Settings, database: Database, encoder=None):
        self.settings = settings
        self.database = database
        self.encoder = encoder
        self.version = encoder.version if encoder is not None else VECTOR_VERSION
        self.problem = None
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.thread = None

    def initialize(self):
        with self.lock:
            if self.encoder is None:
                try:
                    self.encoder = OnnxEncoder(self.settings.model_path)
                    self.problem = None
                except Exception as exc:
                    self.problem = str(exc)
        with self.database.connect() as db:
            db.execute("UPDATE images SET state='pending',vector=NULL,vector_version=NULL,error=NULL "
                       "WHERE role='recognition' AND (state='processing' OR "
                       "(state='ready' AND (vector_version IS NULL OR vector_version!=?)))", (self.version,))
            db.execute("UPDATE imports SET state='interrupted' WHERE state='uploading'")

    def start(self):
        self.initialize()
        self.thread = threading.Thread(target=self._run, name="compfinder-index", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=30)

    def embed(self, images):
        with self.lock:
            if self.encoder is None:
                raise RuntimeError(self.problem or "图片引擎尚未就绪")
            return self.encoder.embed(images)

    def process_one(self):
        if self.encoder is None:
            return False
        with self.database.connect() as db:
            row = db.execute("SELECT id,storage_name FROM images WHERE role='recognition' AND state='pending' "
                             "ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                return False
            db.execute("UPDATE images SET state='processing',error=NULL WHERE id=?", (row["id"],))
        try:
            with Image.open(self.settings.data_dir / "images" / row["storage_name"]) as source:
                vector = self.embed([source.convert("RGB")])[0]
            if not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-10:
                raise ValueError("未能生成有效图片特征，请更换图片后重试")
            with self.database.connect() as db:
                # A concurrently deleted image must never be resurrected.
                db.execute("UPDATE images SET state='ready',vector=?,vector_version=?,error=NULL "
                           "WHERE id=? AND state='processing'",
                           (np.asarray(vector, dtype=np.float32).tobytes(), self.version, row["id"]))
        except Exception as exc:
            log.exception("Image indexing failed for %s", row["id"])
            with self.database.connect() as db:
                db.execute("UPDATE images SET state='failed',error=? WHERE id=?", (str(exc)[:400], row["id"]))
        return True

    def _run(self):
        while not self.stop.is_set():
            try:
                if self.process_one():
                    continue
            except Exception:
                log.exception("Index queue error")
            self.wake.wait(1)
            self.wake.clear()

    def retry(self):
        if self.encoder is None:
            with self.lock:
                try:
                    self.encoder = OnnxEncoder(self.settings.model_path)
                    self.problem = None
                except Exception as exc:
                    self.problem = str(exc)
                    raise RuntimeError(self.problem) from exc
        with self.database.connect() as db:
            db.execute("UPDATE images SET state='pending',error=NULL WHERE role='recognition' AND state='failed'")
        self.wake.set()

    def rank(self, queries):
        """Return (style_id, mean score, per-query best scores), best first."""
        vectors = self.embed(queries)
        with self.database.connect() as db:
            rows = db.execute("SELECT i.style_id,i.vector FROM images i WHERE i.role='recognition' "
                              "AND i.state='ready' AND i.vector_version=? AND EXISTS "
                              "(SELECT 1 FROM images d WHERE d.style_id=i.style_id AND d.role='display')",
                              (self.version,)).fetchall()
        if not rows:
            return []
        references = np.stack([np.frombuffer(row["vector"], dtype=np.float32) for row in rows])
        scores = np.clip(vectors @ references.T, -1, 1)
        best = {}
        for index, row in enumerate(rows):
            style_id = row["style_id"]
            best[style_id] = np.maximum(best.get(style_id, np.full(len(queries), -1.0)), scores[:, index])
        return sorted(((style_id, float(values.mean()), values.tolist()) for style_id, values in best.items()),
                      key=lambda item: (-item[1], item[0]))
