"""Crop and zoom an image so a drawing's dimension text can be read - stdlib only.

WHY THIS IS PART OF THE SKILL
    Reading a drawing, photo or screenshot is the agent's job, not the journals'
    (see SKILL.md: NX ships CPython with no site-packages, so there is no PIL,
    OpenCV or OCR to call). But dimension text on a downloaded drawing is often
    too small to read at the size the image arrives, and this machine has no image
    tooling at all - no PIL, no cv2, no ffmpeg, no ImageMagick. This decodes PNG
    with zlib alone, so it works anywhere Python does:

        python pngcrop.py in.png out.png X Y W H [SCALE]

    X Y W H is the region to keep, SCALE an integer upscale (default 2, nearest
    neighbour - see the note below). On Windows, PowerShell's System.Drawing can
    crop and scale EVERY common format and with smoother text; SKILL.md says when
    to prefer which.

WHAT IT ACCEPTS, MEASURED (2026-09-30)
    8-bit PNG, colour types 0/2/3/4/6 . . . . . . . . . . . . . . . . . . . works
      (type 3, palette, is expanded through PLTE/tRNS to RGB or RGBA - it used to
       be read as if the indices were grey levels, which silently threw the colours
       away, and scanned or bitonal drawings are usually palette PNGs)
    16-bit PNG . . . . . . . . . . . . . . . . . . . . refused, naming the depth
    interlaced (Adam7) PNG  . . . . . . . . . . . . . . . . . . . refused, named
    JPEG / GIF / BMP / TIFF / PDF . . . . . . . . . . . . . . . . refused as
      "not a PNG" - it never guesses. Convert first, or use the PowerShell route.

    It never modifies the input: a new file is written.

NO INTERPOLATION, ON PURPOSE
    Scaling is nearest neighbour, so the output contains no edge the original did
    not. That is the cautious choice for an image the agent then reasons about.
    Note what it is NOT: nothing here is ever measured with a ruler. Dimensions
    come from the printed numbers on the drawing, never from pixels - a photo has
    an unknown scale and lens distortion, so a pixel measurement means nothing.
"""
import struct
import sys
import zlib


def read_png(path):
    """(width, height, channels, rows, note) - rows are unfiltered scanlines."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("%s is not a PNG (only PNG is read; convert it first, or use "
                         "PowerShell's System.Drawing on Windows)" % path)
    pos = 8
    idat = b""
    plte = None
    trns = None
    width = height = depth = color = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", body)
            if depth != 8 or interlace != 0:
                raise SystemExit("only 8-bit non-interlaced PNG is read: depth=%d "
                                 "interlace=%d" % (depth, interlace))
            if color not in (0, 2, 3, 4, 6):
                raise SystemExit("unknown PNG colour type %d" % color)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break

    # Palette entries are indices into PLTE until they are expanded below, so every
    # colour type decodes with its natural channel count here.
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    if color == 3 and not plte:
        raise SystemExit("%s is a palette PNG with no PLTE chunk" % path)

    raw = zlib.decompress(idat)
    stride = width * channels
    rows = []
    prev = bytearray(stride)
    p = 0
    for _y in range(height):
        ft = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ft == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise SystemExit("unknown filter type %d on row %d" % (ft, _y))
        rows.append(bytes(line))
        prev = line

    note = None
    if color == 3:
        # Expand through the palette. Without this the "pixels" are indices, which
        # reads as pure black or pure white and throws the drawing away.
        n = len(plte) // 3
        alpha = trns is not None
        expand = []
        for line in rows:
            out = bytearray()
            for idx in line:
                idx = idx if idx < n else 0
                out += plte[idx * 3:idx * 3 + 3]
                if alpha:
                    out.append(trns[idx] if idx < len(trns) else 255)
            expand.append(bytes(out))
        rows = expand
        channels = 4 if alpha else 3
        note = "palette expanded to %s" % ("RGBA" if alpha else "RGB")
    return width, height, channels, rows, note


def write_png(path, width, height, channels, rows):
    # 2 channels is greyscale + alpha (colour type 4). It was missing here, so a
    # greyscale+alpha source decoded fine and then crashed on the way out - caught
    # by tests/test_pngcrop.py, which is the only reason to have that file.
    color = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        fh.write(chunk(b"IEND", b""))


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip().splitlines()[6].strip())
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    x, y, cw, ch = (int(v) for v in sys.argv[3:7])
    scale = int(sys.argv[7]) if len(sys.argv) > 7 else 2

    width, height, channels, rows, note = read_png(src)
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    cw = max(1, min(cw, width - x))
    ch = max(1, min(ch, height - y))

    out = []
    for r in range(y, y + ch):
        line = rows[r][x * channels:(x + cw) * channels]
        if scale == 1:
            out.append(line)
        else:
            big = bytearray()
            for i in range(0, len(line), channels):
                big += line[i:i + channels] * scale
            for _ in range(scale):
                out.append(bytes(big))
    write_png(dst, cw * scale, ch * scale, channels, out)
    print("%s: %dx%d from (%d,%d) %dx%d, scale %d%s"
          % (dst, cw * scale, ch * scale, x, y, cw, ch, scale,
             "  [%s]" % note if note else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
