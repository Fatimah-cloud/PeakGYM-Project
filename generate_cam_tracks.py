"""
generate_cam_tracks.py
----------------------
Runs YOLOv8 person detection once per second across cam1.mp4, cam2.mp4, cam3.mp4, cam4.mp4, demo_video.mp4.
Saves JSON tracks for the frontend UI and backend API.
"""

import json
from pathlib import Path
import cv2
from services.person_detector import PersonDetector

BASE_DIR = Path(__file__).parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
ASSETS_DIR = BASE_DIR / "test_assets"
OUT_DIR_BACKEND = BASE_DIR / "data" / "detections"
OUT_DIR_FRONTEND = FRONTEND_DIR / "assets" / "detections"

OUT_DIR_BACKEND.mkdir(parents=True, exist_ok=True)
OUT_DIR_FRONTEND.mkdir(parents=True, exist_ok=True)

CAMERA_CONFIGS = {
    "cam1": {
        "id": "cam1",
        "name": "CAM 01 — Squat Rack & Bench Area",
        "zone_id": "zone_squat_bench",
        "zone_name": "Squat Rack & Bench Area",
        "video_file": "cam1.mp4",
        "equipment": [
            {"id": "squat_rack_1", "name": "Squat Rack #1", "bbox": [50, 40, 240, 360]},
            {"id": "squat_rack_2", "name": "Squat Rack #2", "bbox": [310, 50, 480, 360]},
            {"id": "adjustable_bench_1", "name": "Adjustable Bench #1", "bbox": [620, 60, 800, 350]},
        ]
    },
    "cam2": {
        "id": "cam2",
        "name": "CAM 02 — Free Weights Aisle",
        "zone_id": "zone_freeweights_aisle",
        "zone_name": "Free Weights Aisle",
        "video_file": "cam2.mp4",
        "equipment": [
            {"id": "dumbbell_rack_1", "name": "Dumbbell Rack Main", "bbox": [100, 160, 340, 430]},
            {"id": "adjustable_bench_2", "name": "Flat Workout Bench", "bbox": [320, 150, 480, 320]},
            {"id": "free_weight_station", "name": "Free Weight Area", "bbox": [500, 50, 650, 260]}
        ]
    },
    "cam3": {
        "id": "cam3",
        "name": "CAM 03 — Cable & Functional Zone",
        "zone_id": "zone_cable_stations",
        "zone_name": "Cable / Functional Trainer Zone",
        "video_file": "cam3.mp4",
        "equipment": [
            {"id": "cable_station_1", "name": "Cable Crossover #1", "bbox": [140, 80, 340, 420]},
            {"id": "cable_station_2", "name": "Cable Crossover #2", "bbox": [330, 120, 460, 420]},
            {"id": "cable_station_3", "name": "Functional Dual Pulley", "bbox": [450, 60, 650, 260]},
        ]
    },
    "cam4": {
        "id": "cam4",
        "name": "CAM 04 — Machine Row",
        "zone_id": "zone_machine_row",
        "zone_name": "Machine Row",
        "video_file": "cam4.mp4",
        "equipment": [
            {"id": "leg_press_sled_1", "name": "Leg Press / Hack Squat #1", "bbox": [180, 40, 320, 260]},
            {"id": "leg_press_sled_2", "name": "Leg Press / Hack Squat #2", "bbox": [400, 80, 520, 330]},
            {"id": "chest_press_machine_1", "name": "Chest Press Machine", "bbox": [600, 240, 800, 455]},
        ]
    },
    "demo": {
        "id": "demo",
        "name": "Surveillance Overview (Wide Angle)",
        "zone_id": "zone_overview",
        "zone_name": "Main Gym Floor Overview",
        "video_file": "demo_video.mp4",
        "equipment": [
            {"id": "squat_rack_1", "name": "Squat Station", "bbox": [100, 200, 400, 800]},
            {"id": "dumbbell_rack_1", "name": "Dumbbell Area", "bbox": [500, 250, 900, 750]},
            {"id": "cable_station_1", "name": "Cable Zone", "bbox": [950, 200, 1400, 850]},
            {"id": "leg_press_sled_1", "name": "Machine Station", "bbox": [1450, 250, 1850, 850]},
        ]
    }
}


def bbox_overlap(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    return interArea > 0


def point_in_bbox(point, box):
    x, y = point
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def main():
    print("Loading YOLOv8n model...")
    detector = PersonDetector(conf_threshold=0.35)
    all_camera_data = {}

    for cam_key, cam_info in CAMERA_CONFIGS.items():
        video_path = ASSETS_DIR / cam_info["video_file"]
        if not video_path.exists():
            print(f"Skipping {cam_key}: {video_path} not found")
            continue

        cap = cv2.VideoCapture(str(video_path))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        print(f"[{cam_key}] Reading {cam_info['video_file']} ({w}x{h}, {duration:.1f}s)...")

        # Step by 1 second of video
        step_frames = max(1, int(fps * 1.0))
        frames_data = []

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step_frames == 0:
                t = round(frame_idx / fps, 2)
                dets = detector.detect_frame(frame)

                person_list = []
                for p_idx, d in enumerate(dets):
                    person_list.append({
                        "id": f"P-{cam_key.upper()}-{p_idx + 1:02d}",
                        "bbox": [round(c, 1) for c in d.bbox],
                        "confidence": round(d.confidence, 2),
                        "centroid": [round(c, 1) for c in d.centroid]
                    })

                eq_status = []
                for eq in cam_info["equipment"]:
                    occupied = False
                    eq_bbox = eq["bbox"]
                    for p in person_list:
                        if point_in_bbox(p["centroid"], eq_bbox) or bbox_overlap(p["bbox"], eq_bbox):
                            occupied = True
                            break
                    eq_status.append({
                        "id": eq["id"],
                        "name": eq["name"],
                        "bbox": eq["bbox"],
                        "status": "in_use" if occupied else "available"
                    })

                frames_data.append({
                    "time": t,
                    "count": len(person_list),
                    "persons": person_list,
                    "equipment": eq_status
                })

            frame_idx += 1

        cap.release()

        cam_payload = {
            "camera_id": cam_key,
            "name": cam_info["name"],
            "zone_id": cam_info["zone_id"],
            "zone_name": cam_info["zone_name"],
            "video_file": cam_info["video_file"],
            "frame_width": w,
            "frame_height": h,
            "fps": round(fps, 1),
            "duration": round(duration, 2),
            "equipment_rois": cam_info["equipment"],
            "tracks": frames_data
        }

        all_camera_data[cam_key] = cam_payload

        # Write per-camera file
        with open(OUT_DIR_BACKEND / f"{cam_key}_detections.json", "w", encoding="utf-8") as f:
            json.dump(cam_payload, f, indent=2)
        with open(OUT_DIR_FRONTEND / f"{cam_key}_detections.json", "w", encoding="utf-8") as f:
            json.dump(cam_payload, f, indent=2)

        print(f"[{cam_key}] Finished: {len(frames_data)} timestamps generated.")

    # Write multi-cam summary
    with open(OUT_DIR_BACKEND / "all_cameras_tracks.json", "w", encoding="utf-8") as f:
        json.dump(all_camera_data, f, indent=2)
    with open(OUT_DIR_FRONTEND / "all_cameras_tracks.json", "w", encoding="utf-8") as f:
        json.dump(all_camera_data, f, indent=2)

    print("ALL CAMERA DETECTIONS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
