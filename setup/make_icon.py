"""Draw MINTRO's icon (the card's mint diamond) and save it as a multi-size .ico. Pure Python, no imaging libraries."""
import math
import struct
import sys
import zlib

STOPS = [(0.0, (0x8F, 0xF5, 0xC6)), (0.55, (0x3D, 0xDC, 0x97)), (1.0, (0x17, 0xA8, 0x6C))]


def _color(t: float) -> tuple:
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
    return STOPS[-1][1]


def _image(size: int) -> bytes:
    """RGBA rows of a rounded square turned 45 degrees, 4x4 supersampled for smooth edges."""
    r = 0.13 * size
    half = (0.47 * size - r) / math.sqrt(2) + r  # so the rounded tips stop just inside the edges
    rows, n = [], 4
    for y in range(size):
        row = bytearray([0])  # PNG filter: none
        for x in range(size):
            hits = 0
            for sy in range(n):
                for sx in range(n):
                    px, py = x + (sx + 0.5) / n - size / 2, y + (sy + 0.5) / n - size / 2
                    u, v = abs(px + py) / math.sqrt(2), abs(py - px) / math.sqrt(2)
                    qx, qy = u - (half - r), v - (half - r)
                    d = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r
                    hits += d <= 0
            red, green, blue = _color((x + y) / (2 * size))
            row += bytes((red, green, blue, round(255 * hits / (n * n))))
        rows.append(bytes(row))
    return b"".join(rows)


def _png(size: int) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(_image(size), 9)) + chunk(b"IEND", b"")


def write_ico(path: str, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    images = [_png(s) for s in sizes]
    offset = 6 + 16 * len(images)
    out = struct.pack("<HHH", 0, 1, len(images))
    for s, img in zip(sizes, images):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    with open(path, "wb") as f:
        f.write(out + b"".join(images))


if __name__ == "__main__":
    write_ico(sys.argv[1] if len(sys.argv) > 1 else "mintro.ico")
