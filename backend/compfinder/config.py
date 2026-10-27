from dataclasses import dataclass
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[2]
MODEL_REPO = "onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX"
# The graph loads its weights from "model.onnx_data" beside it, so both names are fixed.
MODEL_FILES = {
    "model.onnx": "bb75e9e30ff382ecdbd150266445ab41272be4acc85fd3563218dd89781e36da",
    "model.onnx_data": "1eff0bb9f4fdef831ca61c8bc2b5c88d8cc21ef4756d3b483d9b9c15d8d5d27f",
}
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_QUERIES = 6
TOKEN_FILE = "access-token.txt"


def model_files(model_path: Path):
    """Local path of each model file for the graph at model_path."""
    return {name: model_path if name == "model.onnx" else model_path.with_name(name) for name in MODEL_FILES}


def load_token(data_dir: Path):
    """COMPFINDER_TOKEN, else data/access-token.txt, which is created with a random token on first start."""
    token = os.getenv("COMPFINDER_TOKEN", "").strip()
    path = data_dir / TOKEN_FILE
    if not token and path.is_file():
        token = path.read_text(encoding="utf-8").strip()
    if not token:
        token = secrets.token_urlsafe(32)
        data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(token + "\n", encoding="utf-8")
    if len(token) < 16 or not token.isascii() or not token.isprintable() or " " in token:
        raise RuntimeError("Access token must be at least 16 printable ASCII characters without spaces")
    return token


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model_path: Path
    frontend_dir: Path = ROOT / "frontend" / "dist"
    # None disables authentication; only tests construct Settings that way.
    token: str | None = None

    @classmethod
    def from_env(cls):
        root = Path(os.getenv("COMPFINDER_DATA_DIR", str(ROOT / "data"))).resolve()
        model = Path(os.getenv("COMPFINDER_MODEL_PATH", str(root / "models" / "dinov3-vits16" / "model.onnx"))).resolve()
        return cls(root, model, token=load_token(root))
