"""
Compare what each YOLO model sees on ONE saved frame.

Usage (from your project folder):
    python debug_detect.py frame.jpg
    python debug_detect.py frame.jpg 640            # try a bigger inference size
    python debug_detect.py frame.jpg 480 yolov8s.pt # try a bigger pretrained model

It prints the class names stored inside best.pt (check them against the mapping in
yolo_detector.py!), then every detection from each model, and saves two images:
    debug_pretrained.jpg   and   debug_custom.jpg
"""
import sys
import cv2
from ultralytics import YOLO

if len(sys.argv) < 2:
    sys.exit(__doc__)

image_path = sys.argv[1]
imgsz = int(sys.argv[2]) if len(sys.argv) > 2 else 480
pre_name = sys.argv[3] if len(sys.argv) > 3 else "yolov8n.pt"
cus_name = "best.pt"
CONF = 0.10   # low on purpose, so you can see what the models almost detect

frame = cv2.imread(image_path)
if frame is None:
    sys.exit(f"Could not read {image_path}")
print(f"Frame: {frame.shape[1]}x{frame.shape[0]}  |  imgsz={imgsz}  |  conf>={CONF}\n")

for label, weights, out in (("PRETRAINED", pre_name, "debug_pretrained.jpg"),
                            ("CUSTOM", cus_name, "debug_custom.jpg")):
    model = YOLO(weights)
    print(f"=== {label} ({weights}) ===")
    print("class names inside the model:", model.names)
    res = model.predict(frame, imgsz=imgsz, conf=CONF, agnostic_nms=True, verbose=False)[0]
    rows = []
    for box in res.boxes:
        cls_id = int(box.cls[0])
        rows.append((float(box.conf[0]), model.names[cls_id], [int(v) for v in box.xyxy[0]]))
    rows.sort(reverse=True)
    for conf, name, xyxy in rows:
        print(f"  {name:<18} {conf:.2f}  {xyxy}")
    counts = {}
    for _, name, _ in rows:
        counts[name] = counts.get(name, 0) + 1
    print("  totals:", counts or "nothing detected")
    cv2.imwrite(out, res.plot())
    print(f"  saved {out}\n")
