"""Собрать круглую аватарку бота из квадратной иконки.

Телеграм режет фотографию профиля кругом, поэтому квадратная иконка с
прозрачными углами теряет уголки и выглядит мелко. Скрипт заливает холст
цветом фона, вырезает глиф микрофона и ставит его по центру крупнее.

    python scripts/make_avatar.py --source path/to/icon.png \
        --out app/assets/bot_avatar.png
"""

from __future__ import annotations

import argparse

from PIL import Image


def _near(pixel: tuple[int, ...], target: tuple[int, int, int], tol: int = 26) -> bool:
    return all(abs(pixel[i] - target[i]) <= tol for i in range(3))


def glyph_bbox(image: Image.Image, colors: list[tuple[int, int, int]]) -> tuple[int, int, int, int]:
    """Границы непрозрачных пикселей нужных цветов (микрофон и стойка)."""
    pixels = image.load()
    width, height = image.size
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        for x in range(width):
            pixel = pixels[x, y]
            if pixel[3] > 200 and any(_near(pixel, color) for color in colors):
                xs.append(x)
                ys.append(y)
    if not xs:
        raise SystemExit("Не нашёл глиф микрофона на иконке")
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def build(source: str, out: str, size: int = 1024, glyph_height: float = 0.60) -> None:
    image = Image.open(source).convert("RGBA")
    box = glyph_bbox(image, [(69, 133, 136), (60, 56, 54)])
    glyph = image.crop(box)

    target_height = int(size * glyph_height)
    ratio = target_height / glyph.height
    glyph = glyph.resize(
        (max(1, int(glyph.width * ratio)), target_height), Image.LANCZOS
    )

    canvas = Image.new("RGBA", (size, size), (251, 241, 199, 255))
    offset = ((size - glyph.width) // 2, (size - glyph.height) // 2)
    canvas.alpha_composite(glyph, offset)
    canvas.save(out, "PNG", optimize=True)
    print(f"{out}: {size}x{size}, глиф {glyph.width}x{glyph.height}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="квадратная иконка проекта")
    parser.add_argument("--out", default="app/assets/bot_avatar.png")
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--glyph-height", type=float, default=0.60)
    args = parser.parse_args()
    build(args.source, args.out, args.size, args.glyph_height)
