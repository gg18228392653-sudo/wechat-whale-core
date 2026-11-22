import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image, features

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wechat_whale_core import media_normalize as mn


class MediaNormalizeTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="image-normalize-test-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.out = self.root / "out"

    def _still(self, fmt="PNG", size=(12, 8), *, mode="RGB", color="red", **kwargs):
        path = self.root / "sample.bin"
        with Image.new(mode, size, color) as image:
            image.save(path, format=fmt, **kwargs)
        return path

    def _animation(self, fmt, durations, *, size=(24, 16), **kwargs):
        path = self.root / "sample.anim"
        frames = [Image.new("RGBA", size, (i * 31 % 256, i % 256, 128, 255))
                  for i in range(len(durations) + bool(kwargs.get("default_image")))]
        try:
            frames[0].save(path, format=fmt, save_all=True, append_images=frames[1:],
                           duration=durations, loop=0, **kwargs)
        finally:
            for frame in frames:
                frame.close()
        return path

    def _normalize(self, source, **kwargs):
        result = mn.normalize_media(source, self.out, **kwargs)
        self.assertTrue(result["ok"])
        output = Path(result["path"])
        self.assertEqual(output.stat().st_size, result["bytes"])
        self.assertEqual(result["sourceHash"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(result["outputFormat"], "png")
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (result["width"], result["height"]))
            self.assertFalse(image.is_animated)
            image.load()
        return result

    def test_png_detected_by_contents_and_alpha_preserved(self):
        source = self._still(mode="RGBA", color=(31, 21, 11, 111))
        before = source.read_bytes()
        result = self._normalize(source)
        self.assertEqual(result["sourceFormat"], "png")
        self.assertEqual(result["sampledFrameIndices"], [0])
        self.assertFalse(result["animated"])
        self.assertEqual(source.read_bytes(), before)
        with Image.open(result["path"]) as image:
            self.assertEqual(image.getpixel((2, 2)), (31, 21, 11, 111))

    def test_jpeg_orientation_applied_without_carrying_exif(self):
        exif = Image.Exif()
        exif[274] = 6
        source = self._still("JPEG", exif=exif)
        result = self._normalize(source)
        self.assertEqual(result["sourceFormat"], "jpeg")
        self.assertEqual((result["width"], result["height"]), (8, 12))
        with Image.open(result["path"]) as image:
            self.assertFalse(image.getexif())

    def test_large_and_extreme_aspect_stills_respect_output_pixel_limit(self):
        source = self._still("JPEG", size=(2500, 2000))
        result = self._normalize(source)
        self.assertLessEqual(result["width"] * result["height"], mn.OUTPUT_PIXELS)
        source = self._still(size=(100, 1))
        with patch.object(mn, "OUTPUT_PIXELS", 1):
            result = self._normalize(source)
            self.assertEqual((result["width"], result["height"]), (1, 1))

    def test_gif_samples_six_frames_and_records_start_times(self):
        result = self._normalize(self._animation("GIF", [100] * 8))
        self.assertEqual(result["sourceFormat"], "gif")
        self.assertTrue(result["animated"])
        self.assertEqual(result["sourceFrames"], 8)
        self.assertEqual(result["sampledFrameIndices"], [0, 1, 3, 4, 6, 7])
        self.assertEqual(result["sampledFrameTimesMs"], [0, 100, 300, 400, 600, 700])
        self.assertEqual(result["durationMs"], 800)
        self.assertEqual(result["sampledFrames"], 6)
        self.assertEqual((result["layout"]["columns"], result["layout"]["rows"]), (3, 2))
        self.assertGreater(result["layout"]["labelHeight"], 0)

    def test_missing_timing_and_skewed_duration_are_deterministic(self):
        self.assertEqual(mn._sample_indices([0] * 8), [0, 1, 3, 4, 6, 7])
        self.assertEqual(mn._sample_indices([900, 10, 10, 10, 10, 10, 10]), [0, 6])
        self.assertEqual(mn._sample_indices([0, 0, 0, 1, 1, 1, 0]), [0, 3, 4, 5, 6])

    def test_apng_skips_the_separate_default_image(self):
        source = self._animation("PNG", [50, 75, 125], default_image=True)
        result = self._normalize(source)
        self.assertEqual(result["sourceFormat"], "apng")
        self.assertEqual(result["sourceFrames"], 3)
        self.assertEqual(result["sampledFrameTimesMs"], [0, 50, 125])
        self.assertEqual(result["durationMs"], 250)
        layout = result["layout"]
        with Image.open(result["path"]) as image:
            center = layout["cellWidth"] // 2
            self.assertEqual(image.getpixel((center, center)), (31, 1, 128))

    def test_single_frame_apng_with_default_preview(self):
        result = self._normalize(self._animation("PNG", [50], default_image=True))
        self.assertEqual(result["sourceFormat"], "apng")
        self.assertEqual(result["sourceFrames"], 1)
        self.assertEqual(result["durationMs"], 50)
        self.assertFalse(result["animated"])
        with Image.open(result["path"]) as image:
            self.assertEqual(image.getpixel((0, 0)), (31, 1, 128, 255))

    @unittest.skipUnless(features.check("webp"), "Pillow built without WebP support")
    def test_still_and_animated_webp(self):
        still = self._normalize(self._still("WEBP", lossless=True))
        self.assertEqual(still["sourceFormat"], "webp")
        self.assertFalse(still["animated"])
        result = self._normalize(self._animation("WEBP", [50, 100, 200], lossless=True))
        self.assertEqual(result["sourceFormat"], "webp")
        self.assertTrue(result["animated"])
        self.assertEqual(result["sampledFrameTimesMs"], [0, 50, 150])
        self.assertEqual(result["durationMs"], 350)

    def test_collage_remains_within_tight_output_pixel_cap(self):
        source = self._animation("GIF", [100] * 5, size=(1, 1))
        result = self._normalize(source, max_pixels=25)
        self.assertLessEqual(result["width"] * result["height"], 25)
        self.assertEqual(result["sampledFrameIndices"], [0, 1, 2, 3, 4])
        self.assertEqual(result["layout"]["labelHeight"], 0)
        with self.assertRaisesRegex(mn.NormalizeError, "too small"):
            mn.normalize_media(source, self.out, max_pixels=5)

    def test_corrupt_and_unlisted_pillow_formats_are_rejected(self):
        source = self._still(fmt="BMP")
        with self.assertRaisesRegex(mn.NormalizeError, "unsupported or corrupt"):
            mn.normalize_media(source, self.out)
        for data in (b"unrecognized bytes", b"\x89PNG\r\n\x1a\n"):
            with self.subTest(data=data), self.assertRaises(mn.NormalizeError):
                source.write_bytes(data)
                mn.normalize_media(source, self.out)
        self.assertFalse(self.out.exists())

    def test_decompression_bomb_is_normalize_error(self):
        source = self._still()
        raw = source.read_bytes()
        import zlib
        header = struct.pack(">II", 200_000, 200_000) + raw[24:29]
        crc = struct.pack(">I", zlib.crc32(b"IHDR" + header))
        source.write_bytes(raw[:16] + header + crc + raw[33:])
        with self.assertRaises(mn.NormalizeError):
            mn.normalize_media(source, self.out)
        self.assertFalse(self.out.exists())

    def test_limits_reject_input_before_output_is_written(self):
        source = self._animation("GIF", [100, 100, 100])
        for options, error in (({"max_source_bytes": 1}, "source file exceeds"),
                               ({"max_pixels": 300}, "image exceeds pixel"),
                               ({"max_source_frames": 2}, "source frame limit"),
                               ({"max_frame_pixels": 1000}, "total frame pixel"),
                               ({"max_output_bytes": 1}, "normalized image exceeds"),
                               ({"max_output_bytes": True}, "positive integer")):
            with self.subTest(options=options), self.assertRaisesRegex(mn.NormalizeError, error):
                mn.normalize_media(source, self.out, **options)
        self.assertFalse(self.out.exists())

    def test_repeat_reencodes_instead_of_loading_stale_output(self):
        source = self._still()
        result = self._normalize(source)
        output = Path(result["path"])
        output.write_bytes(b"old bytes")
        with self.assertRaisesRegex(mn.NormalizeError, "byte limit"):
            mn.normalize_media(source, self.out, max_output_bytes=1)
        self.assertEqual(output.read_bytes(), b"old bytes")
        self.assertEqual(self._normalize(source), result)
        self.assertEqual(list(self.out.iterdir()), [output])

    def test_refuses_to_replace_the_source_file(self):
        source = self._still()
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = source.with_name(f"{digest}_{mn.NORMALIZATION_VERSION}.png")
        source.rename(target)
        with self.assertRaisesRegex(mn.NormalizeError, "matches the source"):
            mn.normalize_media(target, target.parent)
        self.assertEqual(target.read_bytes(), data)

    def _run_cli(self, payload):
        stdout = io.StringIO()
        with patch.object(sys, "stdin", io.BytesIO(payload)), redirect_stdout(stdout):
            status = mn.main()
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        return status, json.loads(stdout.getvalue())

    def test_json_cli_success_with_unicode_paths(self):
        source = self._still()
        target = source.with_name("sample-\u56fe\u7247.bin")
        source.rename(target)
        payload = json.dumps({"path": str(target), "outputDir": str(self.out)}, ensure_ascii=False)
        status, result = self._run_cli(payload.encode("utf-8"))
        self.assertEqual(status, 0)
        self.assertTrue(result["ok"])
        self.assertTrue(Path(result["path"]).is_file())

    def test_json_cli_invalid_json_or_missing_values(self):
        for payload in (b"-", b"[]", b"{}", b"\xff"):
            with self.subTest(payload=payload):
                status, result = self._run_cli(payload)
                self.assertEqual(status, 1)
                self.assertFalse(result["ok"])
                self.assertIn("error", result)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
