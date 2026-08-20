"""
equipment_detector.py
----------------------
Person 1 — Computer Vision (Detection & Tracking)

Detects gym EQUIPMENT objects in a frame (as opposed to person_detector.py,
which detects people). This is used to:
  1. Verify/calibrate the ROIs in zones_config.json (does the treadmill
     bbox actually line up with where the treadmill is in frame?)
  2. Optionally auto-suggest ROI boxes for new equipment.

NOTE ON THE ACTUAL "IS THIS TREADMILL IN USE" DECISION:
Per the project plan, in-use/idle status is decided by whether a detected
PERSON's centroid falls inside an equipment ROI — that logic lives in
zone_tracker.py, and it only needs person_detector.py + the ROI coordinates.
equipment_detector.py is NOT required for that core loop to work. It's the
piece that helps you draw/verify the ROIs in the first place, and it's what
you point at if a supervisor asks "how do you know that box is actually the
treadmill" — you show equipment_detector.py's own bounding boxes.

--------------------------------------------------------------------------
ROBOFLOW MODEL RESEARCH (subtask: "search Roboflow for a pretrained
gym-equipment model, evaluate coverage of needed classes")

Checked universe.roboflow.com/search?q=class%3Agym — three strong pretrained
candidates as of this writing:

  1. "Fitness Equipment Recognition" by Atlas (yolov11n)
     https://universe.roboflow.com/atlas-ope08/fitness-equipment-recognition-wlluo-rj8jb
     24 classes incl. Person, Treadmill, Leg Press, Barbell, Dumbbell,
     Smith Machine, Cable Machine, Lat Pulldown, Chest Press, etc.
     mAP@50 90.9%, Precision 87.9% — best accuracy of the candidates found
     and already includes "Person", so it could double as a sanity check
     against person_detector.py's YOLO-COCO counts.

  2. "All Gym Equipment" by FitFuel / FitAi (yolov8)
     https://universe.roboflow.com/fitfuel/all-gym-equipment
     29 classes — widest class coverage (includes things like Ab Roller,
     Stepmill, Stability Ball) but mAP@50 ~79-81%, somewhat lower accuracy.

  3. "Dumbbell Detection" by Gym Equipment Detection
     https://universe.roboflow.com/gym-equipment-detection/dumbbell-detection
     Single-class (dumbbell only) — only useful as a narrow fallback if a
     multi-class model misses dumbbells specifically.

RECOMMENDATION: start with (1) Atlas's model — best accuracy and covers
every equipment type in our current zones_config.json (treadmill, leg
press, bench/barbell). Download its exported weights from the Roboflow
project page ("Download this Dataset" -> or "Deploy Model" -> export
weights), drop the .pt file into backend/models/yolo_equipment.pt, and
point EQUIPMENT_MODEL_PATH below at it.

If the actual gym has equipment none of these models cover well, that's
where fine-tuning comes in — see train_equipment_model.py in this same
folder for the fine-tuning script (50-100 images, starting from one of the
above as the base weights rather than training from scratch).
--------------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
from ultralytics import YOLO

EQUIPMENT_MODEL_PATH = "../models/yolo_equipment.pt"  # set after downloading from Roboflow

# Normalizes whatever class names the Roboflow model uses to the equipment
# "type" values used in zones_config.json. Extend this as needed once you've
# picked a model and seen its actual class list (model.names).
CLASS_NAME_NORMALIZATION = {
    "treadmill": "treadmill",
    "leg press": "leg_press",
    "leg press machine": "leg_press",
    "bench": "bench_press",
    "bench press": "bench_press",
    "barbell": "barbell",
    "dumbbell": "dumbbell",
    "smith machine": "smith_machine",
    "cable machine": "cable_machine",
    "lat pulldown": "lat_pulldown",
}


@dataclass
class EquipmentDetection:
    label: str            # normalized type, e.g. "treadmill"
    raw_label: str         # whatever the model called it
    bbox: list
    confidence: float

    def to_dict(self) -> dict:
        return {"label": self.label, "raw_label": self.raw_label,
                "bbox": self.bbox, "confidence": round(self.confidence, 3)}


class EquipmentDetector:
    def __init__(self, model_path: str = EQUIPMENT_MODEL_PATH, conf_threshold: float = 0.4):
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.class_names = self.model.names  # {id: "Treadmill", ...}

    def detect_frame(self, frame) -> list[EquipmentDetection]:
        results = self.model.predict(frame, conf=self.conf_threshold, verbose=False)
        detections = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                raw_label = self.class_names[cls_id]
                normalized = CLASS_NAME_NORMALIZATION.get(raw_label.lower(), raw_label.lower())
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(EquipmentDetection(
                    label=normalized,
                    raw_label=raw_label,
                    bbox=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                    confidence=float(box.conf[0]),
                ))
        return detections

    def suggest_rois(self, video_path: str, sample_every_n_frames: int = 30,
                      max_frames_sampled: int = 60) -> dict:
        """
        Runs the equipment model over a sample of frames from a calibration
        video and returns the highest-confidence bbox seen for each detected
        equipment type. This is a starting point to paste into
        zones_config.json — always sanity-check by eye afterwards, since a
        single frame's detection can be noisy (someone standing in front of
        the machine, partial occlusion, etc).
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")

        best_by_label: dict[str, EquipmentDetection] = {}
        frame_idx = 0
        sampled = 0
        while sampled < max_frames_sampled:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % sample_every_n_frames == 0:
                sampled += 1
                for det in self.detect_frame(frame):
                    current_best = best_by_label.get(det.label)
                    if current_best is None or det.confidence > current_best.confidence:
                        best_by_label[det.label] = det
            frame_idx += 1
        cap.release()

        return {label: det.to_dict() for label, det in best_by_label.items()}


if __name__ == "__main__":
    # Quick manual smoke test:
    #   python equipment_detector.py path/to/calibration_video.mp4
    import json
    import sys

    video_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not video_path:
        print("Usage: python equipment_detector.py <video_path>")
        print("(Requires yolo_equipment.pt to exist at EQUIPMENT_MODEL_PATH — "
              "see the Roboflow notes in this file's docstring.)")
    else:
        detector = EquipmentDetector()
        print("Model classes:", detector.class_names)
        suggestions = detector.suggest_rois(video_path)
        print(json.dumps(suggestions, indent=2))
