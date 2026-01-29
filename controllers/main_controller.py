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
    ViolationLogsPage, AnalyticsPage, SettingsPage, IssueReportsPage, AdminUsersPage
)

from views.components.notification import NotificationManager

class MainController:
    """Main application controller with 4-way camera and AI integration"""
    
    def __init__(self, root, view, db=None, current_user=None, auth_controller=None, on_logout_callback=None, violation_controller=None):
        self.root = root
        self.view = view
        self.db = db
        self.current_user = current_user
        self.auth_controller = auth_controller
        self.violation_controller = violation_controller
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
        self.yolo_detector = YOLODetector("yolov8n.pt")
        self.traffic_controller = TrafficLightController(
            num_lanes=4,
            model_path=None,  # Will use untrained model initially
            use_pretrained=False
        )
        
        # Traffic States for each direction
        self.states = {}
        for direction in self.directions:
            self.states[direction] = {
                'signal_state': 'RED',
                'time_remaining': 0,
                'last_update_time': time.time(),
                'vehicle_count': 0,
                'detections': [],
                'phase_start_time': time.time()
            }
        
        # North starts green (will be managed by camera_loop state machine)
        self.states['north']['signal_state'] = 'GREEN'
        self.states['north']['time_remaining'] = 30
        
        self.logger.info("Initial traffic state: NORTH → GREEN (30s)")
        
        # Threading
        self.camera_thread = None
        self.is_running = True
        
        self.logger.info("MainController initialized with DQN traffic control")
    
    def initialize_pages(self):
        """Initialize all application pages"""
        if self.view and hasattr(self.view, 'content_area'):
            self.pages['dashboard'] = DashboardPage(self.view.content_area)
            self.pages['issue_reports'] = IssueReportsPage(self.view.content_area, self.db, self.current_user)
            self.pages['traffic_reports'] = TrafficReportsPage(self.view.content_area)
            self.pages['incident_history'] = IncidentHistoryPage(self.view.content_area)
            self.pages['incident_history'] = IncidentHistoryPage(self.view.content_area)
            self.pages['violation_logs'] = ViolationLogsPage(self.view.content_area, self.violation_controller)
            self.pages['analytics'] = AnalyticsPage(self.view.content_area)
            self.pages['settings'] = SettingsPage(self.view.content_area)
            
            # Admin Pages
            if self.current_user and self.current_user.get('role') == 'admin':
                if self.auth_controller:
                    self.pages['admin_users'] = AdminUsersPage(self.view.content_area, self.auth_controller)
    
    def update_sidebar_navigation(self):
        """Update sidebar with proper navigation callback after view is ready"""
        if self.view and hasattr(self.view, 'sidebar'):
            self.view.sidebar.on_nav_click = self.handle_navigation
    
    def handle_navigation(self, page_name):
        """Handle page navigation"""
        try:
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
        # Initialize all cameras
        for i, direction in enumerate(self.directions):
            self.camera_managers[direction].initialize_camera(i)
            
        self.camera_thread = threading.Thread(target=self.camera_loop, daemon=True)
        self.camera_thread.start()
        
        self.logger.info("Camera feed started with DQN traffic control")
    
    def camera_loop(self):
        """Background thread for camera processing with DQN decision making"""
        
        self.logger.info("🚀 CAMERA LOOP STARTED!")
        
        # Simple state machine for traffic lights
        cycle_state = {
            'current_lane': 0,  # 0=north, 1=south, 2=east, 3=west
            'phase': 'green',   # green, yellow, all_red
            'phase_start': time.time(),
            'phase_start': time.time(),
            'phase_duration': 15,  # Start with 15s green (observation period)
            'green_check_done': False, # Flag for observation check
        }
        
        self.logger.info(f"🟢 Initial: {self.directions[0].upper()} → GREEN ({cycle_state['phase_duration']}s) [Observing]")
        
        loop_count = 0
        last_status_time = time.time()
        
        while self.is_running:
            current_time = time.time()
            loop_count += 1
            
            # Status update every 5 seconds
            if current_time - last_status_time >= 5.0:
                elapsed = current_time - cycle_state['phase_start']
                remaining = cycle_state['phase_duration'] - elapsed
                self.logger.info(
                    f"📊 Loop #{loop_count} | Phase: {cycle_state['phase'].upper()} | "
                    f"Lane: {self.directions[cycle_state['current_lane']].upper()} | "
                    f"Remaining: {remaining:.1f}s"
                )
                last_status_time = current_time

            
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
                    
                    # Get Frame
                    frame = self.camera_managers[direction].get_frame()
                    if frame is None:
                        # Create blank frame for demo
                        frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        
                        # SIMULATOR: Generate fake traffic for 3 cameras (North, South, East)
                        detections = []
                        if direction in ['north', 'south', 'east']:
                            # Generate random count using stable random to avoid flickering
                            import random
                            base_count = {'north': 15, 'south': 8, 'east': 12}.get(direction, 0)
                            count = max(0, base_count + random.randint(-2, 2))
                            
                            # Create fake detections (Simulator always creates them, but we might not draw them)
                            for _ in range(count):
                                detections.append({
                                    'class_name': 'car', 
                                    'confidence': 0.95,
                                    'box': [0, 0, 50, 50],
                                    'center': (random.randint(100, 500), random.randint(100, 400))
                                })
                            
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
                                    detections.append({
                                        'class_name': 'accident', 
                                        'confidence': 0.99,
                                        'box': [cx-40, cy-40, cx+20, cy+20],
                                        'center': (cx, cy)
                                    })
                                    detections.append({
                                        'class_name': 'car', 
                                        'confidence': 0.90,
                                        'box': [cx-20, cy-20, cx+40, cy+40],
                                        'center': (cx+10, cy+10)
                                    })
                                    cv2.putText(frame, "⚠️ ACCIDENT DETECTED!", (150, 100), 
                                              cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
                                    # Notify
                                    self.root.after(0, lambda: self.notification_manager.show("Crash Detected", f"Accident simulated on Lane {lane_id}", "error"))
                                
                                # 2. Simulate VIOLATION (If Light is RED)
                                # We simulate a car moving fast through the frame
                                if state['signal_state'] == 'RED' and random.random() < 0.03: # 3% chance when Red
                                    # Force a "detection" that represents a runner
                                    detections.append({
                                        'class_name': 'violation', 
                                        'confidence': 0.98,
                                        'box': [100, 100, 200, 200], # Arbitrary box
                                        'center': (150, 150)
                                    })
                                    cv2.putText(frame, "🚫 RED LIGHT VIOLATION!", (100, 150), 
                                              cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 3)
                                    
                                    # Save simulated violation
                                    current_time = time.time()
                                    if hasattr(self, 'violation_controller') and self.violation_controller:
                                        last_log = getattr(self, 'last_violation_log', 0)
                                        if current_time - last_log > 5.0:
                                            self.violation_controller.save_violation(lane=lane_id, violation_type="Red Light Violation")
                                            self.last_violation_log = current_time
                                            self.logger.info(f"Simulated Violation recorded for {direction}")
                                            # Notify
                                            self.root.after(0, lambda: self.notification_manager.show("Violation Alert", f"Red Light Violation on Lane {lane_id}", "violation"))

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
                            # Run YOLO detection ONCE
                            detection_result = self.yolo_detector.detect(frame)
                            detections = detection_result.get("detections", [])
                            
                            if show_boxes:
                                annotated_frame = detection_result.get('annotated_frame', frame)
                            else:
                                annotated_frame = frame

                            # -------------------------------------------------------------
                            # REAL AI LOGIC: Violation & Accident Detection
                            # -------------------------------------------------------------
                            enable_sim = SETTINGS.get("enable_sim_events", True)
                            
                            if enable_sim: # Using same toggle for "Enable Events" on real cam
                                
                                # 1. Red Light Violation (Real Logic)
                                # Define Intersection Zone (Center of image)
                                h, w, _ = frame.shape
                                # Zone: x1, y1, x2, y2 (Central box)
                                zone_x1, zone_y1 = int(w*0.3), int(h*0.3)
                                zone_x2, zone_y2 = int(w*0.7), int(h*0.7)
                                
                                # Draw zone for debugging/visual
                                if state['signal_state'] == 'RED':
                                    color = (0, 0, 255) # Red Zone
                                    # cv2.rectangle(annotated_frame, (zone_x1, zone_y1), (zone_x2, zone_y2), color, 2)
                                    
                                    # Check if any car is INSIDE this zone while RED
                                    for det in detections:
                                        if det['class_name'] in ['car', 'truck', 'bus', 'motorcycle']:
                                            cx, cy = det['center']
                                            if zone_x1 < cx < zone_x2 and zone_y1 < cy < zone_y2:
                                                # VIOLATION CONFIRMED
                                                cv2.putText(annotated_frame, "🚫 RED LIGHT VIOLATION!", (50, 100), 
                                                          cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
                                                
                                                # Save violation (Simple Throttle: max 1 per 5 seconds per camera)
                                                current_time = time.time()
                                                if hasattr(self, 'violation_controller') and self.violation_controller:
                                                    last_log = getattr(self, 'last_violation_log', 0)
                                                    if current_time - last_log > 5.0:
                                                        self.violation_controller.save_violation(lane=lane_id, violation_type="Red Light Violation")
                                                        self.last_violation_log = current_time
                                                        self.logger.info(f"Violation recorded for {direction}")
                                                        # Notify
                                                        self.root.after(0, lambda: self.notification_manager.show("Violation Alert", f"Red Light Violation on Lane {lane_id}", "violation"))
                                                
                                                break

                                # 2. Accident Detection (Real Logic - Box Overlap)
                                # Simple heuristic: overlapping boxes of high confidence
                                for i, d1 in enumerate(detections):
                                    for j, d2 in enumerate(detections):
                                        if i >= j: continue # Avoid double check
                                        
                                        # Only check vehicles
                                        vehicles = ['car', 'truck', 'bus']
                                        if d1['class_name'] in vehicles and d2['class_name'] in vehicles:
                                            # Box 1
                                            x1a, y1a, x2a, y2a = d1['bbox']
                                            # Box 2
                                            x1b, y1b, x2b, y2b = d2['bbox']
                                            
                                            # IoU / Overlap Check
                                            xi1 = max(x1a, x1b)
                                            yi1 = max(y1a, y1b)
                                            xi2 = min(x2a, x2b)
                                            yi2 = min(y2a, y2b)
                                            
                                            inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)
                                            
                                            if inter_area > 0:
                                                box1_area = (x2a - x1a) * (y2a - y1a)
                                                box2_area = (x2b - x1b) * (y2b - y1b)
                                                union_area = box1_area + box2_area - inter_area
                                                iou = inter_area / union_area
                                                
                                                # If significant overlap (e.g. > 30% IoU), flag as potential accident
                                                if iou > 0.3:
                                                    cv2.putText(annotated_frame, "⚠️ ACCIDENT ALERT!", (50, 150), 
                                                              cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 3)
                                                    # Draw connecting line
                                                    c1 = d1['center']
                                                    c2 = d2['center']
                                                    cv2.line(annotated_frame, c1, c2, (0, 0, 255), 3)
                                                    
                                                    # Notify (Throttled)
                                                    current_time = time.time()
                                                    last_acc = getattr(self, 'last_accident_log', 0)
                                                    if current_time - last_acc > 10.0:
                                                        self.last_accident_log = current_time
                                                        self.root.after(0, lambda: self.notification_manager.show("Accident Alert", f"Collision detected on Lane {lane_id}", "error"))
                            # -------------------------------------------------------------
                        
                    # Apply final filters (Dark Mode)
                    if dark_mode_cam and annotated_frame is not None:
                        annotated_frame = cv2.bitwise_not(annotated_frame)
                    
                    # Store detections
                    state['detections'] = detections
                    state['vehicle_count'] = len(detections)
                    all_lane_counts.append(len(detections))
                    
                    # Log vehicle detections (only if count > 0 to avoid spam)
                    if len(detections) > 0:
                        self.logger.info(f"📹 {direction.upper()}: Detected {len(detections)} vehicles")
                    
                    # Update traffic controller lane stats
                    self.traffic_controller.lane_stats[lane_id]['vehicle_count'] = len(detections)
                    self.traffic_controller.lane_stats[lane_id]['last_detection'] = datetime.now()
                    
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
            
            # Update Analytics Page (if active)
            # We do this once per cycle to keep graph time-aligned
            if self.current_page and hasattr(self.current_page, 'update_analytics'):
                analytics_data = {
                    d: self.states[d]['vehicle_count'] for d in self.directions
                }
                self.root.after(0, lambda d=analytics_data: 
                    self.current_page.update_analytics(d) 
                    if self.current_page and hasattr(self.current_page, 'update_analytics') else None
                )

            # Step 2: Simple traffic light state machine
            try:
                elapsed = current_time - cycle_state['phase_start']
                
                # Dynamic adjustment removed - Using strict High/Low logic instead
                # (Block removed)

                # Check if phase should change
                if elapsed >= cycle_state['phase_duration']:
                    current_lane = cycle_state['current_lane']
                    current_phase = cycle_state['phase']
                    
                    if current_phase == 'green':
                        # Green → Yellow
                        cycle_state['phase'] = 'yellow'
                        cycle_state['phase_start'] = current_time
                        cycle_state['phase_duration'] = 3  # 3 seconds yellow
                        
                        self.logger.info(f"🟡 {self.directions[current_lane].upper()} → YELLOW (3s)")
                        
                        # Update states
                        self.states[self.directions[current_lane]]['signal_state'] = 'YELLOW'
                        self.states[self.directions[current_lane]]['time_remaining'] = 3
                        
                    elif current_phase == 'yellow':
                        # Yellow → All Red
                        cycle_state['phase'] = 'all_red'
                        cycle_state['phase_start'] = current_time
                        cycle_state['phase_duration'] = 2  # 2 seconds all red
                        
                        self.logger.info(f"🔴 ALL LANES → RED (clearance 2s)")
                        
                        # All lanes red
                        for direction in self.directions:
                            self.states[direction]['signal_state'] = 'RED'
                            self.states[direction]['time_remaining'] = 2
                            
                    elif current_phase == 'all_red':
                        # All Red → Pick next lane (Strict Sequential Round Robin)
                        next_lane = (current_lane + 1) % 4
                        
                        # Determine Duration based on Congestion (Simulate DQN High/Low decision)
                        # Threshold: 20 vehicles considered "High Congestion"
                        # High Congestion = 60s
                        # Low Congestion = 30s
                        # Observation: We check congestion NOW to decide duration. 
                        # This models the "check 15s window" by effectively using the accumulated count.
                        
                        vehicle_count = all_lane_counts[next_lane]
                        
                        # RULE-BASED LOGIC (User Override)
                        # High congestion (>20): 40s (30 + 10)
                        # Low congestion (<=5): 15s
                        # Normal: 30s
                        
                        if vehicle_count > 20:
                            green_time = 40
                            mode_info = "HIGH CONGESTION - EXTENDED"
                        elif vehicle_count <= 5:
                            green_time = 15
                            mode_info = "LOW CONGESTION - REDUCED"
                        else:
                            green_time = 30
                            mode_info = "NORMAL FLOW"
                        
                        # Update cycle state
                        cycle_state['current_lane'] = next_lane
                        cycle_state['phase'] = 'green'
                        cycle_state['phase_start'] = current_time
                        cycle_state['phase_duration'] = green_time
                        
                        self.logger.info(
                            f"🟢 Logic Decision: {self.directions[next_lane].upper()} → GREEN ({green_time}s) "
                            f"[{vehicle_count} vehicles | {mode_info}]"
                        )
                        
                        
                        # Update all lane states with CASCADED countdowns
                        for i, direction in enumerate(self.directions):
                            if i == next_lane:
                                self.states[direction]['signal_state'] = 'GREEN'
                                self.states[direction]['time_remaining'] = green_time
                            else:
                                self.states[direction]['signal_state'] = 'RED'
                                # Calculate estimated wait time
                                # Hops: How many phases until this lane?
                                hops = (i - next_lane) % len(self.directions)
                                # Wait = Current Green + (Hops-1)*(Future_Est_Green + Clearance) + Current_Clearance
                                # Assume future phases are 30s + 5s clearance
                                estimated_wait = green_time + 5 + ((hops - 1) * 35)
                                self.states[direction]['time_remaining'] = estimated_wait
                
                # Update time remaining for all lanes
                for direction in self.directions:
                    state = self.states[direction]
                    dt = current_time - state['last_update_time']
                    state['last_update_time'] = current_time
                    state['time_remaining'] = max(0, state['time_remaining'] - dt)
                    
            except Exception as e:
                self.logger.error(f"Error in traffic light control: {e}", exc_info=True)
            
            # Small delay
            time.sleep(0.1)  # 10 FPS update rate
    
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
