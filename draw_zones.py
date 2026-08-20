"""
draw_zones.py
--------------
Person 1 — calibration helper.

Draws the zones and equipment boxes from data/zones_config.json onto a
still frame, so you can SEE whether the coordinates actually line up with
your real camera angle before running the full pipeline. Much faster than
guessing-and-checking with the live --display window.

Usage:
    # grab a frame from your video first:
    python -c "import cv2; cv2.imwrite('frame.png', cv2.VideoCapture('test_assets/gym.mp4').read()[1])"

    # then overlay the configured zones/equipment on it:
    python draw_zones.py --frame frame.png --out frame_with_zones.png

Open frame_with_zones.png and check: do the yellow zone boxes match your
real floor layout? Do the cyan equipment boxes actually sit on top of the
real machines? If not, edit data/zones_config.json and re-run this script
until they do.
"""

from __future__ import annotations

import argparse
import json

import cv2


def draw_zones(frame_path: str, config_path: str, out_path: str):
    frame = cv2.imread(frame_path)
    if frame is None:
        raise RuntimeError(f"Could not read frame: {frame_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Zones: yellow, thick, labeled
    for zone in config["zones"]:
        x1, y1, x2, y2 = map(int, zone["bbox"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 3)
        cv2.putText(frame, zone["name"], (x1 + 8, y1 + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)

    # Equipment: cyan, thinner, labeled
    for eq in config["equipment"]:
        x1, y1, x2, y2 = map(int, eq["bbox"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
        cv2.putText(frame, eq["name"], (x1 + 6, y2 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2)

    cv2.imwrite(out_path, frame)
    print(f"Saved: {out_path}")
    print(f"Zones drawn: {[z['name'] for z in config['zones']]}")
    print(f"Equipment drawn: {[e['name'] for e in config['equipment']]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Overlay zones_config.json boxes on a frame for visual calibration")
    parser.add_argument("--frame", required=True, help="Path to a still frame image (e.g. frame.png)")
    parser.add_argument("--config", default="data/zones_config.json")
    parser.add_argument("--out", default="frame_with_zones.png")
    args = parser.parse_args()

    draw_zones(args.frame, args.config, args.out)
