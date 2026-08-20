"""
person_detector.py
-------------------
Person 1 — Computer Vision (Detection & Tracking)

Uses a PRETRAINED YOLOv8 model (trained on COCO) to detect people in a video
stream. No retraining needed — "person" is class 0 in the standard COCO
weights and detects well out of the box.

Works identically whether the source is:
  - a live camera:      PersonDetector(source=0)
  - an RTSP camera URL: PersonDetector(source="rtsp://...")
  - a pre-recorded demo video: PersonDetector(source="demo.mp4")
This is the "one-line difference" mentioned in the project plan — cv2 handles
files and camera indices/URLs through the exact same VideoCapture interface.

Public interface (this is what Person 2 / stats_aggregator.py will consume):
    detector = PersonDetector()
    for data_point in detector.run(source="demo.mp4", log_interval_sec=30):
        # data_point = {
        #     "timestamp": 12.5,          # seconds into the video/stream
        #     "wall_clock": "2025-06-01T10:00:12",
        #     "count": 7,
        #     "detections": [ {"bbox": [x1,y1,x2,y2], "confidence": 0.91,
        #                       "centroid": [x, y]}, ... ]
        # }
        send_to_aggregator(data_point)   # <- Person 2 plugs in here
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Generator, Optional

import cv2
from ultralytics import YOLO

PERSON_CLASS_ID = 0  # COCO class index for "person"


@dataclass
class Detection:
    bbox: list          # [x1, y1, x2, y2] in pixel coords
    confidence: float
    centroid: list       # [cx, cy]

    def to_dict(self) -> dict:
        return {"bbox": self.bbox, "confidence": round(self.confidence, 3),
                "centroid": self.centroid}


@dataclass
class DataPoint:
    timestamp: float          # seconds into the video/stream
    wall_clock: str
    count: int
    detections: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": round(self.timestamp, 2),
            "wall_clock": self.wall_clock,
            "count": self.count,
            "detections": [d.to_dict() for d in self.detections],
        }


class PersonDetector:
    def __init__(self, model_path: str = "yolov8n.pt", conf_threshold: float = 0.4,
                 device: Optional[str] = None):
        """
        model_path: pretrained COCO weights. yolov8n (nano) is fast enough for
                    a laptop CPU; swap to yolov8s/yolov8m if you have a GPU and
                    want higher accuracy.
        conf_threshold: minimum confidence to count a detection as a real person.
        device: "cpu", "cuda", or None to let ultralytics auto-pick.
        """
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.device = device

    def detect_frame(self, frame) -> list[Detection]:
        """Run detection on a single frame, return only 'person' detections."""
        results = self.model.predict(
            frame,
            classes=[PERSON_CLASS_ID],
            conf=self.conf_threshold,
            device=self.device,
            verbose=False,
        )
        detections = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                detections.append(Detection(
                    bbox=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                    confidence=conf,
                    centroid=[round(cx, 1), round(cy, 1)],
                ))
        return detections

    def run(
        self,
        source,
        log_interval_sec: float = 30.0,
        on_data_point: Optional[Callable[[DataPoint], None]] = None,
        on_frame: Optional[Callable[[list[Detection], float], None]] = None,
        jsonl_log_path: Optional[str] = None,
        save_annotated_video_path: Optional[str] = None,
        max_seconds: Optional[float] = None,
        display: bool = False,
    ) -> Generator[DataPoint, None, None]:
        """
        Process a video source frame-by-frame and yield a DataPoint every
        `log_interval_sec` seconds of VIDEO time (matches the spec: "a data
        point logged every 30 seconds").

        Every frame is still analyzed for a smooth live headcount + optional
        annotated video; only the periodic snapshot gets logged/yielded,
        which is what feeds the stats_aggregator / stats_store.db later.

        IMPORTANT: a person can be detected for only a frame or two (motion
        blur, brief occlusion, standing at the edge of the frame) and then
        be gone again before the next logged data point. If you only react
        to `on_data_point`, those brief detections are silently lost — which
        matters a lot for equipment-in-use tracking (someone briefly at a
        machine should still count as "used it"). That's what `on_frame` is
        for: it fires on EVERY analyzed frame, not just the logged ones, so
        zone_tracker.py can catch every detection as it happens rather than
        only whatever happened to be true at the exact log instant.

        source: 0 for default webcam, an RTSP/HTTP URL for a real camera, or
                a file path for the demo video.
        on_data_point: optional callback, fired every log_interval_sec —
                       e.g. hand this straight to Person 2's ingestion
                       function, or to a dashboard snapshot.
        on_frame: optional callback, fired on EVERY processed frame with
                       (detections, video_time_seconds) — this is what
                       zone_tracker.py should be driven from, so occupancy/
                       idle tracking doesn't miss brief detections.
        jsonl_log_path: if given, appends each DataPoint as one JSON line
                        (simple stand-in until stats_store.db is wired up).
        save_annotated_video_path: if given, writes an .mp4 with bounding
                        boxes + live count drawn on it (handy for the demo).
        max_seconds: stop early after this many seconds of video time
                     (useful for quick tests).
        display: if True, opens an OpenCV window showing detections live.
        """
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video source: {source}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        writer = None
        if save_annotated_video_path:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(save_annotated_video_path, fourcc, fps, (width, height))

        jsonl_file = open(jsonl_log_path, "a", encoding="utf-8") if jsonl_log_path else None

        frame_idx = 0
        next_log_at = 0.0
        start_wall = datetime.now()

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                video_time = frame_idx / fps
                if max_seconds is not None and video_time > max_seconds:
                    break

                detections = self.detect_frame(frame)

                if on_frame:
                    on_frame(detections, video_time)

                if writer is not None or display:
                    annotated = frame.copy()
                    for d in detections:
                        x1, y1, x2, y2 = map(int, d.bbox)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 0), 2)
                    cv2.putText(annotated, f"Count: {len(detections)}", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 0), 2)
                    if writer is not None:
                        writer.write(annotated)
                    if display:
                        cv2.imshow("Smart Gym - Person Detection", annotated)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break

                if video_time >= next_log_at:
                    dp = DataPoint(
                        timestamp=video_time,
                        wall_clock=(start_wall + timedelta(seconds=video_time)).isoformat(),
                        count=len(detections),
                        detections=detections,
                    )
                    if jsonl_file:
                        jsonl_file.write(json.dumps(dp.to_dict()) + "\n")
                        jsonl_file.flush()
                    if on_data_point:
                        on_data_point(dp)
                    yield dp
                    next_log_at += log_interval_sec

                frame_idx += 1
        finally:
            cap.release()
            if writer is not None:
                writer.release()
            if jsonl_file:
                jsonl_file.close()
            if display:
                cv2.destroyAllWindows()


if __name__ == "__main__":
    # Quick manual smoke test:
    #   python person_detector.py path/to/demo_video.mp4
    import sys

    video_path = sys.argv[1] if len(sys.argv) > 1 else 0
    detector = PersonDetector()
    print(f"Running person detection on: {video_path}")
    for point in detector.run(
        source=video_path,
        log_interval_sec=5,       # shortened for quick manual testing
        jsonl_log_path="person_log.jsonl",
        max_seconds=30,
    ):
        print(f"[t={point.timestamp:6.1f}s] count={point.count}")
