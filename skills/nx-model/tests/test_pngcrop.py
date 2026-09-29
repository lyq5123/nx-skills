# =============================================================================
#  Unit tests for pngcrop.py - the tool the agent uses to READ a drawing.
#
#      python nx-model/tests/test_pngcrop.py
#
#  No NX and no third-party library: the fixtures are synthesized here with zlib,
#  which is the only way to test a decoder without shipping sample images.
#
#  The palette case is the reason this file exists. A palette PNG used to be read
#  as if its indices were grey levels: no error, no warning, and the colours gone -
#  for a scanned or bitonal drawing that can come out solid black. Silent wrongness
#  in the tool that feeds the transcription is worse than a refusal, so the
#  expansion is asserted pixel by pixel, and the refusals are asserted to be
#  REFUSALS (a clear message) rather than crashes or guesses.
# =============================================================================
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
PNGCROP = os.path.join(SCRIPTS, "pngcrop.py")


def chunk(kind, body):
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def write_png(path, width, height, color_type, rows, depth=8, interlace=0, extra=b""):
    raw = b"".join(b"\x00" + r for r in rows)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth,
                                            color_type, 0, 0, interlace)))
        fh.write(extra)
        fh.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        fh.write(chunk(b"IEND", b""))


def read_png(path):
    """Minimal reader, deliberately independent of the one under test."""
    data = open(path, "rb").read()
    pos, idat = 8, b""
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if kind == b"IHDR":
            w, h, depth, color = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
    raw = zlib.decompress(idat)
    stride = w * channels
    rows = [raw[1 + i * (stride + 1):1 + i * (stride + 1) + stride] for i in range(h)]
    return w, h, color, rows


class PngCropTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pngcroptest_")

    def path(self, name):
        return os.path.join(self.dir, name)

    def crop(self, src, dst, x, y, w, h, scale=1, expect_ok=True):
        if not os.path.isabs(src):
            src = self.path(src)
        if not os.path.isabs(dst):
            dst = self.path(dst)
        p = subprocess.run([sys.executable, PNGCROP, src, dst,
                            str(x), str(y), str(w), str(h), str(scale)],
                           capture_output=True, text=True)
        out = (p.stdout or "") + (p.stderr or "")
        if expect_ok:
            self.assertEqual(p.returncode, 0, "expected success, got:\n%s" % out)
        else:
            self.assertNotEqual(p.returncode, 0, "expected a refusal, got:\n%s" % out)
        return out

    # --- the formats it must READ --------------------------------------------
    def test_truecolour_crop_and_zoom(self):
        px = bytes([255, 0, 0])
        write_png(self.path("rgb.png"), 4, 4, 2, [px * 4 for _ in range(4)])
        self.crop("rgb.png", "rgb_out.png", 1, 1, 2, 2, scale=3)
        w, h, color, rows = read_png(self.path("rgb_out.png"))
        self.assertEqual((w, h, color), (6, 6, 2))
        self.assertEqual(rows[0], px * 6, "zoom did not replicate the pixel")

    def test_greyscale_and_greyscale_alpha(self):
        write_png(self.path("gray.png"), 4, 4, 0, [bytes([200] * 4) for _ in range(4)])
        self.crop("gray.png", "gray_out.png", 0, 0, 4, 4)
        self.assertEqual(read_png(self.path("gray_out.png"))[2], 0)
        write_png(self.path("gray_a.png"), 4, 4, 4,
                  [bytes([10, 255] * 4) for _ in range(4)])
        self.crop("gray_a.png", "gray_a_out.png", 0, 0, 4, 4)
        # colour type 4 out: greyscale + alpha stays greyscale + alpha
        self.assertEqual(read_png(self.path("gray_a_out.png"))[2], 4)

    def test_a_palette_png_keeps_its_colours(self):
        """The bug this file exists for: indices are not grey levels."""
        plte = bytes([255, 0, 0,
                      0, 255, 0,
                      0, 0, 255])
        rows = [bytes([0, 1, 2, 0]) for _ in range(4)]        # red, green, blue, red
        write_png(self.path("pal.png"), 4, 4, 3, rows, extra=chunk(b"PLTE", plte))
        out = self.crop("pal.png", "pal_out.png", 0, 0, 4, 4)
        self.assertIn("palette expanded", out)
        w, h, color, got = read_png(self.path("pal_out.png"))
        self.assertEqual(color, 2, "palette output should be truecolour")
        self.assertEqual(got[0], bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 0, 0]),
                         "palette indices were not expanded to their colours")

    def test_a_palette_png_with_transparency_becomes_rgba(self):
        plte = bytes([255, 0, 0, 0, 0, 255])
        trns = bytes([0, 255])                                # index 0 transparent
        write_png(self.path("pal_a.png"), 4, 4, 3,
                  [bytes([0, 1, 0, 1]) for _ in range(4)],
                  extra=chunk(b"PLTE", plte) + chunk(b"tRNS", trns))
        self.crop("pal_a.png", "pal_a_out.png", 0, 0, 4, 4)
        w, h, color, got = read_png(self.path("pal_a_out.png"))
        self.assertEqual(color, 6)
        self.assertEqual(got[0], bytes([255, 0, 0, 0, 0, 0, 255, 255] * 2))

    # --- the formats it must REFUSE, clearly ---------------------------------
    def test_sixteen_bit_is_refused_by_name(self):
        out = self.crop("rgb16.png", "x.png", 0, 0, 2, 2, expect_ok=False) \
            if os.path.exists(self.path("rgb16.png")) else None
        write_png(self.path("rgb16.png"), 4, 4, 2,
                  [bytes([0xFF, 0xFF, 0, 0, 0, 0] * 4) for _ in range(4)], depth=16)
        out = self.crop("rgb16.png", "x.png", 0, 0, 2, 2, expect_ok=False)
        self.assertIn("depth=16", out)

    def test_interlaced_is_refused_by_name(self):
        write_png(self.path("i.png"), 4, 4, 2, [bytes([1, 2, 3] * 4) for _ in range(4)],
                  interlace=1)
        out = self.crop("i.png", "x.png", 0, 0, 2, 2, expect_ok=False)
        self.assertIn("interlace=1", out)

    def test_a_non_png_is_refused_rather_than_guessed(self):
        with open(self.path("not.png"), "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0" + b"\x00" * 64)       # a JPEG's magic
        out = self.crop("not.png", "x.png", 0, 0, 2, 2, expect_ok=False)
        self.assertIn("is not a PNG", out)

    def test_a_palette_png_without_plte_is_refused(self):
        write_png(self.path("noplte.png"), 4, 4, 3, [bytes([0, 1, 0, 1]) for _ in range(4)])
        out = self.crop("noplte.png", "x.png", 0, 0, 2, 2, expect_ok=False)
        self.assertIn("no PLTE", out)

    def test_an_out_of_range_crop_is_clamped_not_crashed(self):
        write_png(self.path("small.png"), 4, 4, 2, [bytes([7, 7, 7] * 4) for _ in range(4)])
        self.crop("small.png", "big_region.png", 2, 2, 999, 999, scale=2)
        w, h, _c, _r = read_png(self.path("big_region.png"))
        self.assertEqual((w, h), (4, 4), "the crop should clamp to the image")

    def test_the_input_file_is_not_touched(self):
        write_png(self.path("src.png"), 4, 4, 2, [bytes([9, 9, 9] * 4) for _ in range(4)])
        before = open(self.path("src.png"), "rb").read()
        self.crop("src.png", "dst.png", 0, 0, 2, 2)
        self.assertEqual(open(self.path("src.png"), "rb").read(), before)

    def tearDown(self):
        for f in os.listdir(self.dir):
            try:
                os.remove(os.path.join(self.dir, f))
            except OSError:
                pass
        os.rmdir(self.dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
