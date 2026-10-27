"""Install a verified, independent copy of the image model (DINOv3 ViT-S/16, ONNX graph plus weights)."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import urllib.request

from .config import MODEL_FILES, MODEL_REPO, Settings, model_files


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(name, temporary):
    # HF_ENDPOINT selects a mirror such as https://hf-mirror.com; HF_TOKEN is only needed if access is gated.
    endpoint = os.getenv("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    request = urllib.request.Request(f"{endpoint}/{MODEL_REPO}/resolve/main/onnx/{name}")
    if os.getenv("HF_TOKEN"):
        request.add_unredirected_header("Authorization", f"Bearer {os.environ['HF_TOKEN']}")
    print(f"Downloading {name} from {endpoint} ...", flush=True)
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as stream:
        shutil.copyfileobj(response, stream, 1024 * 1024)


def install(source: Path | None = None):
    """Copy from a folder holding model.onnx and model.onnx_data, or download them."""
    targets = model_files(Settings.from_env().model_path)
    for name, target in targets.items():
        if target.is_file() and digest(target) == MODEL_FILES[name]:
            print(f"Verified {name} ready: {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".part")
        try:
            if source:
                origin = source / name
                if not origin.is_file():
                    raise RuntimeError(f"{origin} not found; the source folder needs model.onnx and model.onnx_data")
                if digest(origin) != MODEL_FILES[name]:
                    raise RuntimeError(f"{origin} checksum mismatch; no file was copied")
                if origin.resolve() == target.resolve():
                    raise RuntimeError("Invalid existing model; use a different source")
                shutil.copyfile(origin, temporary)
            else:
                download(name, temporary)
            if digest(temporary) != MODEL_FILES[name]:
                raise RuntimeError(f"Downloaded {name} checksum mismatch")
            temporary.replace(target)
            print(f"Verified {name} installed: {target}")
        finally:
            temporary.unlink(missing_ok=True)
    return targets["model.onnx"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Optional folder with model.onnx and model.onnx_data, verified by SHA-256")
    args = parser.parse_args()
    install(args.source)


if __name__ == "__main__":
    main()
