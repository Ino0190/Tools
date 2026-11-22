#!/usr/bin/env python3
"""PictureKit dev renders: run experiments as one trusted `python3 PictureKit/dev.py`.

Usage:
  python3 PictureKit/dev.py render '{"exposure": 0.4, "contrast": 31}'
  python3 PictureKit/dev.py render '{}' --full --out /tmp/out.png
  python3 PictureKit/dev.py compare '{}' '{"shadows": 60}'
"""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

import argparse
import json
import tempfile

import numpy as np

sys.path.insert(0, str(ROOT))
import picturekit

BASE = {"curve": [0, 64, 128, 192, 255], "cropAspect": "original"}


def make_item(source):
    work = Path(tempfile.mkdtemp(prefix="picturekit-dev-"))
    return {"source": source, "dir": work, "name": source.name}


def metrics(image):
    pixels = np.asarray(image, dtype=np.float32)
    luminance = pixels @ np.array([.2126, .7152, .0722], dtype=np.float32)
    edge = (np.mean(np.abs(np.diff(luminance, axis=0))) +
            np.mean(np.abs(np.diff(luminance, axis=1)))) / 2
    maximum = pixels.max(2)
    saturation = np.mean((maximum - pixels.min(2)) / np.maximum(maximum, 1))
    return {
        "size": list(image.size),
        "percentiles": [round(v, 1) for v in
                        np.percentile(luminance, [1, 10, 50, 90, 99]).tolist()],
        "white_clip": round(float(np.mean(np.all(pixels >= 250, 2))), 5),
        "black_clip": round(float(np.mean(np.all(pixels <= 5, 2))), 5),
        "edge": round(float(edge), 3),
        "saturation": round(float(saturation), 4),
    }


def main():
    parser = argparse.ArgumentParser(description="PictureKit dev renders")
    parser.add_argument("command", choices=["render", "compare"])
    parser.add_argument("settings", nargs="+", help="settings JSON (1 or 2)")
    parser.add_argument("--source", default=str(ROOT / "IMGP6613.DNG"))
    parser.add_argument("--full", action="store_true", help="full-size render")
    parser.add_argument("--out", default="", help="save PNG to this path")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"source not found: {source}")
    item = make_item(source)
    picturekit.prepare_item(item)

    results = []
    for raw_settings in args.settings:
        settings = {**BASE, **json.loads(raw_settings)}
        image = picturekit.developed_image(item, settings, preview=not args.full)
        results.append((settings, image))

    for index, (settings, image) in enumerate(results):
        print(json.dumps({"settings": {k: v for k, v in settings.items()
                                       if k not in BASE or settings[k] != BASE[k]},
                          **metrics(image)}, ensure_ascii=False))
        if args.out:
            target = Path(args.out)
            if len(results) > 1:
                target = target.with_stem(f"{target.stem}-{index}")
            image.save(target, "PNG")
            print(f"saved: {target}")

    if args.command == "compare" and len(results) == 2:
        first, second = (metrics(image) for _, image in results)
        print(json.dumps({"edge_ratio": round(second["edge"] / max(first["edge"], 1e-6), 3),
                          "median_shift": round(second["percentiles"][2] -
                                                first["percentiles"][2], 1),
                          "saturation_shift": round(second["saturation"] -
                                                    first["saturation"], 4)}))


if __name__ == "__main__":
    main()
