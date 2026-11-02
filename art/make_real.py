#!/usr/bin/env python3
"""Fit your own character pictures to the 1280x720 home screen, darkened where the text and tiles sit.

Usage: make_real.py <pictures.json> <folder of pictures> <theme wallpapers folder>
See pictures/README.md for the file format.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

W, H = 1280, 720


def frame(source, mirror, shift):
    """Cover the screen, mirrored if asked, moved right with the edge colour filling the gap."""
    img = ImageOps.fit(Image.open(source).convert("RGB"), (W, H), Image.LANCZOS)
    if mirror:
        img = ImageOps.mirror(img)
    if shift:
        moved = Image.new("RGB", (W, H))
        moved.paste(img.crop((0, 0, 1, H)).resize((shift, H)), (0, 0))
        moved.paste(img, (shift, 0))
        img = moved
    return img


def grade(img, brightness):
    """Dark toward the left, top and floor, where the tagline, clock and tiles sit."""
    a = np.asarray(img, np.float32) * brightness
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    floor = np.clip((y - 400) / 250, 0, 1) ** 1.2
    left = np.clip((640 - x) / 640, 0, 1) ** 1.05
    top = np.clip((150 - y) / 150, 0, 1)
    keep = (1 - floor * 0.92) * (1 - left * 0.80) * (1 - top * 0.62)
    return Image.fromarray(np.clip(a * keep[..., None], 0, 255).astype(np.uint8))


def read_captions(path):
    captions = {}
    if path.exists():
        for row in path.read_text(encoding="utf-8").splitlines():
            if "\t" in row:
                name, line = row.split("\t", 1)
                captions[name] = line
    return captions


def main():
    config, sources, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    captions = read_captions(out / "captions.txt")
    for item in json.loads(config.read_text(encoding="utf-8")):
        name = f"art_{item['package']}.jpg"
        picture = frame(sources / item["file"], item.get("mirror", False), item.get("shift", 0))
        grade(picture, item.get("brightness", 1.0)).save(out / name, quality=84, optimize=True, subsampling=1)
        if "tagline" in item:
            captions[name] = item["tagline"]
        print(name, (out / name).stat().st_size // 1024, "KB")
    (out / "captions.txt").write_text("".join(f"{k}\t{v}\n" for k, v in captions.items()), encoding="utf-8")


if __name__ == "__main__":
    main()
