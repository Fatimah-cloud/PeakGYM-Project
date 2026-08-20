"""
routers/live.py
-----------------
Person 1 & Multi-Camera Feed Support — real-time detection boxes and camera telemetry
for the frontend's Live Camera Feed overlay.

Provides:
- GET /live/cameras : List of available cameras (CAM 01 - CAM 04, Demo) with zones and resolution metadata
- GET /live/detections : Real-time detections from live_cv_ingest or active camera
- GET /live/detections/{camera_id} : Timestamped track detections for a specific camera
"""

import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Query

from live_cv_ingest import live_detection_state

BASE_DIR = Path(__file__).parent.parent
DETECTIONS_DIR = BASE_DIR / "data" / "detections"

router = APIRouter()

CAMERAS_METADATA = [
    {
        "id": "cam1",
        "name": "CAM 01 — Squat Rack & Bench Area",
        "zone_id": "zone_squat_bench",
        "zone_name": "Squat Rack & Bench Area",
        "video_file": "assets/cam1.mp4",
        "resolution": "832x384",
        "fps": 58.6,
        "equipment_count": 3
    },
    {
        "id": "cam2",
        "name": "CAM 02 — Free Weights Aisle",
        "zone_id": "zone_freeweights_aisle",
        "zone_name": "Free Weights Aisle",
        "video_file": "assets/cam2.mp4",
        "resolution": "816x464",
        "fps": 59.3,
        "equipment_count": 3
    },
    {
        "id": "cam3",
        "name": "CAM 03 — Cable & Functional Zone",
        "zone_id": "zone_cable_stations",
        "zone_name": "Cable / Functional Trainer Zone",
        "video_file": "assets/cam3.mp4",
        "resolution": "832x464",
        "fps": 59.2,
        "equipment_count": 3
    },
    {
        "id": "cam4",
        "name": "CAM 04 — Machine Row",
        "zone_id": "zone_machine_row",
        "zone_name": "Machine Row",
        "video_file": "assets/cam4.mp4",
        "resolution": "816x464",
        "fps": 58.2,
        "equipment_count": 3
    },
    {
        "id": "demo",
        "name": "CAM Overview — Main Surveillance Stream",
        "zone_id": "zone_overview",
        "zone_name": "Main Gym Floor Overview",
        "video_file": "assets/demo_video.mp4",
        "resolution": "1920x1080",
        "fps": 25.0,
        "equipment_count": 4
    }
]


@router.get("/cameras")
def get_cameras():
    """Returns list of configured surveillance camera angles."""
    return {"cameras": CAMERAS_METADATA}


@router.get("/detections")
def get_live_detections(camera_id: Optional[str] = Query(None)):
    """Real person bounding boxes and equipment states.
    If camera_id is provided, loads the calibrated detection metadata for that camera;
    otherwise returns the live_cv_ingest snapshot."""
    if camera_id and DETECTIONS_DIR.exists():
        cam_file = DETECTIONS_DIR / f"{camera_id}_detections.json"
        if cam_file.exists():
            with open(cam_file, "r", encoding="utf-8") as f:
                return json.load(f)

    # Fallback / default live snapshot from live_cv_ingest
    return live_detection_state.to_dict()


@router.get("/detections/{camera_id}")
def get_camera_detections(camera_id: str):
    """Returns the full detection track and equipment metadata for a specific camera."""
    cam_file = DETECTIONS_DIR / f"{camera_id}_detections.json"
    if cam_file.exists():
        with open(cam_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"error": f"Camera tracks for {camera_id} not found", "camera_id": camera_id}
