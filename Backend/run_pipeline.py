"""
run_pipeline.py
----------------
Person 1 — end-to-end test harness for the CV pipeline.

This is the script for the "Test full detection pipeline end-to-end on
stock gym video, fix bugs" subtask, and it's also basically what your demo
will run: point it at a stock gym video and it will detect people, assign
them to zones, track equipment idle/in-use status, print a live log, and
optionally save an annotated .mp4 you can show in your presentation.

Usage:
    cd backend
    python run_pipeline.py --video path/to/demo_video.mp4
    python run_pipeline.py --video path/to/demo_video.mp4 --save-video out.mp4
    python run_pipeline.py --video 0                       # webcam test
    python run_pipeline.py --video path/to/demo_video.mp4 --display   # live window

Once Person 2's stats_aggregator.py exists, the `on_data_point` callback
below is where you'd forward each DataPoint (+ zone/equipment snapshot)
into their ingestion function instead of just printing it.
"""

from __future__ import annotations

import argparse
import json

from services.person_detector import PersonDetector
from services.zone_tracker import ZoneTracker


def main():
    parser = argparse.ArgumentParser(description="Run the Smart Gym CV pipeline on a video")
    parser.add_argument("--video", required=True, help="Path to video file, or 0 for webcam")
    parser.add_argument("--zones-config", default="data/zones_config.json")
    parser.add_argument("--log-interval", type=float, default=30.0,
                         help="Seconds between logged data points (spec default: 30)")
    parser.add_argument("--save-video", default=None, help="Optional path to save annotated .mp4")
    parser.add_argument("--jsonl-log", default="data/person_log.jsonl")
    parser.add_argument("--display", action="store_true", help="Show a live OpenCV window")
    parser.add_argument("--max-seconds", type=float, default=None,
                         help="Stop after N seconds of video time (useful for quick tests)")
    args = parser.parse_args()

    source = int(args.video) if args.video.isdigit() else args.video

    detector = PersonDetector()
    tracker = ZoneTracker(args.zones_config)

    print(f"Running pipeline on source: {source}")
    print(f"Logging a data point every {args.log_interval}s\n")

    # Drive the zone tracker from EVERY frame, not just the logged data
    # points. This matters for equipment occupancy: someone briefly at a
    # machine between two log instants would otherwise never register as
    # "used it" (see the on_frame docstring in person_detector.py).
    def update_tracker_every_frame(detections, video_time):
        centroids = [d.centroid for d in detections]
        tracker.update(person_centroids=centroids, timestamp=video_time)

    for point in detector.run(
        source=source,
        log_interval_sec=args.log_interval,
        on_frame=update_tracker_every_frame,
        jsonl_log_path=args.jsonl_log,
        save_annotated_video_path=args.save_video,
        display=args.display,
        max_seconds=args.max_seconds,
    ):
        # tracker state already reflects every frame up to this point in
        # time (via update_tracker_every_frame above) — just read it out.
        snapshot = {
            "timestamp": point.timestamp,
            "wall_clock": point.wall_clock,
            "total_count": point.count,
            "zone_counts": tracker.get_zone_counts(),
            "equipment_status": tracker.get_equipment_status(current_timestamp=point.timestamp),
        }
        print(json.dumps(snapshot, indent=2))
        print("-" * 60)

    print("\nDone. Raw per-data-point log written to:", args.jsonl_log)
    if args.save_video:
        print("Annotated video saved to:", args.save_video)


if __name__ == "__main__":
    main()
