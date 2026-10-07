# controllers/main_controller.py
import tkinter as tk
import threading
import time
import cv2
import numpy as np
import logging
from datetime import datetime
from detection.camera_manager import CameraManager
from detection.traffic_controller import TrafficLightController
from detection.yolo_detector import YOLODetector
from views.pages import (
    DashboardPage, TrafficReportsPage, IncidentHistoryPage,
    ViolationLogsPage, SettingsPage, IssueReportsPage, AdminUsersPage
)

from views.components.notification import NotificationManager

class MainController:
    """Main application controller with 4-way camera and AI integration"""
    
    def __init__(self, root, view, db=None, current_user=None, auth_controller=None, on_logout_callback=None, violation_controller=None, accident_controller=None):
        self.root = root
        self.view = view
        self.db = db
        self.current_user = current_user
        self.auth_controller = auth_controller
        self.violation_controller = violation_controller
        self.accident_controller = accident_controller
        self.on_logout_callback = on_logout_callback
        
        # Initialize Notification System
        self.notification_manager = NotificationManager(root)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Navigation tracking
        self.current_page = None
        self.pages = {}
        
        # Directions configuration (map to lane IDs)
        self.directions = ['north', 'south', 'east', 'west']
        self.lane_names = {0: 'North Gate', 1: 'South Junction', 2: 'East Portal', 3: 'West Avenue'}
        self.direction_to_lane = {
            'north': 0,
            'south': 1,
            'east': 2,
            'west': 3
        }
        
        # Camera Managers (0, 1, 2, 3)
        self.camera_managers = {}
        for i, direction in enumerate(self.directions):
            self.camera_managers[direction] = CameraManager(camera_index=i)
            
        # Initialize YOLO and DQN-based Traffic Controller
        # Try to load the best trained model; fall back to fresh model if not found
        import os as _os
        import sys
        
        # PyInstaller safe paths
        workspace_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if workspace_dir not in sys.path:
            sys.path.insert(0, workspace_dir)
        from utils.paths import get_resource_path
            
        _model_candidates = [
            "smart_traffic_dqn.zip",
            "Optiflow_Dqn.pth",
            "models/dqn/dqn_best.pth",
            "models/dqn/dqn_final.pth",
        ]
        _selected_model = next(
            (get_resource_path(p) for p in _model_candidates if _os.path.exists(get_resource_path(p))), None
        )
        self.yolo_detector = YOLODetector("best.pt")
        self.traffic_controller = TrafficLightController(
            num_lanes=4,
            model_path=_selected_model,
            use_pretrained=(_selected_model is not None)
        )
        if _selected_model:
            self.logger.info(f"[Main] Loaded trained DQN model: {_selected_model}")
        else:
            self.logger.warning("[Main] No trained DQN model found — using untrained network. Run run_training.py first.")

        # Wire violation screenshot callback into the DQN Rule Controller
        # so frames are auto-saved whenever a z_jaywalker detection fires.
        self.traffic_controller.set_screenshot_callback(self._rule_violation_screenshot)

        # Per-lane frame cache so the rule controller can capture the right frame
        self._lane_frames: dict = {i: None for i in range(4)}
        
        # Traffic States for each direction
        self.states = {}
        for direction in self.directions:
            self.states[direction] = {
                'signal_state': 'RED',
                'time_remaining': 0,
                'last_update_time': time.time(),
                'vehicle_count': 0,
                'detections': [],
                'phase_start_time': time.time(),
                'last_ai_time': 0,
                'cached_detections': [],
                'current_source': 'Simulated'
            }
        
        # The controller owns the real signal state; initialize the dashboard
        # to the synchronized NS pair until the first controller sync arrives.
        self.states['north']['signal_state'] = 'GREEN'
        self.states['south']['signal_state'] = 'GREEN'
        self.states['north']['time_remaining'] = 60
        self.states['south']['time_remaining'] = 60
        
        self.logger.info("Initial traffic state: synchronized NS GREEN")
        
        # specific counters
        self.session_violations = 0
        
        # Per-lane accident tracking for multi-frame confirmation
        # Counts consecutive frames where a collision candidate is detected.
        # Accident is only confirmed after ACCIDENT_CONFIRM_FRAMES consecutive hits.
        self._accident_frame_counts = {i: 0 for i in range(4)}

        # Prohibited stopping tracker
        self.PROHIBITED_STOP_SECONDS = 300
        self._prohibited_stop_tracker: dict = {d: {} for d in ['north', 'south', 'east', 'west']}

        # Blocking intersection tracker
        # Fires when a vehicle is stationary BEYOND the stop line while RED
        # for >= BLOCKING_INTERSECTION_SECONDS continuously.
        self.BLOCKING_INTERSECTION_SECONDS = 20
        # direction -> { grid_key: {"first_seen": float, "logged": bool} }
        self._blocking_intersection_tracker: dict = {d: {} for d in ['north', 'south', 'east', 'west']}

        # Wrong-way driving detector
        # Fires after WRONG_WAY_CONFIRM_SECONDS of confirmed counter-flow movement.
        self.WRONG_WAY_CONFIRM_SECONDS = 3.0
        self._wrong_way_tracker: dict  = {d: {} for d in ['north', 'south', 'east', 'west']}
        self._wrong_way_next_id: dict  = {d: 0   for d in ['north', 'south', 'east', 'west']}

        # High congestion notification
        # Fires when a lane hits 40+ vehicles, re-alerts every 60 s while still congested.
        self.CONGESTION_VEHICLE_THRESHOLD = 40
        self.CONGESTION_NOTIFY_INTERVAL   = 60   # seconds between repeat alerts
        self._congestion_last_notify: dict = {d: 0.0 for d in ['north', 'south', 'east', 'west']}

        # Low traffic performance notification (fires when a lane drops below threshold)
        self.LOW_TRAFFIC_THRESHOLD      = 5    # fewer than this = low traffic
        self.LOW_TRAFFIC_NOTIFY_INTERVAL = 120  # seconds between per-lane alerts
        self._low_traffic_last_notify: dict = {d: 0.0 for d in ['north', 'south', 'east', 'west']}

        # Metrics for green light efficiency and hourly traffic flow
        self._system_start_time = time.time()
        self._lane_green_ticks:  dict = {d: 0 for d in ['north', 'south', 'east', 'west']}
        self._lane_total_ticks:  dict = {d: 0 for d in ['north', 'south', 'east', 'west']}
        self._lane_throughput:   dict = {d: 0 for d in ['north', 'south', 'east', 'west']}
        self._lane_prev_count:   dict = {d: 0 for d in ['north', 'south', 'east', 'west']}

        # Threading
        self.camera_thread = None
        self.is_running = True
        
        # Track read issue reports
        self.last_viewed_report_count = 0
        # Wait for initialize_pages or first poll to load actual count from DB
        
        self.logger.info("MainController initialized with DQN traffic control")
    
    def initialize_pages(self):
        """Initialize all application pages"""
        if self.view and hasattr(self.view, 'content_area'):
            self.pages['dashboard'] = DashboardPage(self.view.content_area)
            self.pages['issue_reports'] = IssueReportsPage(self.view.content_area, self.db, self.current_user)
            self.pages['traffic_reports'] = TrafficReportsPage(self.view.content_area)
            self.pages['incident_history'] = IncidentHistoryPage(self.view.content_area, self.accident_controller, self.current_user)
            self.pages['violation_logs'] = ViolationLogsPage(self.view.content_area, self.violation_controller, self.current_user)
            self.pages['settings'] = SettingsPage(self.view.content_area)
            
            # Admin Pages
            if self.current_user and self.current_user.get('role') == 'admin':
                if self.auth_controller:
                    self.pages['admin_users'] = AdminUsersPage(self.view.content_area, self.auth_controller)
    
    def get_active_cameras(self):
        """Get list of active cameras for the sidebar"""
        # Map logical directions to base names
        name_map = {
            'north': 'North Gate',
            'south': 'South Junction',
            'east': 'East Portal',
            'west': 'West Avenue'
        }
        
        cameras_data = []
        for direction in self.directions:
            manager = self.camera_managers.get(direction)
            state = self.states.get(direction, {})
            current_source = state.get("current_source", "Simulated")
            
            base_name = name_map.get(direction, direction.title())
            
            if current_source.startswith("Camera") and manager and manager.is_running:
                status = "active"
                # Make it dynamic: show hardware/source name
                display_name = f"{base_name} ({current_source.replace('Camera', 'Cam')})"
            elif current_source != "Simulated" and manager and manager.is_running:
                status = "active"
                # If it's a video file, clip the name or just show 'Video'
                if len(current_source) > 10:
                    src_short = current_source[:7] + "..."
                else:
                    src_short = current_source
                display_name = f"{base_name} ({src_short})"
            else:
                status = "simulated" 
                display_name = f"{base_name} (Sim)"

            cameras_data.append({
                "name": display_name,
                "status": status,
                "id": direction
            })
            
        return cameras_data
    
    def update_sidebar_navigation(self):
        """Update sidebar with proper navigation callback after view is ready"""
        if self.view and hasattr(self.view, 'sidebar'):
            self.view.sidebar.on_nav_click = self.handle_navigation
    
    def handle_navigation(self, page_name):
        """Handle page navigation"""
        try:
            # Add dynamic notification clear logic for issue reports
            if page_name == 'issue_reports':
                try:
                    if self.db:
                        reports = self.db.get_all_reports() or []
                        self.last_viewed_report_count = len(reports)
                    if self.view and hasattr(self.view, 'sidebar'):
                        self.view.sidebar.update_nav_badge('issue_reports', 0)
                except Exception as ex:
                    self.logger.error(f"Error resetting report notification: {ex}")

            if page_name in self.pages:
                if self.current_page:
                    try:
                        self.current_page.get_widget().pack_forget()
                    except:
                        pass
                
                page = self.pages[page_name]
                page.get_widget().pack(fill=tk.BOTH, expand=True)
                self.current_page = page
        except Exception as e:
            print(f"Navigation error: {e}")
    
    def start_camera_feed(self):
        """Start camera feeds in background thread"""
        from utils.app_config import SETTINGS
        # Initialize all cameras based on SETTINGS
        for i, direction in enumerate(self.directions):
            source = SETTINGS.get(f"camera_source_{direction}", "Simulated")
            self.states[direction]["current_source"] = source
            if source.startswith("Camera"):
                try:
                    cam_idx = int(source.split(" ")[1])
                    self.camera_managers[direction].initialize_camera(cam_idx)
                except ValueError:
                    pass
            
        self.camera_thread = threading.Thread(target=self.camera_loop, daemon=True)
        self.camera_thread.start()
        
        self.logger.info("Camera feed started with DQN traffic control")
    
    def camera_loop(self):
        """Background thread for camera processing with DQN decision making"""
        
        self.logger.info("🚀 CAMERA LOOP STARTED!")
        
        # Traffic light state is now fully managed by TrafficLightController.
        # The controller tracks: phase, buffer lock, emergency override, starvation.
        # We only need to push detections into it and read back the active lane/phase.
        
        self.logger.info("Initial: synchronized NS GREEN")
        
        loop_count = 0
        last_status_time = time.time()
        last_report_poll_time = time.time() - 10.0  # Force an immediate poll
        last_phase_update_time = time.time()
        
        while self.is_running:
            current_time = time.time()
            loop_count += 1
            
            # Status update every 5 seconds — read state from the controller, not cycle_state
            if current_time - last_status_time >= 5.0:
                ctrl_status = self.traffic_controller.get_current_status()
                self.logger.info(
                    f"Status Loop #{loop_count} | "
                    f"Phase: {ctrl_status['current_phase'].upper()} | "
                    f"Lane: {self.directions[ctrl_status['current_lane']].upper()} | "
                    f"Remaining: {ctrl_status['phase_remaining']:.1f}s | "
                    f"Buffer: {'LOCKED' if ctrl_status['buffer_locked'] else 'open'} | "
                    f"Emergency: {'YES' if ctrl_status['is_emergency'] else 'no'}"
                )
                
                # Update sidebar active camera status
                if self.view and hasattr(self.view, 'sidebar') and self.view.sidebar:
                    try:
                        active_cams = self.get_active_cameras()
                        self.root.after(0, lambda d=active_cams: self.view.sidebar.update_cameras(d))
                    except Exception as e:
                        print(f"Error updating sidebar: {e}")

                last_status_time = current_time

            # Update issue reports dynamic notification every 10 seconds
            if current_time - last_report_poll_time >= 10.0:
                last_report_poll_time = current_time
                if self.db and self.view and hasattr(self.view, 'sidebar') and self.view.sidebar:
                    try:
                        reports = self.db.get_all_reports() or []
                        unread = len(reports) - getattr(self, 'last_viewed_report_count', 0)
                        self.root.after(0, lambda c=unread: self.view.sidebar.update_nav_badge('issue_reports', c))
                    except Exception as e:
                        pass # Silently handle if database fails or widgets no longer exist

            
            # Step 1: Process all cameras and collect YOLO detections
            all_lane_counts = []
            for direction in self.directions:
                try:
                    state = self.states[direction]
                    lane_id = self.direction_to_lane[direction]
                    
                    # ---------------------------
                    # READ GLOBAL SETTINGS
                    # ---------------------------
                    # We check the dict inside the loop for real-time updates
                    from utils.app_config import SETTINGS
                    
                    enable_detection = SETTINGS.get("enable_detection", True)
                    show_boxes = SETTINGS.get("show_bounding_boxes", True)
                    show_confidence = SETTINGS.get("show_confidence", True)
                    show_sim_text = SETTINGS.get("show_simulation_text", True)
                    dark_mode_cam = SETTINGS.get("dark_mode_cam", False)
                    camera_source = SETTINGS.get(f"camera_source_{direction}", "Simulated")
                    
                    # Check if source changed
                    if camera_source != state.get("current_source", "Simulated"):
                        self.camera_managers[direction].release()
                        if camera_source.startswith("Camera"):
                            try:
                                cam_idx = int(camera_source.split(" ")[1])
                                self.camera_managers[direction].initialize_camera(cam_idx)
                            except ValueError:
                                pass
                        state["current_source"] = camera_source
                    
                    # Get Frame
                    frame = None
                    if camera_source.startswith("Camera"):
                        frame = self.camera_managers[direction].get_frame()
                    
                    if frame is None:
                        # Create blank frame for demo
                        frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        
                        # SIMULATOR: Generate fake traffic only for explicit Simulation.
                        # A real USB/RTSP source with no frame must report no detections
                        # so camera dropouts do not disturb the signal controller.
                        detections = []
                        if camera_source == "Simulated":
                            # DYNAMIC SIMULATION: Smoothly rise and fall over time to test DQN
                            import random
                            
                            # Initialize dynamic simulation parameters for the lane
                            if "sim_count" not in state:
                                state["sim_count"] = random.randint(5, 30)
                                state["sim_trend"] = random.choice([-1, 1])
                                state["last_sim_change"] = time.time()
                                
                            # Change count every 1.5 seconds by a small amount
                            if current_time - state.get("last_sim_change", current_time) > 1.5:
                                state["last_sim_change"] = current_time
                                
                                # Bounce off extremes or randomly change direction 15% of the time
                                if state["sim_count"] >= 45:
                                    state["sim_trend"] = -1
                                elif state["sim_count"] <= 3:
                                    state["sim_trend"] = 1
                                elif random.random() < 0.15:
                                    state["sim_trend"] *= -1
                                        
                                # Apply trend step
                                step = random.randint(1, 4) * state["sim_trend"]
                                state["sim_count"] = max(0, min(50, state["sim_count"] + step))
                                
                            count = int(state["sim_count"])
                            
                            # Create fake detections (Simulator always creates them, but we might not draw them)
                            # Create fake detections (Simulator always creates them, but we might not draw them)
                            for _ in range(count):
                                cx, cy = random.randint(100, 500), random.randint(100, 400)
                                w, h = 60, 40 # Approx car size
                                x1, y1 = cx - w//2, cy - h//2
                                x2, y2 = cx + w//2, cy + h//2
                                
                                # Randomize types? For now mostly cars
                                v_type = random.choice(['car', 'car', 'car', 'truck', 'bus', 'motorcycle'])
                                
                                det = {
                                    'class_name': v_type, 
                                    'confidence': 0.95,
                                    'bbox': [x1, y1, x2, y2],
                                    'center': (cx, cy)
                                }
                                detections.append(det)
                                
                                # Draw if enabled
                                if show_boxes:
                                    color = getattr(self.yolo_detector, 'color_map', {}).get(v_type, (0, 255, 0))
                                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                                    # Simple label
                                    # cv2.putText(frame, v_type, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                            
                            # -------------------------------------------------------------
                            # AI EVENT SIMULATION (Accidents & Violations)
                            # -------------------------------------------------------------
                            # Check settings
                            enable_sim = SETTINGS.get("enable_sim_events", True)
                            
                            if enable_sim:
                                # 1. Simulate ACCIDENT (Random low probability)
                                # We create 2 overlapping boxes to simulate a crash
                                if random.random() < 0.02: # 2% chance per frame
                                    cx, cy = 320, 240
                                    acc_box1 = [cx-50, cy-40, cx+20, cy+30]
                                    acc_box2 = [cx-10, cy-30, cx+55, cy+40]
                                    detections.append({
                                        'class_name': 'car',
                                        'confidence': 0.95,
                                        'bbox': acc_box1,
                                        'center': (cx - 15, cy)
                                    })
                                    detections.append({
                                        'class_name': 'truck',
                                        'confidence': 0.92,
                                        'bbox': acc_box2,
                                        'center': (cx + 22, cy + 5)
                                    })

                                    # Compute collision zone coordinates (always needed for text label)
                                    zone_x1 = min(acc_box1[0], acc_box2[0]) - 8
                                    zone_y1 = min(acc_box1[1], acc_box2[1]) - 8
                                    zone_x2 = max(acc_box1[2], acc_box2[2]) + 8
                                    zone_y2 = max(acc_box1[3], acc_box2[3]) + 8

                                    # Draw accident bounding boxes explicitly on the frame
                                    if show_boxes:
                                        # Vehicle 1 box (red)
                                        cv2.rectangle(frame, (acc_box1[0], acc_box1[1]), (acc_box1[2], acc_box1[3]), (0, 0, 255), 2)
                                        cv2.rectangle(frame, (acc_box1[0], acc_box1[1] - 20), (acc_box1[0] + 70, acc_box1[1]), (0, 0, 255), -1)
                                        cv2.putText(frame, "car 0.95", (acc_box1[0], acc_box1[1] - 5),
                                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                                        # Vehicle 2 box (orange)
                                        cv2.rectangle(frame, (acc_box2[0], acc_box2[1]), (acc_box2[2], acc_box2[3]), (0, 100, 255), 2)
                                        cv2.rectangle(frame, (acc_box2[0], acc_box2[1] - 20), (acc_box2[0] + 80, acc_box2[1]), (0, 100, 255), -1)
                                        cv2.putText(frame, "truck 0.92", (acc_box2[0], acc_box2[1] - 5),
                                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                                        # Collision zone highlight rectangle + connecting line
                                        cv2.rectangle(frame, (zone_x1, zone_y1), (zone_x2, zone_y2), (0, 0, 255), 3)
                                        cv2.line(frame, (cx - 15, cy), (cx + 22, cy + 5), (0, 0, 255), 2)
                                        # Label banner
                                        cv2.rectangle(frame, (zone_x1, zone_y1 - 28), (zone_x1 + 210, zone_y1), (0, 0, 255), -1)
                                        cv2.putText(frame, "ACCIDENT DETECTED!", (zone_x1 + 4, zone_y1 - 8),
                                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                                    # Save Simulate Accident
                                    current_time = time.time()
                                    last_acc = getattr(self, 'last_accident_log', 0)
                                    if hasattr(self, 'accident_controller') and self.accident_controller:
                                        if current_time - last_acc > 10.0:
                                            self.accident_controller.report_accident(
                                                lane=lane_id,
                                                severity="Severe",
                                                description="Simulated Multi-Vehicle Crash",
                                                frame=frame
                                            )
                                            self.last_accident_log = current_time
                                            self.logger.info(f"Simulated Accident recorded for {direction}")
                                            # Notify
                                            self.root.after(0, lambda lid=lane_id: self.notification_manager.show("Crash Detected", f"Accident on {self.lane_names.get(lid, f'Lane {lid}')}", "error"))
                                
                                # 2. Simulate VIOLATION (If Light is RED)
                                # We simulate a car running through the stop line
                                if state['signal_state'] == 'RED' and random.random() < 0.03: # 3% chance when Red
                                    viol_box = [100, 300, 210, 380]
                                    detections.append({
                                        'class_name': 'car',
                                        'confidence': 0.98,
                                        'bbox': viol_box,
                                        'center': (155, 340)
                                    })

                                    # Draw violation bounding box explicitly
                                    if show_boxes:
                                        cv2.rectangle(frame, (viol_box[0], viol_box[1]), (viol_box[2], viol_box[3]), (0, 165, 255), 3)
                                        cv2.rectangle(frame, (viol_box[0], viol_box[1] - 20), (viol_box[0] + 90, viol_box[1]), (0, 165, 255), -1)
                                        cv2.putText(frame, "car 0.98", (viol_box[0], viol_box[1] - 5),
                                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                                    cv2.putText(frame, "RED LIGHT VIOLATION!", (viol_box[0], viol_box[1] - 28),
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

                                    # Save simulated violation
                                    current_time = time.time()
                                    if hasattr(self, 'violation_controller') and self.violation_controller:
                                        last_log = getattr(self, 'last_violation_log', 0)
                                        if current_time - last_log > 5.0:
                                            self.violation_controller.save_violation(lane=lane_id, violation_type="Red Light Violation", frame=frame)
                                            self.session_violations += 1 # Increment Session Counter
                                            self.last_violation_log = current_time
                                            self.logger.info(f"Simulated Violation recorded for {direction}")
                                            # Notify
                                            self.root.after(0, lambda lid=lane_id: self.notification_manager.show("Violation Alert", f"Red Light Violation — {self.lane_names.get(lid, f'Lane {lid}')}", "violation"))

                                # 3. Simulate EMERGENCY VEHICLE
                                # Provide a small chance for an emergency vehicle to show up and trigger priority
                                # -> Currently disabled at user's request
                                enable_sim_emergency = False
                                
                                if enable_sim_emergency:
                                    if "sim_emergency_end" not in state:
                                        state["sim_emergency_end"] = 0
                                        
                                    if current_time < state["sim_emergency_end"]:
                                        # Force emergency vehicle to remain in view
                                        cx, cy = 400, 300
                                        detections.append({
                                            'class_name': 'emergency_vehicle', 
                                            'confidence': 0.99,
                                            'bbox': [cx-30, cy-30, cx+30, cy+30],
                                            'center': (cx, cy)
                                        })
                                        cv2.putText(frame, "🚨 EMERGENCY VEHICLE!", (100, 50), 
                                                  cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 0, 0), 3)
                                                  
                                    elif random.random() < 0.01: # 1% chance per frame (throttle down)
                                        state["sim_emergency_end"] = current_time + 10.0 # Stick around for 10s
                                        self.logger.info(f"Generated SIMULATED Emergency Vehicle in {direction}")

                            # -------------------------------------------------------------
                            
                            if show_sim_text:
                                cv2.putText(frame, f"SIMULATION: {count} vehicles", (50, 240), 
                                          cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        else:
                             if show_sim_text:
                                 cv2.putText(frame, "No Signal - No Traffic", (150, 240), 
                                          cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                        
                        annotated_frame = frame
                    else:
                        # REAL CAMERA
                        detections = []
                        annotated_frame = frame
                        
                        if enable_detection:
                            # ---------------------------
                            # PERFORMANCE OPTIMIZATION
                            # Throttle AI to ~10 FPS (every 0.1s)
                            # ---------------------------
                            current_ai_time = time.time()
                            last_ai_time = state.get('last_ai_time', 0)
                            
                            # Determine if we should run fresh detection
                            # Throttle YOLO inference - gives the UI display loop
                            # more time per cycle so video rendering stays smooth
                            throttle_val = SETTINGS.get("ai_throttle_seconds", 0.125)
                            should_detect = (current_ai_time - last_ai_time) > throttle_val
                            
                            if should_detect:
                                # Run YOLO detection
                                detection_result = self.yolo_detector.detect(frame)
                                detections = detection_result.get("detections", [])
                                annotated_frame = detection_result.get('annotated_frame', frame)
                                
                                # Update cache
                                state['last_ai_time'] = current_ai_time
                                state['cached_detections'] = detections
                            else:
                                # Reuse cached detections but redraw on NEW frame to prevent "ghosting"
                                # This ensures the video background is smooth (30fps) while boxes update at 10fps
                                detections = state.get('cached_detections', [])
                                
                                if show_boxes and detections:
                                    try:
                                        annotated_frame = self.yolo_detector.draw_detections(frame, detections)
                                    except AttributeError:
                                        # Fallback if method missing (shouldn't happen)
                                        annotated_frame = frame
                                else:
                                    annotated_frame = frame
                            
                            if not show_boxes:
                                annotated_frame = frame

                            # -------------------------------------------------------------
                            # REAL AI LOGIC: Violation & Accident Detection
                            # -------------------------------------------------------------
                            if True: # Always process real AI logic for actual camera
                                
                                # 1. Red Light Violation (Real Logic)
                                # Define Stop Line based on user preference
                                h, w, _ = frame.shape
                                
                                # Line position: 80% height, spanning the central parts of the lane
                                line_y = int(h * 0.80)
                                line_x1 = int(w * 0.25)  # 1/4 the way in
                                line_x2 = int(w * 0.75)  # 3/4 the way in
                                
                                is_red = state['signal_state'] == 'RED'
                                is_green = state['signal_state'] == 'GREEN'
                                
                                # Draw the Stop Line
                                if is_red:
                                    color = (0, 0, 255)  # Red
                                    cv2.line(annotated_frame, (line_x1, line_y), (line_x2, line_y), color, 3)
                                    cv2.putText(annotated_frame, "STOP LINE", (line_x1, line_y - 10), 
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                                                
                                    # Check if any car crosses the line while RED
                                    for det in detections:
                                        if det['class_name'] in ['car', 'truck', 'bus', 'motorcycle']:
                                            v_x1, v_y1, v_x2, v_y2 = det['bbox']
                                            
                                            # Check if vehicle box intersects the stop line segment
                                            # It intersects if line_y is between the vehicle's top and bottom,
                                            # AND vehicle's left-right spans across the line's x range
                                            if v_y1 < line_y < v_y2:
                                                if (v_x1 < line_x2) and (v_x2 > line_x1):
                                                    # VIOLATION CONFIRMED
                                                    cv2.putText(annotated_frame, "🚫 RED LIGHT VIOLATION!", (50, 100), 
                                                              cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
                                                    
                                                    # Save violation (Simple Throttle: max 1 per 5 seconds per camera)
                                                    current_time = time.time()
                                                    if hasattr(self, 'violation_controller') and self.violation_controller:
                                                        last_log = getattr(self, 'last_violation_log', 0)
                                                        if current_time - last_log > 5.0:
                                                            self.violation_controller.save_violation(lane=lane_id, violation_type="Red Light Violation", frame=annotated_frame)
                                                            self.session_violations += 1 # Increment Session Counter
                                                            self.last_violation_log = current_time
                                                            self.logger.info(f"Violation recorded for {direction}")
                                                            # Notify
                                                            self.root.after(0, lambda lid=lane_id: self.notification_manager.show("Violation Alert", f"Red Light Violation — {self.lane_names.get(lid, f'Lane {lid}')}", "violation"))
                                                    
                                                    break

                                elif is_green:
                                    color = (0, 255, 0)  # Green
                                    cv2.line(annotated_frame, (line_x1, line_y), (line_x2, line_y), color, 3)
                                    cv2.putText(annotated_frame, "GO", (line_x1, line_y - 10), 
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


                                # ─── 2. Accident Detection (Real Logic) ──────────────────────
                                # YOLO draws TIGHT individual boxes. After a crash they TOUCH
                                # but rarely overlap → IoU ≈ 0. We use a gap-based check:
                                #
                                # Candidate if EITHER condition is true:
                                #  A) Center distance < (half_w1+half_w2)*1.1  (x-axis close)
                                #     AND center distance < (half_h1+half_h2)*1.4  (y-axis close)
                                #     → catches head-on / rear-end / side-impact
                                #  B) Bounding boxes within GAP_PX pixels of each other
                                #     in both x and y → catches touching-but-not-overlapping
                                #
                                # Size-ratio guard avoids tiny artefacts vs big trucks.
                                # 3-frame confirmation eliminates single-frame false positives.
                                # ─────────────────────────────────────────────────────────────
                                CONFIRM_FRAMES = 3   # consecutive frames to confirm accident
                                GAP_PX         = 25  # pixel gap tolerance for touching boxes
                                SIZE_RATIO_MIN = 0.10  # min(area1,area2)/max(area1,area2)

                                vehicle_classes = ['car', 'truck', 'bus', 'motorcycle', 'jeepney']
                                vehicle_dets = [d for d in detections if d['class_name'] in vehicle_classes]

                                accident_candidate = False
                                candidate_d1 = candidate_d2 = None
                                candidate_score = 0.0  # proximity score for label

                                for _i, d1 in enumerate(vehicle_dets):
                                    for _j, d2 in enumerate(vehicle_dets):
                                        if _i >= _j:
                                            continue

                                        x1a, y1a, x2a, y2a = d1['bbox']
                                        x1b, y1b, x2b, y2b = d2['bbox']
                                        w1 = max(1, x2a - x1a)
                                        h1 = max(1, y2a - y1a)
                                        w2 = max(1, x2b - x1b)
                                        h2 = max(1, y2b - y1b)

                                        # Size-ratio guard (filter tiny artefacts)
                                        a1, a2 = w1 * h1, w2 * h2
                                        if min(a1, a2) / max(a1, a2) < SIZE_RATIO_MIN:
                                            continue

                                        cx1 = (x1a + x2a) / 2;  cy1 = (y1a + y2a) / 2
                                        cx2 = (x1b + x2b) / 2;  cy2 = (y1b + y2b) / 2
                                        dx  = abs(cx1 - cx2)
                                        dy  = abs(cy1 - cy2)

                                        # Condition A: center-to-center within combined half-sizes
                                        half_x_sum = (w1 / 2 + w2 / 2) * 1.1
                                        half_y_sum = (h1 / 2 + h2 / 2) * 1.4
                                        cond_a = (dx < half_x_sum) and (dy < half_y_sum)

                                        # Condition B: boxes within GAP_PX pixels of each other
                                        gap_x = max(0, max(x1a, x1b) - min(x2a, x2b))
                                        gap_y = max(0, max(y1a, y1b) - min(y2a, y2b))
                                        cond_b = (gap_x <= GAP_PX) and (gap_y <= GAP_PX)

                                        if not (cond_a or cond_b):
                                            continue  # Neither condition satisfied

                                        # Compute a proximity score: 0.0 = touching, 1.0 = just passing
                                        dist = (dx**2 + dy**2) ** 0.5
                                        avg_half = ((half_x_sum + half_y_sum) / 2) + 1e-6
                                        prox_score = max(0.0, 1.0 - dist / avg_half)

                                        if prox_score > candidate_score:
                                            accident_candidate = True
                                            candidate_d1, candidate_d2 = d1, d2
                                            candidate_score = prox_score
                                        break  # Best pair already found for this d1
                                    if accident_candidate:
                                        break

                                # Multi-frame counter (Stage 4)
                                if accident_candidate:
                                    self._accident_frame_counts[lane_id] = \
                                        self._accident_frame_counts.get(lane_id, 0) + 1
                                else:
                                    self._accident_frame_counts[lane_id] = max(
                                        0, self._accident_frame_counts.get(lane_id, 0) - 1
                                    )

                                frame_count = self._accident_frame_counts.get(lane_id, 0)
                                accident_detected = frame_count >= CONFIRM_FRAMES

                                # ── Visualisation ──────────────────────────────────────────
                                if accident_candidate and candidate_d1 and candidate_d2:
                                    x1a, y1a, x2a, y2a = candidate_d1['bbox']
                                    x1b, y1b, x2b, y2b = candidate_d2['bbox']
                                    zone_x1 = max(0, min(x1a, x1b) - 10)
                                    zone_y1 = max(0, min(y1a, y1b) - 10)
                                    zone_x2 = max(x2a, x2b) + 10
                                    zone_y2 = max(y2a, y2b) + 10

                                    if accident_detected:
                                        box_color  = (0, 0, 255)       # Red — confirmed
                                        label_text = f"ACCIDENT! Score:{candidate_score:.2f}"
                                    else:
                                        box_color  = (0, 165, 255)     # Orange — warming up
                                        label_text = f"Possible Accident ({frame_count}/{CONFIRM_FRAMES})"

                                    cv2.rectangle(annotated_frame,
                                                  (zone_x1, zone_y1), (zone_x2, zone_y2),
                                                  box_color, 3)
                                    c1 = candidate_d1['center']
                                    c2 = candidate_d2['center']
                                    cv2.line(annotated_frame, c1, c2, box_color, 2)
                                    lbl_w = len(label_text) * 11
                                    cv2.rectangle(annotated_frame,
                                                  (zone_x1, max(0, zone_y1 - 28)),
                                                  (zone_x1 + lbl_w, zone_y1),
                                                  box_color, -1)
                                    cv2.putText(annotated_frame, label_text,
                                                (zone_x1 + 4, max(5, zone_y1 - 8)),
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                                (255, 255, 255), 2)
                                # ─────────────────────────────────────────────────────────────

                                accident_desc = (
                                    f"Proximity collision (score:{candidate_score:.2f})"
                                    if accident_detected else ""
                                )

                                if accident_detected:
                                    # Notify and Save (Throttled)
                                    current_time = time.time()
                                    last_acc = getattr(self, 'last_accident_log', 0)
                                    if hasattr(self, 'accident_controller') and self.accident_controller:
                                        if current_time - last_acc > 10.0:
                                            self.accident_controller.report_accident(
                                                lane=lane_id, severity="Severe",
                                                description=accident_desc,
                                                frame=annotated_frame
                                            )
                                            self.last_accident_log = current_time
                                            self.root.after(0, lambda lid=lane_id: self.notification_manager.show(
                                                "Accident Alert",
                                                f"Collision — {self.lane_names.get(lid, f'Lane {lid}')}",
                                                "error"
                                            ))
                            # -------------------------------------------------------------
                        
                    # Apply final filters (Dark Mode)
                    if dark_mode_cam and annotated_frame is not None:
                        annotated_frame = cv2.bitwise_not(annotated_frame)
                    
                    # Store detections
                    state['detections'] = detections
                    state['vehicle_count'] = len([d for d in detections
                                                  if d.get('class_name') not in ['emergency_vehicle']])
                    all_lane_counts.append(state['vehicle_count'])

                    # High-congestion alert (40+ vehicles)
                    if state['vehicle_count'] >= self.CONGESTION_VEHICLE_THRESHOLD:
                        if current_time - self._congestion_last_notify[direction] >= self.CONGESTION_NOTIFY_INTERVAL:
                            self._congestion_last_notify[direction] = current_time
                            lane_name = {'north': 'North Gate', 'south': 'South Junction',
                                         'east': 'East Portal', 'west': 'West Avenue'}.get(direction, direction.title())
                            vc = state['vehicle_count']
                            self.root.after(0, lambda n=lane_name, c=vc: self.notification_manager.show(
                                "High Congestion",
                                f"{n}: {c} vehicles",
                                "warning"
                            ))
                            self.logger.info(f"[Congestion] {direction.upper()} hit {vc} vehicles")
                    else:
                        # Reset timer when congestion clears so next spike notifies immediately
                        self._congestion_last_notify[direction] = 0.0

                    # Throughput tracking (count vehicles that exit the frame)
                    prev_c = self._lane_prev_count[direction]
                    curr_c = state['vehicle_count']
                    if curr_c < prev_c:
                        self._lane_throughput[direction] += (prev_c - curr_c)
                    self._lane_prev_count[direction] = curr_c

                    # Low traffic notification (at most once every 2 minutes per lane)
                    if state['vehicle_count'] < self.LOW_TRAFFIC_THRESHOLD:
                        if current_time - self._low_traffic_last_notify[direction] >= self.LOW_TRAFFIC_NOTIFY_INTERVAL:
                            self._low_traffic_last_notify[direction] = current_time
                            _ln = {'north': 'North Gate', 'south': 'South Junction',
                                   'east': 'East Portal', 'west': 'West Avenue'}.get(direction, direction.title())
                            _vc = state['vehicle_count']
                            self.root.after(0, lambda n=_ln, c=_vc:
                                self.notification_manager.show(
                                    "Low Traffic",
                                    f"{n}: {c} vehicles",
                                    "success"
                                ))

                    # Log vehicle detections (only if count > 0 to avoid spam)
                    if len(detections) > 0:
                        self.logger.info(f"📹 {direction.upper()}: Detected {len(detections)} vehicles")
                    
                    # Push full typed detections into the new TrafficLightController
                    # This enables congestion weighting, emergency detection, and starvation tracking.
                    self.traffic_controller.update_lane_detections(lane_id, detections)

                    # Check for blocking intersection (vehicle beyond stop line while RED)
                    self._check_blocking_intersection(
                        direction, lane_id, detections,
                        annotated_frame, current_time,
                        state['signal_state']
                    )

                    # Check for prohibited stopping (vehicle stationary in intersection zone)
                    self._check_prohibited_stopping(
                        direction, lane_id, detections,
                        annotated_frame, current_time
                    )

                    # Check for wrong-way driving (vehicle moving against lane flow)
                    # self._check_wrong_way_driving(
                    #     direction, lane_id, detections,
                    #     annotated_frame, current_time
                    # )

                    # Cache the latest frame per lane for violation screenshot capture
                    self._lane_frames[lane_id] = (
                        annotated_frame.copy() if annotated_frame is not None else None
                    )
                    
                    # Update dashboard display safely on main thread
                    if self.current_page and hasattr(self.current_page, 'update_camera_feed'):
                        dash_data = {
                            'vehicle_count': state['vehicle_count'],
                            'signal_state': state['signal_state'],
                            'time_remaining': max(0, state['time_remaining'])
                        }
                        
                        # Create a copy of the frame to avoid race conditions
                        frame_copy = annotated_frame.copy() if annotated_frame is not None else None
                        
                        # Schedule UI update on main thread
                        self.root.after(0, lambda f=frame_copy, d=dash_data, dir=direction: 
                            self.current_page.update_camera_feed(f, d, dir) 
                            if self.current_page and hasattr(self.current_page, 'update_camera_feed') else None
                        )
                        
                except Exception as e:
                    self.logger.error(f"Error processing camera ({direction}): {e}", exc_info=True)
                    all_lane_counts.append(0)
            
            
            # NEW: Update Traffic Reports Page (Bar Graph)
            if self.current_page and hasattr(self.current_page, 'update_report'):
                # Collect traffic report data
                report_data = {
                    'lane_data': {d: self.states[d]['vehicle_count'] for d in self.directions},
                    'active_cameras': sum(1 for d in self.directions if self.camera_managers[d].is_running),
                    'violations': self.session_violations
                }
                
                self.root.after(0, lambda d=report_data: 
                    self.current_page.update_report(d) 
                    if self.current_page and hasattr(self.current_page, 'update_report') else None
                )

            # ─────────────────────────────────────────────────────────────────
            # Step 2: DQN Traffic Light State Machine
            # Delegates ALL decisions to TrafficLightController which internally
            # enforces:
            #   • 10-second minimum buffer rule
            #   • Emergency override (separate from DQN policy)
            #   • Congestion-based green time (low/medium/high)
            #   • Starvation fairness protection
            # ─────────────────────────────────────────────────────────────────
            try:
                # Call update_phase() approximately every 1 second
                dt_phase = current_time - last_phase_update_time
                if dt_phase >= 1.0:
                    last_phase_update_time = current_time
                    
                    # Ask the controller to evaluate phase transitions
                    decision = self.traffic_controller.update_phase(
                        all_lane_counts=all_lane_counts
                    )
                    
                    # Sync UI state from the controller
                    ctrl_lane  = self.traffic_controller.active_lane
                    ctrl_phase = self.traffic_controller.current_phase
                    ctrl_remaining = max(
                        0.0,
                        self.traffic_controller.phase_duration -
                        (current_time - self.traffic_controller.phase_start_time)
                    )
                    ctrl_is_emergency = self.traffic_controller.is_emergency_active
                    ctrl_buffer_locked = self.traffic_controller.buffer_locked
                    lane_signal_states = (
                        self.traffic_controller.get_lane_signal_states()
                        if hasattr(self.traffic_controller, 'get_lane_signal_states')
                        else {}
                    )
                    
                    # Map controller's numeric active_lane back to directions
                    for i, direction in enumerate(self.directions):
                        if i == ctrl_lane and ctrl_phase == 'green':
                            self.states[direction]['signal_state'] = 'GREEN'
                            self.states[direction]['time_remaining'] = ctrl_remaining
                        elif i == ctrl_lane and ctrl_phase == 'yellow':
                            self.states[direction]['signal_state'] = 'YELLOW'
                            self.states[direction]['time_remaining'] = ctrl_remaining
                        else:
                            self.states[direction]['signal_state'] = 'RED'
                            # Estimated wait: hops × avg_phase_duration
                            hops = (i - ctrl_lane) % len(self.directions)
                            # Estimate based on congestion-weighted average
                            est_phase = 25 + 5   # 25s avg green + 5s clearance
                            if hops == 0:
                                self.states[direction]['time_remaining'] = ctrl_remaining
                            else:
                                self.states[direction]['time_remaining'] = (
                                    ctrl_remaining + (hops - 1) * est_phase
                                )

                    # Paired NS/EW flow: trust the controller's per-lane map.
                    if lane_signal_states:
                        for i, direction in enumerate(self.directions):
                            lane_signal = lane_signal_states.get(i, 'RED')
                            self.states[direction]['signal_state'] = lane_signal
                            if hasattr(self.traffic_controller, 'get_lane_time_remaining'):
                                self.states[direction]['time_remaining'] = (
                                    self.traffic_controller.get_lane_time_remaining(i)
                                )
                            elif lane_signal in ('GREEN', 'YELLOW'):
                                self.states[direction]['time_remaining'] = ctrl_remaining

                    # Track green light efficiency ticks (once per full-cycle update)
                    for _d in self.directions:
                        self._lane_total_ticks[_d] += 1
                        if self.states[_d].get('signal_state') == 'GREEN':
                            self._lane_green_ticks[_d] += 1

                    # Log meaningful transitions
                    if decision is not None:
                        phase_name = decision.get('phase', 'unknown')
                        if phase_name == 'green':
                            lane_id  = decision.get('lane_id', ctrl_lane)
                            gtime    = decision.get('green_time', 15)
                            mode     = decision.get('mode', '')
                            vcnt     = decision.get('vehicle_count', 0)
                            em_flag  = '🚨 EMERGENCY |' if decision.get('is_emergency') else ''
                            buf_flag = '🔒 Buffer active' if ctrl_buffer_locked else ''
                            self.logger.info(
                                f"🟢 {self.directions[lane_id].upper()} → GREEN {gtime}s "
                                f"| {vcnt} vehicles | {em_flag}{mode} {buf_flag}"
                            )
                        elif phase_name == 'yellow':
                            self.logger.info(
                                f"🟡 {self.directions[ctrl_lane].upper()} → YELLOW"
                            )
                        elif phase_name == 'all_red':
                            self.logger.info("🔴 ALL LANES → RED (clearance)")
                
                # ── Sync time_remaining for ALL lanes from the controller ──────
                # The active green lane decrements display at the real wall-clock
                # rate every loop iteration (0.1s) for smooth continuous countdown.
                # The controller's live remaining acts as an authoritative ceiling:
                # if it's trimmed by more than 2s the display snaps down to match,
                # preventing both drift and abrupt UI jumps from adaptive trims.
                # Red lanes use proper delta-time decrement with a stored timestamp.
                # Initialise per-lane display trackers once
                if not hasattr(self, '_display_remaining'):
                    self._display_remaining = {d: 0.0 for d in self.directions}
                if not hasattr(self, '_display_last_tick'):
                    self._display_last_tick = {d: current_time for d in self.directions}
                if not hasattr(self, '_display_signal_state'):
                    self._display_signal_state = {d: None for d in self.directions}

                for direction in self.directions:
                    st  = self.states[direction]
                    lane_id = self.direction_to_lane[direction]
                    dt_since_last = current_time - self._display_last_tick[direction]
                    self._display_last_tick[direction] = current_time

                    # Read directly from the controller every 0.1 s so snaps
                    # happen instantly and the display never freezes at 0
                    # waiting for the 1-second sync block.
                    try:
                        target_time = max(0.0, self.traffic_controller.get_lane_time_remaining(lane_id))
                        signal_state = self.traffic_controller.get_lane_signal_state(lane_id)
                    except Exception:
                        target_time = max(0.0, float(st.get('time_remaining', 0.0)))
                        signal_state = st.get('signal_state', 'RED')

                    st['signal_state'] = signal_state

                    prev_signal = self._display_signal_state.get(direction)
                    prev_disp = self._display_remaining.get(direction, target_time)
                    new_disp = max(0.0, prev_disp - max(0.0, dt_since_last))

                    if prev_signal != signal_state:
                        new_disp = target_time
                    elif abs(target_time - new_disp) > 1.5:
                        # Snap in EITHER direction: down when controller trims
                        # the green, UP when a RED lane gets a fresh countdown
                        # (e.g. after emergency resumption jumps from 3s → 35s).
                        new_disp = target_time

                    self._display_signal_state[direction] = signal_state
                    self._display_remaining[direction] = new_disp
                    st['time_remaining'] = new_disp
                    st['last_update_time'] = current_time
                    
            except Exception as e:
                self.logger.error(f"Error in DQN traffic light control: {e}", exc_info=True)
            
            # Small delay — 10 FPS UI update rate; controller observes at 1-sec cadence
            time.sleep(0.1)
    
    def _check_blocking_intersection(self, direction: str, lane_id: int,
                                     detections: list, frame, current_time: float,
                                     signal_state: str):
        """
        Track vehicles that are stationary BEYOND the stop line while the
        signal is RED. If they haven't moved for BLOCKING_INTERSECTION_SECONDS,
        auto-capture and log a Blocking Intersection violation.
        """
        if frame is None or signal_state != 'RED':
            # Clear tracker when light is no longer red so stale entries don't carry over
            self._blocking_intersection_tracker[direction].clear()
            return

        h, w = frame.shape[:2]

        # Same stop-line geometry used for drawing
        line_y  = int(h * 0.80)
        line_x1 = int(w * 0.25)
        line_x2 = int(w * 0.75)

        vehicle_classes = {'car', 'truck', 'bus', 'motorcycle', 'jeepney'}
        tracker = self._blocking_intersection_tracker[direction]

        # Vehicles whose centre is ABOVE the stop line (passed into intersection)
        occupied_now: set = set()
        for det in detections:
            if det.get('class_name') not in vehicle_classes:
                continue
            cx, cy = det.get('center', (0, 0))
            # Beyond the line = centre is above line_y AND within its x span
            if cy < line_y and line_x1 <= cx <= line_x2:
                occupied_now.add((cx // 60, cy // 60))

        # Evict cells that are no longer occupied (vehicle moved / left)
        for key in list(tracker.keys()):
            if key not in occupied_now:
                del tracker[key]

        for key in occupied_now:
            if key not in tracker:
                tracker[key] = {"first_seen": current_time, "logged": False}
                continue

            entry = tracker[key]
            if entry["logged"]:
                continue

            duration = current_time - entry["first_seen"]
            if duration >= self.BLOCKING_INTERSECTION_SECONDS:
                entry["logged"] = True
                if hasattr(self, 'violation_controller') and self.violation_controller:
                    self.violation_controller.save_violation(
                        lane=lane_id,
                        violation_type="Blocking Intersection",
                        frame=frame
                    )
                    self.session_violations += 1
                    self.logger.info(
                        f"[BlockingIntersection] Lane {lane_id} ({direction.upper()}) "
                        f"— vehicle beyond stop line for {duration:.0f}s"
                    )
                    self.root.after(0, lambda d=direction, lid=lane_id: (
                        self.notification_manager.show(
                            "Blocking Intersection",
                            f"{d.title()} — Lane {lid}",
                            "violation"
                        )
                    ))

    def _check_prohibited_stopping(self, direction: str, lane_id: int,
                                    detections: list, frame, current_time: float):
        """
        Track vehicles present in the intersection zone. If any vehicle
        occupies the same grid cell continuously for PROHIBITED_STOP_SECONDS,
        auto-capture the frame and log a Prohibited Stopping violation.
        """
        if frame is None:
            return

        h, w = frame.shape[:2]

        # Intersection zone: central area of the frame around the stop line
        zone_x1 = int(w * 0.15)
        zone_x2 = int(w * 0.85)
        zone_y1 = int(h * 0.25)
        zone_y2 = int(h * 0.85)

        vehicle_classes = {'car', 'truck', 'bus', 'motorcycle', 'jeepney'}
        tracker = self._prohibited_stop_tracker[direction]

        # Collect grid cells currently occupied by vehicles in the zone
        occupied_now: set = set()
        for det in detections:
            if det.get('class_name') not in vehicle_classes:
                continue
            cx, cy = det.get('center', (0, 0))
            if zone_x1 <= cx <= zone_x2 and zone_y1 <= cy <= zone_y2:
                # 60-pixel grid so minor jitter doesn't reset the timer
                occupied_now.add((cx // 60, cy // 60))

        # Remove cells no longer occupied (vehicle moved / left)
        for key in list(tracker.keys()):
            if key not in occupied_now:
                del tracker[key]

        # Update or create entries for currently occupied cells
        for key in occupied_now:
            if key not in tracker:
                tracker[key] = {"first_seen": current_time, "logged": False}
                continue

            entry = tracker[key]
            if entry["logged"]:
                continue

            duration = current_time - entry["first_seen"]
            if duration >= self.PROHIBITED_STOP_SECONDS:
                entry["logged"] = True
                if hasattr(self, 'violation_controller') and self.violation_controller:
                    self.violation_controller.save_violation(
                        lane=lane_id,
                        violation_type="Prohibited Stopping",
                        frame=frame
                    )
                    self.session_violations += 1
                    self.logger.info(
                        f"[ProhibitedStop] Lane {lane_id} ({direction.upper()}) "
                        f"— vehicle stationary for {duration:.0f}s"
                    )
                    self.root.after(0, lambda d=direction, lid=lane_id: (
                        self.notification_manager.show(
                            "Prohibited Stopping",
                            f"{d.title()} — Lane {lid}",
                            "violation"
                        )
                    ))

    def _check_wrong_way_driving(self, direction: str, lane_id: int,
                                  detections: list, frame, current_time: float):
        """
        Detect vehicles moving against the expected lane flow direction.
        Each camera has a defined inbound direction; a vehicle consistently
        moving the opposite way for WRONG_WAY_CONFIRM_SECONDS is flagged.

        Expected inbound flow (vehicle approaching intersection):
          north → y increases (moves down in frame)
          south → y decreases (moves up in frame)
          east  → x decreases (moves left in frame)
          west  → x increases (moves right in frame)
        """
        if frame is None:
            return

        # (axis, expected_sign) — sign of delta when vehicle moves correctly
        flow = {'north': ('y', +1), 'south': ('y', -1),
                'east':  ('x', -1), 'west':  ('x', +1)}
        axis, expected_sign = flow[direction]

        vehicle_classes = {'car', 'truck', 'bus', 'motorcycle', 'jeepney'}
        tracker   = self._wrong_way_tracker[direction]
        MATCH_PX  = 120   # max px to associate detection with existing track
        MIN_SAMP  = 8     # minimum samples before direction is trusted
        MIN_MOVE  = 40    # minimum total pixel displacement (filters stationary noise)

        # ── match detections to existing tracks ──────────────────────────────
        unmatched_centroids = []
        matched_ids = set()

        for det in detections:
            if det.get('class_name') not in vehicle_classes:
                continue
            cx, cy = det.get('center', (0, 0))

            best_id, best_dist = None, MATCH_PX
            for tid, trk in tracker.items():
                if tid in matched_ids:
                    continue
                dist = ((cx - trk['cx'])**2 + (cy - trk['cy'])**2) ** 0.5
                if dist < best_dist:
                    best_dist, best_id = dist, tid

            if best_id is not None:
                trk = tracker[best_id]
                delta = (cx - trk['cx']) if axis == 'x' else (cy - trk['cy'])
                trk['delta_sum'] += delta
                trk['samples']   += 1
                trk['cx'], trk['cy'] = cx, cy
                trk['last_seen']  = current_time
                matched_ids.add(best_id)
            else:
                unmatched_centroids.append((cx, cy))

        # ── create tracks for new detections ─────────────────────────────────
        for cx, cy in unmatched_centroids:
            tid = self._wrong_way_next_id[direction]
            self._wrong_way_next_id[direction] += 1
            tracker[tid] = {
                'cx': cx, 'cy': cy,
                'delta_sum': 0.0, 'samples': 0,
                'first_seen': current_time, 'last_seen': current_time,
                'logged': False
            }

        # ── evict stale tracks ────────────────────────────────────────────────
        for tid in [k for k, v in tracker.items() if current_time - v['last_seen'] > 2.0]:
            del tracker[tid]

        # ── evaluate direction for each mature track ──────────────────────────
        for trk in tracker.values():
            if trk['logged'] or trk['samples'] < MIN_SAMP:
                continue
            if abs(trk['delta_sum']) < MIN_MOVE:
                continue

            actual_sign = 1 if trk['delta_sum'] > 0 else -1
            if actual_sign == expected_sign:
                continue  # moving the right way

            duration = current_time - trk['first_seen']
            if duration < self.WRONG_WAY_CONFIRM_SECONDS:
                continue

            trk['logged'] = True
            if hasattr(self, 'violation_controller') and self.violation_controller:
                self.violation_controller.save_violation(
                    lane=lane_id,
                    violation_type="Wrong-way Driving",
                    frame=frame
                )
                self.session_violations += 1
                self.logger.info(
                    f"[WrongWay] Lane {lane_id} ({direction.upper()}) "
                    f"— vehicle moving against traffic flow"
                )
                lane_name = self.lane_names.get(lane_id, f'Lane {lane_id}')
                self.root.after(0, lambda n=lane_name:
                    self.notification_manager.show(
                        "Wrong-way Driving",
                        f"Vehicle going wrong way — {n}",
                        "violation"
                    ))

    def _rule_violation_screenshot(self, lane_id: int, frame):
        """
        Callback invoked by DQNRuleController when a pedestrian violation
        (z_jaywalker) is detected. Saves the frame through the violation
        controller and shows a UI notification.
        """
        try:
            import cv2, os
            # Try to get the cached frame for this lane if none supplied
            if frame is None:
                frame = self._lane_frames.get(lane_id)

            if frame is not None and hasattr(self, 'violation_controller') and self.violation_controller:
                self.violation_controller.save_violation(
                    lane=lane_id,
                    violation_type="Pedestrian Violation (Jaywalker)",
                    frame=frame
                )
                self.session_violations += 1
                direction = self.directions[lane_id] if lane_id < len(self.directions) else str(lane_id)
                self.logger.info(
                    f"[RuleCtrl] Pedestrian violation screenshot saved — "
                    f"Lane {lane_id} ({direction.upper()})"
                )
                self.root.after(0, lambda lid=lane_id: self.notification_manager.show(
                    "Pedestrian Violation",
                    f"Jaywalker — {self.lane_names.get(lid, f'Lane {lid}')}",
                    "violation"
                ))
        except Exception as e:
            self.logger.error(f"[RuleCtrl] Failed to save violation screenshot: {e}")

    def stop_camera(self):
        """Stop camera feed"""
        self.is_running = False
        for cam in self.camera_managers.values():
            cam.release()
        
        # Save DQN model
        try:
            self.traffic_controller.save_model("models/dqn/traffic_model.pth")
            self.logger.info("DQN model saved")
        except Exception as e:
            self.logger.error(f"Failed to save DQN model: {e}")
    
    def logout(self):
        """Handle logout"""
        self.stop_camera()
        if self.on_logout_callback:
            self.on_logout_callback()

