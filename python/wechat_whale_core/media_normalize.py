from __future__ import annotations

import hashlib
import io
import json
import math
import os
import sys
from bisect import bisect_right
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from PIL import Image, ImageDraw, ImageOps

NORMALIZATION_VERSION = "1"
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
OUTPUT_PIXELS = 4_000_000
MAX_SOURCE_FRAMES = 256
MAX_FRAME_PIXELS = 100_000_000
MAX_FRAMES = 6
LABEL_HEIGHT = 24
FORMATS = ("PNG", "JPEG", "GIF", "WEBP")
BACKGROUND = (28, 28, 32)


class NormalizeError(RuntimeError):
    pass


def _positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NormalizeError(f"{name} must be a positive integer")


def _read_source(path: Path, max_source_bytes: int) -> bytes:
    try:
        if not path.is_file():
            raise NormalizeError("source file does not exist or is not a regular file")
        with path.open("rb") as source:
            data = source.read(max_source_bytes + 1)
    except (OSError, ValueError, OverflowError) as exc:
        raise NormalizeError("could not read source file") from exc
    if not data:
        raise NormalizeError("source file is empty")
    if len(data) > max_source_bytes:
        raise NormalizeError("source file exceeds byte limit")
    return data


def _check_pixels(image: Image.Image, max_pixels: int) -> int:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise NormalizeError("image has invalid dimensions")
    pixels = width * height
    if pixels > max_pixels:
        raise NormalizeError("image exceeds pixel limit")
    return pixels


def _duration_ms(image: Image.Image) -> int:
    try:
        return max(0, round(float(image.info.get("duration", 0) or 0)))
    except (ValueError, TypeError, OverflowError):
        return 0


def _sample_indices(durations: list[int]) -> list[int]:
    frame_count = len(durations)
    if frame_count <= MAX_FRAMES:
        return list(range(frame_count))
    total = sum(durations)
    if not total:
        return [round(i * (frame_count - 1) / (MAX_FRAMES - 1)) for i in range(MAX_FRAMES)]
    starts = _frame_starts(durations)
    indices = [0]
    for i in range(1, MAX_FRAMES - 1):
        index = bisect_right(starts, total * i // (MAX_FRAMES - 1)) - 1
        if index != indices[-1]:
            indices.append(index)
    if indices[-1] != frame_count - 1:
        indices.append(frame_count - 1)
    return indices


def _frame_starts(durations: list[int]) -> list[int]:
    starts = []
    elapsed = 0
    for duration in durations:
        starts.append(elapsed)
        elapsed += duration
    return starts


def _animation_timing(
    image: Image.Image,
    first_frame: int,
    max_pixels: int,
    max_source_frames: int,
    max_frame_pixels: int,
) -> list[int]:
    durations = []
    decoded_pixels = 0
    index = 0
    while True:
        try:
            image.seek(index)
        except EOFError:
            break
        if index >= max_source_frames:
            raise NormalizeError("image exceeds source frame limit")
        decoded_pixels += _check_pixels(image, max_pixels)
        if decoded_pixels > max_frame_pixels:
            raise NormalizeError("animation exceeds total frame pixel limit")
        image.load()
        if index >= first_frame:
            durations.append(_duration_ms(image))
        index += 1
    if not durations:
        raise NormalizeError("image has no frames")
    return durations


def _frame(image: Image.Image) -> Image.Image:
    with ImageOps.exif_transpose(image) as oriented:
        return oriented.convert("RGBA")


def _fit_still(frame: Image.Image, max_pixels: int) -> Image.Image:
    if frame.width * frame.height <= max_pixels:
        return frame
    ratio = math.sqrt(max_pixels / (frame.width * frame.height))
    width = max(1, int(frame.width * ratio))
    height = max(1, int(frame.height * ratio))
    if width >= height:
        width = min(width, max_pixels // height)
    else:
        height = min(height, max_pixels // width)
    try:
        return frame.resize((width, height), Image.Resampling.LANCZOS)
    finally:
        frame.close()


def _collage(
    image: Image.Image,
    first_frame: int,
    indices: list[int],
    times: list[int],
    max_pixels: int,
) -> tuple[Image.Image, dict[str, Any]]:
    columns = min(3, len(indices))
    rows = (len(indices) + columns - 1) // columns
    area = max_pixels // (columns * rows)
    if area < 1:
        raise NormalizeError("output pixel limit is too small for the collage")
    label_height = LABEL_HEIGHT if area >= 16 * (16 + LABEL_HEIGHT) else 0
    cell = min(512, (math.isqrt(label_height**2 + 4 * area) - label_height) // 2)
    row_height = cell + label_height
    layout = {
        "type": "collage", "columns": columns, "rows": rows,
        "cellWidth": cell, "cellHeight": row_height, "labelHeight": label_height,
    }
    canvas = Image.new("RGB", (columns * cell, rows * row_height), BACKGROUND)
    try:
        for pos, (index, elapsed) in enumerate(zip(indices, times)):
            x = (pos % columns) * cell
            y = (pos // columns) * row_height
            image.seek(first_frame + index)
            with _frame(image) as frame:
                frame.thumbnail((cell, cell), Image.Resampling.LANCZOS)
                paste = x + (cell - frame.width) // 2, y + (cell - frame.height) // 2
                canvas.paste(frame, paste, frame)
            if label_height:
                with Image.new("RGB", (cell, label_height), BACKGROUND) as label:
                    ImageDraw.Draw(label).text((5, 5), f"{elapsed} ms", fill=(235, 235, 240))
                    canvas.paste(label, (x, y + cell))
    except BaseException:
        canvas.close()
        raise
    return canvas, layout


def _normalize_image(
    data: bytes,
    max_pixels: int,
    max_source_frames: int,
    max_frame_pixels: int,
) -> tuple[Image.Image, dict[str, Any]]:
    try:
        with Image.open(io.BytesIO(data), formats=FORMATS) as image:
            _check_pixels(image, max_pixels)
            source_format = str(image.format).lower()
            if source_format == "png" and image.get_format_mimetype() == "image/apng":
                source_format = "apng"
            first_frame = int(source_format == "apng" and bool(image.info.get("default_image")))
            if source_format in {"gif", "apng", "webp"}:
                durations = _animation_timing(image, first_frame, max_pixels, max_source_frames, max_frame_pixels)
            else:
                durations = [0]
            indices = _sample_indices(durations)
            starts = _frame_starts(durations)
            times = [starts[index] for index in indices]
            animated = len(durations) > 1
            output_pixels = min(max_pixels, OUTPUT_PIXELS)
            if animated:
                normalized, layout = _collage(image, first_frame, indices, times, output_pixels)
            else:
                image.seek(first_frame)
                normalized = _fit_still(_frame(image), output_pixels)
                layout = {
                    "type": "single", "columns": 1, "rows": 1,
                    "cellWidth": normalized.width, "cellHeight": normalized.height,
                }
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise NormalizeError("unsupported or corrupt image") from exc
    return normalized, {
        "sourceFormat": source_format,
        "sourceFrames": len(durations),
        "sampledFrames": len(indices),
        "sampledFrameIndices": indices,
        "sampledFrameTimesMs": times,
        "durationMs": sum(durations),
        "animated": animated,
        "layout": layout,
    }


def _encode_png(image: Image.Image, max_output_bytes: int) -> bytes:
    image.info.clear()
    with io.BytesIO() as destination:
        image.save(destination, format="PNG", optimize=True)
        if destination.tell() > max_output_bytes:
            raise NormalizeError("normalized image exceeds byte limit")
        return destination.getvalue()


def _write_output(path: Path, data: bytes) -> None:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, prefix=".normalize-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        temporary.replace(path)
        temporary = None
    except OSError as exc:
        raise NormalizeError("could not write normalized image") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def normalize_media(
    path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    max_source_bytes: int = MAX_SOURCE_BYTES,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
    max_pixels: int = MAX_PIXELS,
    max_source_frames: int = MAX_SOURCE_FRAMES,
    max_frame_pixels: int = MAX_FRAME_PIXELS,
) -> dict[str, Any]:
    for name, value in {
        "max_source_bytes": max_source_bytes, "max_output_bytes": max_output_bytes,
        "max_pixels": max_pixels, "max_source_frames": max_source_frames,
        "max_frame_pixels": max_frame_pixels,
    }.items():
        _positive_int(name, value)
    source = Path(path)
    data = _read_source(source, max_source_bytes)
    digest = hashlib.sha256(data).hexdigest()
    output_path = Path(output_dir) / f"{digest}_{NORMALIZATION_VERSION}.png"
    if output_path.resolve() == source.resolve():
        raise NormalizeError("output path matches the source file")
    image, metadata = _normalize_image(data, max_pixels, max_source_frames, max_frame_pixels)
    with image:
        encoded = _encode_png(image, max_output_bytes)
        width, height = image.size
    _write_output(output_path, encoded)
    return {
        "ok": True, "path": str(output_path), "sourceHash": digest,
        "normalizationVersion": NORMALIZATION_VERSION, "outputFormat": "png",
        "bytes": len(encoded), "width": width, "height": height, **metadata,
    }


def main() -> int:
    try:
        payload = json.load(getattr(sys.stdin, "buffer", sys.stdin))
        if not isinstance(payload, dict):
            raise NormalizeError("stdin must be a JSON object")
        path, output_dir = payload.get("path"), payload.get("outputDir")
        if not all(isinstance(value, str) and value.strip() for value in (path, output_dir)):
            raise NormalizeError("path and outputDir are required")
        result = normalize_media(path, output_dir)
    except NormalizeError as exc:
        result = {"ok": False, "error": str(exc)}
    except (json.JSONDecodeError, UnicodeError):
        result = {"ok": False, "error": "stdin must be a JSON object"}
    except Exception as exc:
        result = {"ok": False, "error": f"normalization failed: {type(exc).__name__}"}
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
