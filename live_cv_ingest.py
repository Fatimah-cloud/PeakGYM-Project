"""
live_cv_ingest.py
-------------------
Person 1 — continuous multi-camera ingestion into the real database.

UPGRADED: this used to run a single background thread watching one video
(demo_video.mp4) against the merged zones_config.json — which meant the
live pipeline was checking for people on 11 pieces of equipment spread
across 4 zones, but only ever looking at ONE video that didn't actually
contain most of that equipment. Headcount/equipment stats stayed near
zero no matter how long it ran.

This now runs FOUR independent background threads, one per real camera
(cam1.mp4 .. cam4.mp4), each checked only against ITS OWN zone's real
equipment (using data/zones_config_cam1.json .. cam4.json — generated from
generate_cam_tracks.py's CAMERA_CONFIGS, the correct per-camera source of
truth). All four write into the same raw_detections table via Person 2's
ingest_snapshot() — /stats/current sums each zone's most-recent row
regardless of which camera wrote it, so no backend changes were needed for
this to compose correctly.

Note: this is separate from the pre-computed per-second track JSON files
(data/detections/cam1_detections.json etc.) that drive the *visual* Live
Camera Feed overlay in the frontend — that's a legitimate, different design
(frame-accurate replay synced to video playback) and is untouched here.
This module only feeds the aggregate stats: headcount, equipment status,
heatmap, peak times, LLM recommendations.

Wire into main.py (unchanged from before):

    from live_cv_ingest import start_live_ingest, stop_live_ingest

    @app.on_event("startup")
    def on_startup():
        init_db()
        start_scheduler()
        start_live_ingest()

    @app.on_event("shutdown")
    def on_shutdown():
        stop_scheduler()
        stop_live_ingest()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from services.person_detector import PersonDetector
from services.zone_tracker import ZoneTracker
from services.ingest_cv_pipeline import ingest_snapshot
from services.stats_aggregator import run_hourly_aggregation
from services.rule_engine import run_all_rules

BASE_DIR = Path(__file__).parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [live_cv_ingest] %(message)s")
logger = logging.getLogger("live_cv_ingest")

# One real camera per real zone — matches generate_cam_tracks.py's
# CAMERA_CONFIGS exactly (video file + which zones_config file to check it
# against). Add/remove entries here if the camera lineup ever changes.
CAMERAS = [
    {"id": "cam1", "video": "cam1.mp4", "zones_config": "zones_config_cam1.json"},
    {"id": "cam2", "video": "cam2.mp4", "zones_config": "zones_config_cam2.json"},
    {"id": "cam3", "video": "cam3.mp4", "zones_config": "zones_config_cam3.json"},
    {"id": "cam4", "video": "cam4.mp4", "zones_config": "zones_config_cam4.json"},
]

_threads: list[threading.Thread] = []
_stop_flag = threading.Event()


@dataclass
class LiveDetectionState:
    """Thread-safe snapshot of one camera's most recent real detections."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    frame_width: int = 0
    frame_height: int = 0
    timestamp: float = 0.0
    person_boxes: list = field(default_factory=list)
    equipment_rois: list = field(default_factory=list)  # static, set once at startup

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "frame_width": self.frame_width,
                "frame_height": self.frame_height,
                "timestamp": round(self.timestamp, 2),
                "person_boxes": list(self.person_boxes),
                "equipment_rois": list(self.equipment_rois),
            }


# Per-camera live state, keyed by camera id — e.g. live_detection_states["cam1"]
live_detection_states: dict[str, LiveDetectionState] = {
    cam["id"]: LiveDetectionState() for cam in CAMERAS
}

# Backward-compat alias: some routes (routers/live.py's no-camera-id
# fallback) expect a single `live_detection_state`. Point it at cam1 so
# that old code path still returns something real instead of breaking.
live_detection_state = live_detection_states["cam1"]


def _run_camera_loop(cam_id: str, video_path: str, zones_config_path: str,
                      log_interval_sec: float, loop_video: bool):
    state = live_detection_states[cam_id]
    detector = PersonDetector()
    tracker = ZoneTracker(zones_config_path)

    logger.info(f"[{cam_id}] Starting live CV ingest — video={video_path} "
                f"zones={zones_config_path} log_interval={log_interval_sec}s")

    # Real wall-clock elapsed time, not video-internal time — see the
    # single-camera version's original comment for why: video-internal
    # time resets to 0 on every loop restart, which would make idle/busy
    # streak math jump backwards and produce nonsense.
    ingest_start = time.time()

    import cv2
    probe = cv2.VideoCapture(video_path)
    if probe.isOpened():
        with state.lock:
            state.frame_width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))
            state.frame_height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    probe.release()

    with state.lock:
        state.equipment_rois = [
            {"id": eq.id, "name": eq.name, "bbox": eq.bbox}
            for eq in tracker.equipment.values()
        ]

    last_ingest_at = -log_interval_sec  # force an immediate first write

    def on_frame(detections, video_time):
        elapsed = time.time() - ingest_start
        centroids = [d.centroid for d in detections]
        tracker.update(person_centroids=centroids, timestamp=elapsed)

        with state.lock:
            state.timestamp = elapsed
            state.person_boxes = [d.to_dict() for d in detections]

        # Gate DB writes on real wall-clock time, not video-internal time —
        # see module docstring in the original single-camera version for
        # why (CPU-bound inference can run slower than the video's native
        # frame rate, which would otherwise make the dashboard go stale).
        nonlocal last_ingest_at
        if elapsed - last_ingest_at >= log_interval_sec:
            last_ingest_at = elapsed
            snapshot = {
                "timestamp": elapsed,
                "wall_clock": datetime.now().isoformat(),
                "total_count": len(detections),
                "zone_counts": tracker.get_zone_counts(),
                "equipment_status": tracker.get_equipment_status(elapsed),
            }
            rows = ingest_snapshot(snapshot)
            logger.info(f"[{cam_id}] t={elapsed:.1f}s  count={len(detections)}  "
                        f"wrote {rows} rows to raw_detections")

            # Keep hourly_stats / heatmap_data / rule_triggers fresh
            # continuously rather than waiting for the once-an-hour cron.
            # Cheap — only processes a recent rolling window — but 4
            # cameras all doing this on their own schedule means it runs
            # more often than with 1; still negligible cost for a demo.
            try:
                run_hourly_aggregation()
                run_all_rules()
            except Exception as agg_err:  # noqa: BLE001
                logger.error(f"[{cam_id}] aggregation/rules error: {agg_err}")

    while not _stop_flag.is_set():
        try:
            for _ in detector.run(
                source=video_path,
                log_interval_sec=log_interval_sec,
                on_frame=on_frame,
            ):
                if _stop_flag.is_set():
                    break

            if not loop_video:
                break
            # video ended — loop back to keep "live" data flowing
            # (ingest_start is NOT reset, so elapsed time keeps climbing)

        except Exception as e:  # noqa: BLE001
            logger.error(f"[{cam_id}] live CV ingest error: {e}")
            time.sleep(3)  # avoid a tight crash loop on a bad video path


def start_live_ingest(
    log_interval_sec: float = 10.0,
    loop_video: bool = True,
    cameras: Optional[list[dict]] = None,
):
    """Call once at FastAPI startup. Safe to call more than once — ignored
    if threads are already running.

    Starts ONE background thread per camera in `cameras` (defaults to all
    4 real cameras in CAMERAS above), each independently watching its own
    video and writing real detections for its own zone into the shared
    database. Person 2's /stats/current endpoint already sums each zone's
    latest row regardless of which camera wrote it, so no backend changes
    were needed for multi-camera data to compose correctly."""
    global _threads
    if _threads and any(t.is_alive() for t in _threads):
        return

    cams = cameras if cameras is not None else CAMERAS
    _stop_flag.clear()
    _threads = []
    for cam in cams:
        video_path = str(BASE_DIR / "test_assets" / cam["video"])
        zones_config_path = str(BASE_DIR / "data" / cam["zones_config"])
        t = threading.Thread(
            target=_run_camera_loop,
            args=(cam["id"], video_path, zones_config_path, log_interval_sec, loop_video),
            daemon=True,
        )
        t.start()
        _threads.append(t)


def stop_live_ingest():
    _stop_flag.set()
    for t in _threads:
        t.join(timeout=5)


if __name__ == "__main__":
    # Manual test: run all 4 cameras for ~30 seconds, then stop.
    # (Run this from the backend/ folder: python live_cv_ingest.py)
    start_live_ingest(loop_video=False)
    time.sleep(30)
    stop_live_ingest()
    print("Stopped. Check data/stats_store.db (or hit /stats/current once "
          "the server's running) to see the real rows that got written.")
