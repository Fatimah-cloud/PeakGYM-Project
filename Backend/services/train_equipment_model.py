"""
train_equipment_model.py
--------------------------
Person 1 — Computer Vision (Detection & Tracking)

Fine-tuning script — ONLY needed if the pretrained Roboflow model (see the
notes at the top of equipment_detector.py) doesn't cover some piece of
equipment your gym actually has.

This does NOT train from scratch. It starts from an existing checkpoint
(either the Roboflow pretrained weights, or plain yolov8n.pt as a fallback)
and continues training on a small custom dataset — the spec calls for
50-100 images per missing class, which is enough for fine-tuning even
though it would be far too little to train a detector from zero.

--------------------------------------------------------------------------
HOW TO GET YOUR 50-100 IMAGES + LABELS (do this part outside this script):

  1. Take/collect ~50-100 photos of the missing equipment from a few angles
     and lighting conditions (ideally from roughly the camera's actual POV).
  2. Label them. Easiest free option: Roboflow's own annotation tool
     (roboflow.com -> new project -> upload images -> draw boxes -> export).
  3. Export in "YOLOv8" format. Roboflow gives you a folder like:

        my_dataset/
          train/images/, train/labels/
          valid/images/, valid/labels/
          data.yaml

     `data.yaml` is what YOLO training needs — point DATA_YAML below at it.
--------------------------------------------------------------------------

Usage (from backend/services/):
    python train_equipment_model.py --data path/to/data.yaml --base yolov8n.pt

Recommended for a graduation-project timeline / laptop or free Colab GPU:
    epochs=30-50, imgsz=640 is plenty for a handful of extra classes.
"""

from __future__ import annotations

import argparse

from ultralytics import YOLO


def fine_tune(data_yaml: str, base_weights: str = "yolov8n.pt",
              epochs: int = 40, imgsz: int = 640, project: str = "runs/equipment_finetune"):
    """
    data_yaml: path to the data.yaml exported from Roboflow (or any YOLO-
               format dataset config) describing your missing-equipment
               images.
    base_weights: starting checkpoint. Use the Roboflow gym model's .pt if
               you have it (best — it already knows general gym equipment
               shapes), otherwise plain yolov8n.pt works fine too.
    """
    model = YOLO(base_weights)
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=imgsz,
        project=project,
        name="finetune_run",
        patience=10,       # stop early if it stops improving
        exist_ok=True,
    )
    print("Training complete.")
    print(f"Best weights saved to: {project}/finetune_run/weights/best.pt")
    print("Copy that file to backend/models/yolo_equipment.pt to use it in "
          "equipment_detector.py")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune YOLO on missing gym equipment classes")
    parser.add_argument("--data", required=True, help="Path to data.yaml")
    parser.add_argument("--base", default="yolov8n.pt", help="Base checkpoint to fine-tune from")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    fine_tune(data_yaml=args.data, base_weights=args.base, epochs=args.epochs, imgsz=args.imgsz)
