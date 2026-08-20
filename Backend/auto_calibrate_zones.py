"""
auto_calibrate_zones.py
-------------------------
Person 1 — automatic zone/equipment calibration for a NEW video.

WHAT THIS DOES (and doesn't):
Detects equipment locations by watching where PEOPLE spend time in the
video — not by recognizing what the equipment looks like. If someone uses
a treadmill for a while, the spot where they stood/ran gets identified as
an equipment zone. This means:

  - Equipment that gets used during the sample WILL be found automatically.
  - Equipment nobody touches during the sample CANNOT be found this way —
    there's nothing to detect if nobody's ever there. (True equipment
    *recognition*, independent of whether it's currently being used, needs
    a gym-equipment-specific object detector — see the Roboflow notes in
    equipment_detector.py. That's a separate, not-yet-verified capability;
    this script doesn't depend on it or require downloading anything.)
  - Auto-generated boxes are a good STARTING POINT, not a substitute for
    eyeballing the result with draw_zones.py — always verify visually
    before trusting the output.

HOW IT WORKS:
  1. Sample the video at a fixed interval, running the same PersonDetector
     used everywhere else in this pipeline.
  2. Bucket every detected person's centroid into a coarse grid over the
     frame.
  3. Grid cells that keep getting hit across many samples = somewhere
     people dwell = likely equipment. Cells hit only once or twice are
     probably just someone walking through, not using anything.
  4. Merge adjacent "hot" cells into clusters (simple flood-fill).
  5. For each cluster, build a bounding box from the union of every real
     person bbox that landed in it (expanded slightly), and write out a
     zones_config.json-compatible file.

USAGE:
    python auto_calibrate_zones.py --video test_assets/your_video.mp4 --out data/zones_config_auto.json

Then, like any calibration, VERIFY it before trusting it:
    python draw_zones.py --frame frame.png --config data/zones_config_auto.json --out check.png

...and rename the generic "detected_equipment_N" labels to real equipment
names once you've confirmed which box is which.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2

from services.person_detector import PersonDetector


def _get_video_dims(video_path: str) -> tuple[int, int]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return w, h


def collect_dwell_samples(video_path: str, sample_interval_sec: float, max_seconds: float | None):
    """Runs the person detector across the video and returns every detected
    (bbox, centroid) — one entry per person per sampled frame."""
    detector = PersonDetector()
    samples = []
    for point in detector.run(source=video_path, log_interval_sec=sample_interval_sec, max_seconds=max_seconds):
        for det in point.detections:
            samples.append(det.bbox)  # [x1,y1,x2,y2]
    return samples


def cluster_dwell_points(bboxes: list[list[float]], frame_w: int, frame_h: int,
                          grid_cells: int = 16, min_hits_fraction: float = 0.15):
    """
    Grid-bucket centroids, keep only cells hit often enough to suggest
    dwelling (not just passing through), then flood-fill merge adjacent hot
    cells into clusters. Returns a list of {bbox, hit_count} per cluster,
    where bbox is the union of every real person bbox that fell in it.
    """
    if not bboxes:
        return []

    cell_w = frame_w / grid_cells
    cell_h = frame_h / grid_cells

    # cell -> list of bboxes whose centroid landed there
    cell_boxes = defaultdict(list)
    for bbox in bboxes:
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        cell = (int(cx // cell_w), int(cy // cell_h))
        cell_boxes[cell].append(bbox)

    total_samples = len(bboxes)
    min_hits = max(2, int(total_samples * min_hits_fraction))
    hot_cells = {cell for cell, boxes in cell_boxes.items() if len(boxes) >= min_hits}

    # Flood-fill merge adjacent hot cells (4-connected) into clusters
    visited = set()
    clusters = []
    for start in hot_cells:
        if start in visited:
            continue
        stack = [start]
        group = []
        while stack:
            cell = stack.pop()
            if cell in visited or cell not in hot_cells:
                continue
            visited.add(cell)
            group.append(cell)
            cx, cy = cell
            for neighbor in [(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)]:
                if neighbor in hot_cells and neighbor not in visited:
                    stack.append(neighbor)
        clusters.append(group)

    results = []
    for group in clusters:
        all_boxes = []
        for cell in group:
            all_boxes.extend(cell_boxes[cell])
        x1 = min(b[0] for b in all_boxes)
        y1 = min(b[1] for b in all_boxes)
        x2 = max(b[2] for b in all_boxes)
        y2 = max(b[3] for b in all_boxes)
        results.append({"bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                         "hit_count": len(all_boxes)})

    results.sort(key=lambda r: -r["hit_count"])
    return results


def build_zones_config(clusters: list[dict], frame_w: int, frame_h: int) -> dict:
    equipment = []
    for i, c in enumerate(clusters, start=1):
        equipment.append({
            "id": f"detected_equipment_{i}",
            "name": f"Detected Equipment {i} (RENAME ME)",
            "type": "unknown",
            "zone_id": "zone_auto",
            "bbox": c["bbox"],
            "idle_threshold_minutes": 5,
            "busy_threshold_minutes": 45,
        })

    return {
        "_comment": "AUTO-GENERATED by auto_calibrate_zones.py — this is a "
                    "starting point, not a finished config. Verify every box "
                    "with draw_zones.py before trusting it, and rename the "
                    "generic 'Detected Equipment N' labels to real equipment "
                    "names. Only equipment actually USED during the sample "
                    "gets detected — anything nobody touched won't appear "
                    "here and must be added manually.",
        "frame_reference_resolution": {"width": frame_w, "height": frame_h},
        "zones": [
            {"id": "zone_auto", "name": "Auto-Detected Zone", "type": "area",
             "bbox": [0, 0, frame_w, frame_h]},
        ],
        "equipment": equipment,
    }


def main():
    parser = argparse.ArgumentParser(description="Auto-discover equipment ROIs from where people dwell in a video")
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", default="data/zones_config_auto.json")
    parser.add_argument("--sample-interval", type=float, default=1.0,
                         help="Seconds between sampled frames (smaller = more accurate, slower)")
    parser.add_argument("--max-seconds", type=float, default=None,
                         help="Only analyze the first N seconds (default: whole video)")
    parser.add_argument("--grid-cells", type=int, default=16,
                         help="Grid resolution for dwell detection (higher = finer clusters)")
    parser.add_argument("--min-hits-fraction", type=float, default=0.15,
                         help="Minimum fraction of samples a cell needs to count as 'dwelled in'")
    args = parser.parse_args()

    frame_w, frame_h = _get_video_dims(args.video)
    print(f"Video: {args.video} ({frame_w}x{frame_h})")
    print(f"Sampling every {args.sample_interval}s...")

    bboxes = collect_dwell_samples(args.video, args.sample_interval, args.max_seconds)
    print(f"Collected {len(bboxes)} person detections across the sample.")

    if not bboxes:
        print("No people detected at all — can't auto-calibrate. "
              "Check the video actually has people in it, or lower nothing "
              "(there's no threshold to lower here — zero detections means "
              "the detector found nobody).")
        return

    clusters = cluster_dwell_points(bboxes, frame_w, frame_h,
                                     grid_cells=args.grid_cells,
                                     min_hits_fraction=args.min_hits_fraction)
    print(f"Found {len(clusters)} dwell cluster(s):")
    for i, c in enumerate(clusters, start=1):
        print(f"  {i}. bbox={c['bbox']}  hits={c['hit_count']}")

    config = build_zones_config(clusters, frame_w, frame_h)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print(f"\nWrote {out_path}")
    print("Next: grab a frame and verify visually before trusting this —")
    print(f'  python -c "import cv2; cv2.imwrite(\'frame.png\', cv2.VideoCapture(\'{args.video}\').read()[1])"')
    print(f"  python draw_zones.py --frame frame.png --config {out_path} --out check.png")


if __name__ == "__main__":
    main()
