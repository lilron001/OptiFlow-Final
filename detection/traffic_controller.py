# detection/traffic_controller.py
"""
Intelligent Traffic Light Controller - YOLO + DQN

Implements an NS/EW paired phase cycle:
GREEN -> YELLOW -> ALL_RED -> opposite GREEN.

During normal GREEN, the active parallel pair runs together:
North/South or East/West. The opposite pair stays RED.

Emergency priority is an overlay. It pauses the normal synchronized cycle,
warns the current green movement with YELLOW, gives the detected emergency
lane GREEN by itself, then resumes the saved NS/EW countdown.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

import cv2
import numpy as np

from .yolo_detector import YOLODetector
from .deep_q_learning import (
    TrafficLightDQN,
    TrafficStateBuilder,
    NUM_LANES,
    MIN_BUFFER_TIME,
    NORMAL_MIN_GREEN,
    MAX_GREEN_NORMAL,
    YELLOW_TIME,
    ALL_RED_TIME,
)
from .dqn_rule_controller import DQNRuleController


LANE_LABELS = ["NORTH", "SOUTH", "EAST", "WEST"]
PHASE_NS = "NS"
PHASE_EW = "EW"
PHASE_MAIN_LANES = {
    PHASE_NS: [0, 1],
    PHASE_EW: [2, 3],
}
MAX_RED_DISPLAY_SECONDS = 199.0
EMERGENCY_ATTEMPTS = 2
EMERGENCY_ATTEMPT_SECONDS = 10.0
EMERGENCY_PRIORITY_SECONDS = EMERGENCY_ATTEMPTS * EMERGENCY_ATTEMPT_SECONDS
EMERGENCY_OBSERVATION_SECONDS = 2.0
EMERGENCY_CLEAR_WARNING_SECONDS = 5.0


class TrafficLightController:
    """Traffic light controller with paired NS/EW flow and emergency override."""

    def __init__(
        self,
        num_lanes: int = NUM_LANES,
        model_path: Optional[str] = None,
        use_pretrained: bool = True,
    ):
        self.logger = logging.getLogger(__name__)
        self.num_lanes = num_lanes

        self.yolo = YOLODetector()
        self.dqn = TrafficLightDQN(state_size=22, action_size=5, hidden_size=256)
        if use_pretrained and model_path:
            try:
                self.dqn.load_model(model_path)
                self.logger.info(f"[Controller] Loaded DQN model: {model_path}")
            except Exception as e:
                self.logger.warning(f"[Controller] Could not load model ({e}). Fresh network.")

        self.rule_controller = DQNRuleController(
            dqn=self.dqn,
            num_lanes=num_lanes,
            screenshot_callback=None,
        )
        self.last_rule_audit: dict = {}

        self.active_phase = PHASE_NS
        self.active_lane = 0
        self.active_direction = self.active_phase
        self.active_main_lanes = list(PHASE_MAIN_LANES[self.active_phase])
        self.secondary_lane = None
        self.secondary_state = "OFF"
        self.current_phase = "green"
        self.phase_start_time = time.time()
        self.phase_duration = float(NORMAL_MIN_GREEN)
        self.elapsed_green = 0.0
        self.last_obs_elapsed = 0.0
        self.buffer_locked = True
        self._phase_recalibrated = False

        self.is_emergency_active = False
        self.emergency_lane = None
        self.pending_emergency_lane = None
        self.emergency_exhausted_lanes = set()
        self.paused_normal_state: Optional[Dict] = None

        self.lane_stats: Dict[int, Dict] = {
            i: {
                "vehicle_count": 0,
                "weighted_count": 0.0,
                "wait_time": 0.0,
                "throughput": 0,
                "last_detection": None,
                "detections": [],
                "emergency_flag": False,
                "emergency_first_seen": None,
                "accident_flag": False,
                "congestion_pressure": 0.0,
                "congestion_level": "low",
            }
            for i in range(num_lanes)
        }
        self.secondary_lane = None

        self.decisions_made = 0
        self.total_vehicles_processed = 0
        self.lanes_served_this_cycle: List[int] = list(self.active_main_lanes)
        self.logger.info("[Controller] Initialized synchronized NS/EW paired traffic flow")

    @staticmethod
    def _lane_label(lane_idx: int) -> str:
        return (LANE_LABELS + [str(lane_idx)])[lane_idx if lane_idx < 4 else 4]

    @staticmethod
    def _phase_for_lane(lane_idx: int) -> str:
        return PHASE_NS if lane_idx in PHASE_MAIN_LANES[PHASE_NS] else PHASE_EW

    @staticmethod
    def _opposite_phase(phase: str) -> str:
        return PHASE_EW if phase == PHASE_NS else PHASE_NS

    def _phase_elapsed(self) -> float:
        return max(0.0, time.time() - self.phase_start_time)

    def _phase_green_duration(self, phase: str) -> float:
        lanes = PHASE_MAIN_LANES[phase]
        weighted_count = max(self.lane_stats[lane].get("weighted_count", 0.0) for lane in lanes)
        has_accident = any(self.lane_stats[lane].get("accident_flag", False) for lane in lanes)
        calculated = TrafficStateBuilder.calculate_green_time(weighted_count, has_accident, False)
        return float(max(NORMAL_MIN_GREEN, min(calculated, MAX_GREEN_NORMAL)))

    def _detected_emergency_lane(self, current_time: Optional[float] = None) -> Optional[int]:
        """Return the confirmed emergency lane that was detected earliest."""
        if current_time is None:
            current_time = time.time()

        candidates = []
        for lane in range(self.num_lanes):
            first_seen = self.lane_stats[lane].get("emergency_first_seen")
            if (
                self.lane_stats[lane].get("emergency_flag", False)
                and first_seen is not None
                and current_time - first_seen >= EMERGENCY_OBSERVATION_SECONDS
                and lane not in self.emergency_exhausted_lanes
            ):
                candidates.append((first_seen, lane))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _pause_normal_phase(self, current_time: float) -> None:
        """Save the current synchronized phase so emergency priority can resume it."""
        if self.paused_normal_state is not None or self.is_emergency_active:
            return

        elapsed = max(0.0, current_time - self.phase_start_time)
        remaining = max(1.0, self.phase_duration - elapsed)
        self.paused_normal_state = {
            "active_phase": self.active_phase,
            "active_lane": self.active_lane,
            "active_main_lanes": list(self.active_main_lanes),
            "current_phase": self.current_phase,
            "phase_remaining": remaining,
            "buffer_locked": self.buffer_locked,
            "lanes_served_this_cycle": list(self.lanes_served_this_cycle),
        }

    def _resume_paused_normal_phase(self, current_time: float) -> Optional[Dict]:
        """Restore the paused NS/EW phase and continue its remaining countdown."""
        if self.paused_normal_state is None:
            return None

        paused = self.paused_normal_state
        self.paused_normal_state = None
        self.is_emergency_active = False
        self.emergency_lane = None
        self.pending_emergency_lane = None

        self.active_phase = paused["active_phase"]
        self.active_direction = self.active_phase
        self.active_lane = paused["active_lane"]
        self.active_main_lanes = list(paused["active_main_lanes"])
        self.current_phase = paused["current_phase"]
        self.phase_start_time = current_time
        self.phase_duration = float(paused["phase_remaining"])
        self.elapsed_green = 0.0
        self.buffer_locked = bool(paused["buffer_locked"])
        self.secondary_lane = None
        self.secondary_state = "OFF"
        self.lanes_served_this_cycle = list(paused["lanes_served_this_cycle"])
        # Do not expand the restored countdown; continue exactly where it paused.
        self._phase_recalibrated = True

        return {
            "lane_id": self.active_lane,
            "main_lanes": list(self.active_main_lanes),
            "secondary_lane": None,
            "active_direction": self.active_phase,
            "lane_signal_states": self.get_lane_signal_states(),
            "phase": self.current_phase,
            "duration": self.phase_duration,
            "is_emergency": False,
            "mode": "resume paused synchronized flow",
            "timestamp": datetime.now().isoformat(),
        }

    def _finish_unpaused_emergency(self, current_time: float) -> Dict:
        """Safely leave an emergency that started while no normal phase was paused."""
        self.is_emergency_active = False
        self.emergency_lane = None
        self.pending_emergency_lane = None
        self.current_phase = "yellow"
        self.phase_start_time = current_time
        self.phase_duration = float(YELLOW_TIME)
        self.buffer_locked = False
        return {
            "lane_id": self.active_lane,
            "main_lanes": list(self.active_main_lanes),
            "secondary_lane": None,
            "active_direction": self.active_phase,
            "lane_signal_states": self.get_lane_signal_states(),
            "phase": "yellow",
            "duration": self.phase_duration,
            "is_emergency": False,
            "mode": "emergency complete",
            "timestamp": datetime.now().isoformat(),
        }

    def _start_emergency_clear_warning(self, current_time: float, timed_out: bool = False) -> Dict:
        """Show a 5-second yellow warning on the emergency lane before resuming."""
        lane = self.emergency_lane if self.emergency_lane is not None else self.active_lane
        if timed_out and lane is not None:
            self.emergency_exhausted_lanes.add(lane)

        self.active_lane = lane
        self.active_main_lanes = [lane]
        self.active_phase = self._phase_for_lane(lane)
        self.active_direction = self.active_phase
        self.is_emergency_active = False
        self.emergency_lane = lane
        self.pending_emergency_lane = None
        self.current_phase = "emergency_clear_warning"
        self.phase_start_time = current_time
        self.phase_duration = EMERGENCY_CLEAR_WARNING_SECONDS
        self.buffer_locked = False
        return {
            "lane_id": self.active_lane,
            "main_lanes": list(self.active_main_lanes),
            "secondary_lane": None,
            "active_direction": self.active_phase,
            "lane_signal_states": self.get_lane_signal_states(),
            "phase": "emergency_clear_warning",
            "duration": self.phase_duration,
            "is_emergency": False,
            "mode": "emergency clear warning",
            "timestamp": datetime.now().isoformat(),
        }

    def _commit_green_phase(
        self,
        phase: str,
        current_time: float,
        is_emergency: bool = False,
        emergency_lane: Optional[int] = None,
        green_time: Optional[float] = None,
    ):
        self.active_phase = phase
        self.active_direction = phase
        self.is_emergency_active = is_emergency
        self.emergency_lane = emergency_lane if is_emergency else None

        if is_emergency and emergency_lane is not None:
            self.active_lane = emergency_lane
            self.active_main_lanes = [emergency_lane]
            self.secondary_lane = None
            self.secondary_state = "OFF"
            duration = float(green_time if green_time is not None else EMERGENCY_PRIORITY_SECONDS)
        else:
            self.active_lane = PHASE_MAIN_LANES[phase][0]
            self.active_main_lanes = list(PHASE_MAIN_LANES[phase])
            self.secondary_lane = None
            self.secondary_state = "OFF"
            duration = float(green_time if green_time is not None else self._phase_green_duration(phase))

        self.current_phase = "green"
        self.phase_start_time = current_time
        self.phase_duration = duration
        self.elapsed_green = 0.0
        self.last_obs_elapsed = 0.0
        self.buffer_locked = True
        self._phase_recalibrated = False

    def _commit_emergency_phase(self, lane_id: int, current_time: float) -> None:
        """Give the emergency lane two 10-second priority attempts, alone."""
        if hasattr(self.rule_controller, "release_emergency_lock"):
            self.rule_controller.release_emergency_lock(current_time)
        self.pending_emergency_lane = None
        self._commit_green_phase(
            self._phase_for_lane(lane_id),
            current_time,
            True,
            lane_id,
            EMERGENCY_PRIORITY_SECONDS,
        )

    def _start_emergency_warning(self, lane_id: int, current_time: float) -> None:
        """Warn the current green movement before switching to emergency green."""
        if hasattr(self.rule_controller, "release_emergency_lock"):
            self.rule_controller.release_emergency_lock(current_time)
        self._pause_normal_phase(current_time)
        self.pending_emergency_lane = lane_id
        self.is_emergency_active = False
        self.emergency_lane = None
        self.current_phase = "emergency_warning"
        self.phase_start_time = current_time
        self.phase_duration = float(YELLOW_TIME)
        self.buffer_locked = False

    def set_screenshot_callback(self, callback):
        self.rule_controller.screenshot_callback = callback

    def update_lane_detections(self, lane_id: int, detections: List[Dict]):
        stats = self.lane_stats[lane_id]
        stats["detections"] = detections
        stats["vehicle_count"] = len([
            d for d in detections
            if d.get("class_name") != "emergency_vehicle"
        ])
        stats["weighted_count"] = TrafficStateBuilder.compute_weighted_count(detections)
        has_emergency = any(d.get("class_name") == "emergency_vehicle" for d in detections)
        stats["emergency_flag"] = has_emergency
        if has_emergency:
            if stats.get("emergency_first_seen") is None:
                stats["emergency_first_seen"] = time.time()
        else:
            stats["emergency_first_seen"] = None
            self.emergency_exhausted_lanes.discard(lane_id)
        stats["accident_flag"] = any(d.get("class_name") == "z_accident" for d in detections)
        stats["last_detection"] = datetime.now()

        all_w = [
            TrafficStateBuilder.compute_weighted_count(self.lane_stats[i].get("detections", []))
            for i in range(self.num_lanes)
        ]
        pressure = TrafficStateBuilder.relative_pressure(stats["weighted_count"], all_w)
        stats["congestion_pressure"] = pressure
        stats["congestion_level"] = TrafficStateBuilder.congestion_label(pressure)

        if self.get_lane_signal_state(lane_id) == "GREEN":
            stats["wait_time"] = 0.0
        else:
            stats["wait_time"] += 1.0

    def process_camera_frame(self, frame: np.ndarray, lane_id: int) -> Dict:
        detections = self.yolo.detect_vehicles(frame)
        self.update_lane_detections(lane_id, detections)
        return {
            "lane_id": lane_id,
            "detections": detections,
            "stats": dict(self.lane_stats[lane_id]),
            "timestamp": datetime.now().isoformat(),
        }

    def get_lane_signal_state(self, lane_id: int, elapsed: Optional[float] = None) -> str:
        if elapsed is None:
            elapsed = self._phase_elapsed()

        if self.current_phase == "all_red":
            return "RED"

        if self.is_emergency_active:
            if lane_id != self.emergency_lane:
                return "RED"
            return "GREEN" if self.current_phase == "green" else "YELLOW"

        if self.current_phase == "emergency_warning":
            if lane_id == self.pending_emergency_lane and lane_id in self.active_main_lanes:
                return "GREEN"
            return "YELLOW" if lane_id in self.active_main_lanes else "RED"

        if self.current_phase == "emergency_clear_warning":
            return "YELLOW" if lane_id in self.active_main_lanes else "RED"

        if self.current_phase == "yellow":
            return "YELLOW" if lane_id in self.active_main_lanes else "RED"

        return "GREEN" if lane_id in self.active_main_lanes else "RED"

    def get_lane_signal_states(self) -> Dict[int, str]:
        elapsed = self._phase_elapsed()
        return {lane: self.get_lane_signal_state(lane, elapsed) for lane in range(self.num_lanes)}

    def get_traffic_light_states(self) -> Dict[int, str]:
        return self.get_lane_signal_states()

    def get_lane_time_remaining(self, lane_id: int) -> float:
        elapsed = self._phase_elapsed()
        phase_remaining = max(0.0, self.phase_duration - elapsed)
        signal = self.get_lane_signal_state(lane_id, elapsed)

        if signal in ("GREEN", "YELLOW"):
            return phase_remaining

        if self.current_phase == "green":
            wait = phase_remaining + float(YELLOW_TIME + ALL_RED_TIME)
        elif self.current_phase in ("emergency_warning", "emergency_clear_warning"):
            wait = phase_remaining
        elif self.current_phase == "yellow":
            wait = phase_remaining + float(ALL_RED_TIME)
        elif self.current_phase == "all_red":
            wait = phase_remaining
        else:
            wait = phase_remaining

        lane_phase = self._phase_for_lane(lane_id)
        if not self.is_emergency_active and lane_phase != self._opposite_phase(self.active_phase):
            wait += self._phase_green_duration(self._opposite_phase(self.active_phase))
            wait += float(YELLOW_TIME + ALL_RED_TIME)
        return min(MAX_RED_DISPLAY_SECONDS, max(0.0, wait))

    def make_decision(self, all_lane_counts: List[int], current_time: Optional[float] = None) -> Dict:
        if current_time is None:
            current_time = time.time()

        emergency_lane = self._detected_emergency_lane(current_time)
        if emergency_lane is not None:
            green_time = float(EMERGENCY_PRIORITY_SECONDS)
            self._commit_emergency_phase(emergency_lane, current_time)
            self.decisions_made += 1
            self.lanes_served_this_cycle = list(self.active_main_lanes)
            return {
                "decision_id": self.decisions_made,
                "lane_id": self.active_lane,
                "main_lanes": list(self.active_main_lanes),
                "secondary_lane": None,
                "active_direction": self.active_phase,
                "lane_signal_states": self.get_lane_signal_states(),
                "phase": "green",
                "green_time": green_time,
                "yellow_time": self.dqn.yellow_time,
                "all_red_time": self.dqn.all_red_time,
                "total_cycle_time": green_time + self.dqn.yellow_time + self.dqn.all_red_time,
                "vehicle_count": all_lane_counts[emergency_lane] if emergency_lane < len(all_lane_counts) else 0,
                "all_lane_counts": all_lane_counts,
                "is_emergency": True,
                "mode": "EMERGENCY: two 10-second priority attempts",
                "timestamp": datetime.now().isoformat(),
            }

        lane_detections = [self.lane_stats[i]["detections"] for i in range(self.num_lanes)]
        wait_times = [self.lane_stats[i]["wait_time"] for i in range(self.num_lanes)]
        rule_action, audit = self.rule_controller.step(
            lane_detections=lane_detections,
            wait_times=wait_times,
            active_lane=self.active_lane,
            elapsed_green=self.elapsed_green,
            buffer_locked=self.buffer_locked,
            is_green_phase=False,
        )
        self.last_rule_audit = audit

        rule_label = audit.get("rule_fired", "dqn")
        is_emergency = rule_action is not None and rule_action != 4 and "emergency" in rule_label

        if is_emergency:
            next_lane = int(rule_action)
            if next_lane in self.emergency_exhausted_lanes:
                if hasattr(self.rule_controller, "release_emergency_lock"):
                    self.rule_controller.release_emergency_lock(current_time)
                is_emergency = False
            else:
                green_time = float(EMERGENCY_PRIORITY_SECONDS)
                self._commit_emergency_phase(next_lane, current_time)
                mode_info = f"EMERGENCY:{rule_label}"
                lane_count = all_lane_counts[next_lane] if next_lane < len(all_lane_counts) else 0

        if not is_emergency:
            next_phase = self._opposite_phase(self.active_phase)
            green_time = self._phase_green_duration(next_phase)
            self._commit_green_phase(next_phase, current_time, False, None, green_time)
            mode_info = "NS/EW alternating phase"
            lane_count = sum(
                all_lane_counts[lane] if lane < len(all_lane_counts) else 0
                for lane in self.active_main_lanes
            )

        self.decisions_made += 1
        self.lanes_served_this_cycle = list(self.active_main_lanes)

        self.logger.info(
            f"Decision #{self.decisions_made}: "
            f"{self.active_phase} ({', '.join(self._lane_label(l) for l in self.active_main_lanes)}) "
            f"GREEN {green_time:.0f}s | {lane_count} veh | {mode_info}"
        )

        return {
            "decision_id": self.decisions_made,
            "lane_id": self.active_lane,
            "main_lanes": list(self.active_main_lanes),
            "secondary_lane": self.secondary_lane,
            "active_direction": self.active_phase,
            "lane_signal_states": self.get_lane_signal_states(),
            "phase": "green",
            "green_time": green_time,
            "yellow_time": self.dqn.yellow_time,
            "all_red_time": self.dqn.all_red_time,
            "total_cycle_time": green_time + self.dqn.yellow_time + self.dqn.all_red_time,
            "vehicle_count": lane_count,
            "all_lane_counts": all_lane_counts,
            "is_emergency": is_emergency,
            "mode": mode_info,
            "timestamp": datetime.now().isoformat(),
        }

    def update_phase(self, all_lane_counts: Optional[List[int]] = None) -> Optional[Dict]:
        current_time = time.time()
        elapsed = current_time - self.phase_start_time
        self.elapsed_green = elapsed
        self.buffer_locked = self.current_phase == "green" and elapsed < float(MIN_BUFFER_TIME)
        self.secondary_state = "OFF"

        # ── Safety fallback: if any phase is stuck well past its intended
        # duration, force a clean recovery to the next normal green phase.
        _SAFETY_OVERAGE = 15.0
        if elapsed > self.phase_duration + _SAFETY_OVERAGE:
            self.logger.warning(
                f"[Controller] Phase '{self.current_phase}' stuck "
                f"({elapsed:.1f}s / limit {self.phase_duration:.1f}s) — forcing recovery"
            )
            self.is_emergency_active = False
            self.pending_emergency_lane = None
            self.paused_normal_state = None
            if hasattr(self.rule_controller, "release_emergency_lock"):
                self.rule_controller.release_emergency_lock(current_time)
            next_phase = self._opposite_phase(self.active_phase)
            self._commit_green_phase(next_phase, current_time)
            return {
                "lane_id": self.active_lane,
                "main_lanes": list(self.active_main_lanes),
                "secondary_lane": None,
                "active_direction": self.active_phase,
                "lane_signal_states": self.get_lane_signal_states(),
                "phase": "green",
                "mode": "safety_recovery",
                "timestamp": datetime.now().isoformat(),
            }

        if self.current_phase == "green":
            if self.is_emergency_active:
                emergency_visible = (
                    self.emergency_lane is not None
                    and self.lane_stats[self.emergency_lane].get("emergency_flag", False)
                )
                if emergency_visible and elapsed < EMERGENCY_PRIORITY_SECONDS:
                    return None
                return self._start_emergency_clear_warning(
                    current_time,
                    timed_out=bool(emergency_visible),
                )

            emergency_lane = self._detected_emergency_lane(current_time)
            if not self.is_emergency_active and emergency_lane is not None:
                self._start_emergency_warning(emergency_lane, current_time)
                return {
                    "lane_id": self.active_lane,
                    "main_lanes": list(self.active_main_lanes),
                    "secondary_lane": None,
                    "active_direction": self.active_phase,
                    "lane_signal_states": self.get_lane_signal_states(),
                    "phase": "emergency_warning",
                    "duration": self.phase_duration,
                    "pending_emergency_lane": emergency_lane,
                    "is_emergency": False,
                    "timestamp": datetime.now().isoformat(),
                }

            try:
                lane_detections = [self.lane_stats[i].get("detections", []) for i in range(self.num_lanes)]
                wait_times = [self.lane_stats[i].get("wait_time", 0.0) for i in range(self.num_lanes)]
                rule_action, audit = self.rule_controller.step(
                    lane_detections=lane_detections,
                    wait_times=wait_times,
                    active_lane=self.active_lane,
                    elapsed_green=elapsed,
                    buffer_locked=self.buffer_locked,
                    is_green_phase=True,
                )
                self.last_rule_audit = audit
            except Exception as _rule_err:
                self.logger.error(f"[Controller] rule_controller.step error: {_rule_err}")
                rule_action = 4
                audit = {"rule_fired": "error_fallback"}

            if (
                not self.is_emergency_active
                and rule_action is not None
                and rule_action != 4
                and "emergency" in audit.get("rule_fired", "")
            ):
                if int(rule_action) in self.emergency_exhausted_lanes:
                    if hasattr(self.rule_controller, "release_emergency_lock"):
                        self.rule_controller.release_emergency_lock(current_time)
                # Fall through to natural phase expiry — no early return.

            if not self.is_emergency_active and not self.buffer_locked:
                self._phase_recalibrated = True

        if elapsed < self.phase_duration:
            return None

        if self.current_phase == "green":
            if self.is_emergency_active and self.emergency_lane is not None:
                self.emergency_exhausted_lanes.add(self.emergency_lane)
                self.is_emergency_active = False
                self.emergency_lane = None
            self.current_phase = "yellow"
            self.phase_start_time = current_time
            self.phase_duration = float(YELLOW_TIME)
            self.buffer_locked = False
            return {
                "lane_id": self.active_lane,
                "main_lanes": list(self.active_main_lanes),
                "secondary_lane": None,
                "active_direction": self.active_phase,
                "lane_signal_states": self.get_lane_signal_states(),
                "phase": "yellow",
                "duration": self.phase_duration,
                "timestamp": datetime.now().isoformat(),
            }

        if self.current_phase == "emergency_warning":
            emergency_lane = self.pending_emergency_lane
            if emergency_lane is None or emergency_lane in self.emergency_exhausted_lanes:
                self.current_phase = "all_red"
                self.phase_start_time = current_time
                self.phase_duration = float(ALL_RED_TIME)
                self.pending_emergency_lane = None
                return {
                    "lane_id": self.active_lane,
                    "main_lanes": list(self.active_main_lanes),
                    "secondary_lane": None,
                    "active_direction": self.active_phase,
                    "lane_signal_states": self.get_lane_signal_states(),
                    "phase": "all_red",
                    "duration": self.phase_duration,
                    "timestamp": datetime.now().isoformat(),
                }

            self._commit_emergency_phase(emergency_lane, current_time)
            return {
                "lane_id": self.active_lane,
                "main_lanes": list(self.active_main_lanes),
                "secondary_lane": None,
                "active_direction": self.active_phase,
                "lane_signal_states": self.get_lane_signal_states(),
                "phase": "green",
                "green_time": self.phase_duration,
                "is_emergency": True,
                "timestamp": datetime.now().isoformat(),
            }

        if self.current_phase == "emergency_clear_warning":
            resumed = self._resume_paused_normal_phase(current_time)
            if resumed is not None:
                return resumed
            return self._finish_unpaused_emergency(current_time)

        if self.current_phase == "yellow":
            self.current_phase = "all_red"
            self.phase_start_time = current_time
            self.phase_duration = float(ALL_RED_TIME)
            self.secondary_lane = None
            self.secondary_state = "OFF"
            return {
                "lane_id": self.active_lane,
                "main_lanes": list(self.active_main_lanes),
                "secondary_lane": None,
                "active_direction": self.active_phase,
                "lane_signal_states": self.get_lane_signal_states(),
                "phase": "all_red",
                "duration": self.phase_duration,
                "timestamp": datetime.now().isoformat(),
            }

        if self.current_phase == "all_red":
            if all_lane_counts is None:
                all_lane_counts = [self.lane_stats[i]["vehicle_count"] for i in range(self.num_lanes)]
            try:
                return self.make_decision(all_lane_counts, current_time)
            except Exception as _dec_err:
                self.logger.error(f"[Controller] make_decision error: {_dec_err} — forcing normal transition")
                next_phase = self._opposite_phase(self.active_phase)
                self._commit_green_phase(next_phase, current_time)
                return {
                    "lane_id": self.active_lane,
                    "main_lanes": list(self.active_main_lanes),
                    "secondary_lane": None,
                    "active_direction": self.active_phase,
                    "lane_signal_states": self.get_lane_signal_states(),
                    "phase": "green",
                    "mode": "error_recovery",
                    "timestamp": datetime.now().isoformat(),
                }

        return None

    def _build_state(self) -> np.ndarray:
        return self.dqn.build_state(
            lane_detections=[self.lane_stats[i]["detections"] for i in range(self.num_lanes)],
            wait_times=[self.lane_stats[i]["wait_time"] for i in range(self.num_lanes)],
            active_lane=self.active_lane,
            elapsed_green=self.elapsed_green,
            buffer_locked=self.buffer_locked,
        )

    def train_from_experience(self, state, action, reward, next_state, done=False):
        self.dqn.store_transition(state, action, reward, next_state, done)
        self.dqn.train_step()

    def get_current_status(self) -> Dict:
        elapsed = time.time() - self.phase_start_time
        remaining = max(0.0, self.phase_duration - elapsed)
        return {
            "current_lane": self.active_lane,
            "active_direction": self.active_phase,
            "main_lanes": list(self.active_main_lanes),
            "secondary_lane": self.secondary_lane,
            "secondary_state": self.secondary_state,
            "lane_signal_states": self.get_lane_signal_states(),
            "current_phase": self.current_phase,
            "phase_elapsed": elapsed,
            "phase_remaining": remaining,
            "buffer_locked": self.buffer_locked,
            "is_emergency": self.is_emergency_active,
            "em_observing": self.emergency_lane,
            "pending_emergency_lane": self.pending_emergency_lane,
            "interrupted_lane": None,
            "interrupted_remaining": 0.0,
            "lane_stats": self.lane_stats,
            "decisions_made": self.decisions_made,
            "dqn_stats": self.dqn.get_training_stats(),
            "timestamp": datetime.now().isoformat(),
        }

    def calculate_performance_metrics(self) -> Dict:
        avg_wait = float(np.mean([self.lane_stats[i]["wait_time"] for i in range(self.num_lanes)]))
        total_q = sum(self.lane_stats[i]["vehicle_count"] for i in range(self.num_lanes))
        return {
            "total_vehicles_waiting": total_q,
            "avg_wait_time": avg_wait,
            "congestion_levels": {
                i: self.lane_stats[i]["congestion_level"]
                for i in range(self.num_lanes)
            },
            "decisions_made": self.decisions_made,
            "dqn_epsilon": self.dqn.epsilon,
            "timestamp": datetime.now().isoformat(),
        }

    def save_model(self, filepath: str):
        import os
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        self.dqn.save_model(filepath)

    def load_model(self, filepath: str):
        self.dqn.load_model(filepath)
