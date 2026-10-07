# detection/yolo_detector.py
import logging
import threading
import cv2
import numpy as np
from typing import List, Dict, Optional


class YOLODetector:
    """YOLOv8 based object detection for traffic monitoring"""

    INFER_SIZE = 480  # long-side inference size; frames are letterboxed (not squashed). Override: SETTINGS['detector_imgsz']

    def __init__(self, model_name: str = "best.pt"):
        self.logger = logging.getLogger(__name__)
        self.pretrained_model = None
        self.custom_model = None
        self.pretrained_model_name = "yolov8n.pt"
        self.custom_model_name = model_name
        self.confidence_threshold = 0.25  # Lowered to 0.25 for blurry/small vehicle detection (like bicycles)

        # Check for CUDA availability
        try:
            import torch
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            self.device = "cpu"
        self.use_half = (self.device == "cuda")  # FP16 is much faster on NVIDIA GPUs

        self.pretrained_class_names = {
            0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
            5: "bus", 7: "truck", 8: "boat", 9: "traffic light",
            10: "fire hydrant", 11: "stop sign", 12: "parking meter"
        }
        # 'person' is never used, so don't even ask the model for it
        self.pretrained_class_ids = [k for k in self.pretrained_class_names if k != 0]

        # Class names reflect the actual best.pt model (6 classes only).
        # z_accident / z_jaywalker / z_non-jaywalker are NOT present in this model.
        self.custom_class_names = {
            0: 'bus',
            1: 'car',
            2: 'emergency_vehicle',
            3: 'jeepney',
            4: 'motorcycle',
            5: 'truck'
        }
        # Only these classes are taken from the custom model
        self.custom_wanted = {'emergency_vehicle', 'jeepney'}
        self.custom_class_ids = [k for k, v in self.custom_class_names.items() if v in self.custom_wanted]

        # The custom model only contributes emergency_vehicle / jeepney, so it does not
        # need to run on every call. Run it every N calls per stream and reuse the last
        # result in between. Override with SETTINGS["custom_model_every_n"]. Use 1 to run always.
        self.custom_every_n = 2

        # Accuracy options
        self.agnostic_nms = True            # one box per object (stops the same vehicle being a 'car' AND a 'truck')
        self.class_conf: Dict[str, float] = {}   # optional per-class thresholds, e.g. {"car": 0.4, "truck": 0.2}
        self._call_count: Dict = {}
        self._custom_cache: Dict = {}

        # One inference at a time (model objects are not meant to be shared across threads)
        self._lock = threading.Lock()

        self.color_map = {
            "car": (0, 255, 0),            # Green
            "motorcycle": (0, 255, 255),   # Yellow
            "bus": (255, 255, 0),          # Cyan
            "truck": (0, 165, 255),        # Orange
            "bicycle": (255, 0, 255),      # Magenta
            "person": (255, 255, 255),     # White
            "traffic light": (0, 0, 255),  # Red (default)
            "emergency_vehicle": (255, 0, 0), # Blue
            "jeepney": (128, 0, 128)       # Purple
        }
        self.load_models()

    # ------------------------------------------------------------------ #
    def load_models(self) -> bool:
        """Load YOLOv8 models"""
        try:
            from ultralytics import YOLO
            import sys
            import os
            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if workspace_dir not in sys.path:
                sys.path.insert(0, workspace_dir)
            from utils.paths import get_resource_path

            ptr_path = get_resource_path(self.pretrained_model_name)
            cus_path = get_resource_path(self.custom_model_name)

            self.pretrained_model = YOLO(ptr_path)
            self.pretrained_model.to(self.device)
            self.logger.info(f"YOLO pretrained model {self.pretrained_model_name} loaded successfully on {self.device}")

            self.custom_model = YOLO(cus_path)
            self.custom_model.to(self.device)
            self.logger.info(f"YOLO custom model {self.custom_model_name} loaded successfully on {self.device}")

            self._sync_custom_names()
            self._warmup()
            return True
        except Exception as e:
            self.logger.error(f"Failed to load YOLO models: {e}")
            return False

    def _sync_custom_names(self):
        """
        Read the class names stored INSIDE best.pt and compare them with the hard-coded
        mapping. A wrong mapping silently mislabels (or drops) ambulances/trucks.
        """
        try:
            names = getattr(self.custom_model, "names", None)
            if not isinstance(names, dict) or not names:
                return
            alias = {"ambulance": "emergency_vehicle", "emergency": "emergency_vehicle",
                     "emergency-vehicle": "emergency_vehicle", "emergency vehicle": "emergency_vehicle"}
            model_map = {}
            for k, v in names.items():
                n = str(v).strip().lower()
                model_map[int(k)] = alias.get(n, n)

            self.logger.info(f"best.pt class names: {names}")
            if model_map != self.custom_class_names:
                self.logger.warning(
                    f"best.pt classes differ from the hard-coded mapping. "
                    f"Using the model's own: {model_map} (was {self.custom_class_names})"
                )
                self.custom_class_names = model_map
            self.custom_class_ids = [k for k, v in self.custom_class_names.items() if v in self.custom_wanted]
            if not self.custom_class_ids:
                self.logger.warning("best.pt has no emergency_vehicle/jeepney class — emergency detection is impossible")
        except Exception as e:
            self.logger.warning(f"Could not read best.pt class names: {e}")

    def _warmup(self):
        """Run one dummy inference so the first real frame doesn't stall."""
        try:
            dummy = np.zeros((self.INFER_SIZE, self.INFER_SIZE, 3), dtype=np.uint8)
            with self._lock:
                self.pretrained_model.predict(dummy, imgsz=self.INFER_SIZE, device=self.device,
                                              half=self.use_half, verbose=False)
                self.custom_model.predict(dummy, imgsz=self.INFER_SIZE, device=self.device,
                                          half=self.use_half, verbose=False)
            self.logger.info("YOLO warm-up complete")
        except Exception as e:
            self.logger.warning(f"YOLO warm-up skipped: {e}")

    # ------------------------------------------------------------------ #
    def _parse_boxes(self, result, names_map: Dict[int, str], wanted: Optional[set],
                     x_scale: float, y_scale: float, source: str) -> List[Dict]:
        """Convert one ultralytics result into our detection dicts (original-frame coords)."""
        out: List[Dict] = []
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return out

        # Move everything to numpy once instead of indexing tensors box by box
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy().astype(int)

        for (bx1, by1, bx2, by2), conf, cls_id in zip(xyxy, confs, clss):
            conf = float(conf)
            class_name = names_map.get(int(cls_id))
            if not class_name or class_name == "person":
                continue
            if conf <= self.class_conf.get(class_name, self.confidence_threshold):
                continue
            if wanted is not None and class_name not in wanted:
                continue

            x1 = int(bx1 * x_scale)
            y1 = int(by1 * y_scale)
            x2 = int(bx2 * x_scale)
            y2 = int(by2 * y_scale)
            out.append({
                "class_id": int(cls_id),
                "class_name": class_name,
                "confidence": conf,
                "bbox": (x1, y1, x2, y2),
                "center": ((x1 + x2) // 2, (y1 + y2) // 2),
                "source": source
            })
        return out

    def detect(self, frame: np.ndarray, stream_key=None, draw: bool = True) -> Dict:
        """
        Detect objects in a frame using both models.

        stream_key : any hashable id for the video source (e.g. 'north'). Used to
                     cache the custom model's result per stream between runs.
        draw       : if False, skips drawing boxes and returns the original frame
                     as 'annotated_frame' (saves a full-frame copy per call).
        """
        if self.pretrained_model is None or self.custom_model is None:
            self.logger.warning("Models not loaded, skipping detection")
            return {"detections": [], "annotated_frame": frame}

        try:
            try:
                from utils.app_config import SETTINGS
            except ImportError:
                SETTINGS = {}

            # --- BLURRY VIDEO ENHANCEMENT (UNSHARP MASK) ---
            # Optional via SETTINGS, to conserve CPU
            enhancement_enabled = SETTINGS.get("enable_video_enhancement", False)
            if enhancement_enabled:
                blurred = cv2.GaussianBlur(frame, (0, 0), 3)
                eval_frame = cv2.addWeighted(frame, 1.5, blurred, -0.5, 0)
            else:
                eval_frame = frame

            # Ultralytics letterboxes the frame itself (keeps the aspect ratio) and returns
            # boxes in ORIGINAL frame coordinates, so no manual resize/rescale is needed.
            size = int(SETTINGS.get("detector_imgsz", self.INFER_SIZE))
            x_scale = y_scale = 1.0

            # Optionally let best.pt (trained on YOUR traffic) also detect cars/trucks/buses/
            # motorcycles. Otherwise it only supplies emergency_vehicle and jeepney.
            use_custom_for_vehicles = bool(SETTINGS.get("use_custom_for_vehicles", False))
            if use_custom_for_vehicles:
                custom_wanted = set(self.custom_class_names.values())
                custom_ids = list(self.custom_class_names.keys())
            else:
                custom_wanted = self.custom_wanted
                custom_ids = self.custom_class_ids

            min_conf = min([self.confidence_threshold] + list(self.class_conf.values()))
            agnostic = bool(SETTINGS.get("agnostic_nms", self.agnostic_nms))

            # Decide whether the custom model runs on this call (always, if it supplies vehicles)
            every_n = 1 if use_custom_for_vehicles else max(1, int(SETTINGS.get("custom_model_every_n", self.custom_every_n)))
            count = self._call_count.get(stream_key, 0)
            self._call_count[stream_key] = count + 1
            run_custom = (count % every_n == 0) or (stream_key not in self._custom_cache)

            # --- Inference ---
            with self._lock:
                results_pre = self.pretrained_model.predict(
                    eval_frame, imgsz=size, conf=min_conf,
                    classes=self.pretrained_class_ids, agnostic_nms=agnostic,
                    device=self.device, half=self.use_half, verbose=False
                )
                results_custom = None
                if run_custom and custom_ids:
                    results_custom = self.custom_model.predict(
                        eval_frame, imgsz=size, conf=min_conf,
                        classes=custom_ids, agnostic_nms=agnostic,
                        device=self.device, half=self.use_half, verbose=False
                    )

            pre_dets: List[Dict] = []
            if results_pre and len(results_pre) > 0:
                pre_dets = self._parse_boxes(
                    results_pre[0], self.pretrained_class_names, None, x_scale, y_scale, "pretrained"
                )

            if run_custom:
                custom_dets: List[Dict] = []
                if results_custom and len(results_custom) > 0:
                    custom_dets = self._parse_boxes(
                        results_custom[0], self.custom_class_names, custom_wanted,
                        x_scale, y_scale, "custom"
                    )
                self._custom_cache[stream_key] = custom_dets
            else:
                custom_dets = list(self._custom_cache.get(stream_key, []))

            # --- Non-Maximum Suppression (Deduplication) ---
            # Remove pretrained detections (like car/truck) that heavily overlap with
            # custom detections (e.g. emergency vehicle)
            final_detections: List[Dict] = list(custom_dets)

            for p_det in pre_dets:
                overlap = False
                px1, py1, px2, py2 = p_det["bbox"]
                p_area = max(0, px2 - px1) * max(0, py2 - py1)

                for c_det in custom_dets:
                    cx1, cy1, cx2, cy2 = c_det["bbox"]

                    # Compute intersection
                    ix1, iy1 = max(px1, cx1), max(py1, cy1)
                    ix2, iy2 = min(px2, cx2), min(py2, cy2)

                    if ix1 < ix2 and iy1 < iy2:
                        i_area = (ix2 - ix1) * (iy2 - iy1)
                        # If pretrained box is mostly inside custom box, or overlaps heavily (>40%)
                        if p_area > 0 and (i_area / p_area) > 0.4:
                            overlap = True
                            break

                if not overlap:
                    final_detections.append(p_det)

            annotated_frame = self.draw_detections(frame, final_detections) if draw else frame

            return {
                "detections": final_detections,
                "annotated_frame": annotated_frame,
                "success": True
            }

        except Exception as e:
            self.logger.error(f"Detection error: {e}")
            return {"detections": [], "annotated_frame": frame, "success": False}

    # ------------------------------------------------------------------ #
    def draw_detections(self, frame: np.ndarray, detections: List[Dict]) -> np.ndarray:
        """Draw detections on a copy of the frame"""
        annotated_frame = frame.copy()

        for detection in detections:
            bbox = detection['bbox']
            x1, y1, x2, y2 = bbox
            class_name = detection['class_name']
            conf = detection.get('confidence', 1.0)

            # Get color based on class name (Default to Green)
            color = self.color_map.get(class_name, (0, 255, 0))

            # Draw bounding box
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)

            label = f"{class_name} {conf:.2f}"

            # Text background for better visibility
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv2.rectangle(annotated_frame, (x1, y1 - 20), (x1 + w, y1), color, -1)
            cv2.putText(annotated_frame, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

        return annotated_frame

    def detect_vehicles(self, frame: np.ndarray) -> List[Dict]:
        """Detect vehicles specifically"""
        result = self.detect(frame, draw=False)
        vehicles = [d for d in result["detections"] if d["class_name"] in ["car", "bus", "truck", "motorcycle", "bicycle", "emergency_vehicle", "jeepney"]]
        return vehicles

    def detect_traffic_lights(self, frame: np.ndarray) -> List[Dict]:
        """Detect traffic lights"""
        result = self.detect(frame, draw=False)
        lights = [d for d in result["detections"] if d["class_name"] == "traffic light"]
        return lights

    def set_confidence_threshold(self, threshold: float):
        """Set confidence threshold for detections"""
        self.confidence_threshold = max(0, min(1, threshold))
