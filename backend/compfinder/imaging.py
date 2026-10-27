import hashlib
from io import BytesIO
import warnings

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import MAX_FILE_BYTES

# DINOv3 patches are 16 px; 448 keeps a 28×28 grid so pins and stems span several patches.
INPUT_SIZE = 448
MEAN = np.array([.485, .456, .406], dtype=np.float32)
STD = np.array([.229, .224, .225], dtype=np.float32)
Image.MAX_IMAGE_PIXELS = 40_000_000


def decode_image(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("图片不能为空，且每张不能超过 20 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("仅支持 JPG、PNG、WebP 图片")
                if getattr(source, "is_animated", False):
                    raise ValueError("请上传静态图片，不支持动画")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                rgba = oriented.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
                if min(image.size) < 24:
                    raise ValueError("图片宽高至少为 24 像素")
                return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("图片无法读取或尺寸过大，请换一张图片") from exc


def content_hash(image: Image.Image) -> str:
    # Deduplicate the decoded, oriented content, including dimensions.
    return hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()


def crop_image(image: Image.Image, crop: dict | None) -> Image.Image:
    if crop is None:
        return image
    if not isinstance(crop, dict) or set(crop) != {"x", "y", "width", "height"}:
        raise ValueError("框选数据无效")
    values = [crop[k] for k in ("x", "y", "width", "height")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in values):
        raise ValueError("框选数据无效")
    x, y, w, h = values
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.00001 or y + h > 1.00001:
        raise ValueError("框选区域必须在图片内")
    box = (round(x * image.width), round(y * image.height),
           round((x + w) * image.width), round((y + h) * image.height))
    if box[2] - box[0] < 24 or box[3] - box[1] < 24:
        raise ValueError("框选区域太小，请至少保留 24 × 24 像素")
    return image.crop(box)


def trim_white_margin(image: Image.Image) -> Image.Image:
    """Adapted from ytst: retain thin leads, remove only uniform white margins."""
    sample = ImageOps.contain(image, (800, 800))
    pixels = np.asarray(sample, dtype=np.int16)
    border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    if np.mean(np.min(border, axis=1) >= 242) < .98:
        return image
    ys, xs = np.where(np.min(pixels, axis=2) < 242)
    if len(xs) < 32:
        return image
    margin = max(8, round(max(xs.max() - xs.min(), ys.max() - ys.min()) * .06))
    x0, y0 = max(0, xs.min() - margin), max(0, ys.min() - margin)
    x1, y1 = min(sample.width, xs.max() + margin + 1), min(sample.height, ys.max() + margin + 1)
    if (x1 - x0) * (y1 - y0) > sample.width * sample.height * .9:
        return image
    return image.crop((int(x0 * image.width / sample.width), int(y0 * image.height / sample.height),
                       int(np.ceil(x1 * image.width / sample.width)), int(np.ceil(y1 * image.height / sample.height))))


def preprocess(image: Image.Image) -> np.ndarray:
    image = trim_white_margin(image)
    side = max(image.size)
    canvas = Image.new("RGB", (side, side), "white")
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    array = np.asarray(canvas.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BICUBIC), dtype=np.float32) / 255
    return ((array - MEAN) / STD).transpose(2, 0, 1)
