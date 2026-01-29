# controllers/violation_controller.py
from models.database import TrafficDB

class ViolationController:
    """Handle traffic violation reports"""
    def __init__(self, db: TrafficDB):
        self.db = db
    
    def save_violation(self, lane, violation_type="Red Light Violation"):
        """Save violation to database or local file fallback"""
        vehicle_id = "SYS-DETECTION"
        
        # Try database first
        try:
            result = self.db.save_violation(vehicle_id, lane, violation_type, source="AI_SYSTEM")
            if result:
                return result
        except Exception:
            pass # Fallback
            
        # Fallback: Save to local CSV/JSON if DB fails
        self._save_to_local_fallback(lane, violation_type, vehicle_id)
        return "LOCAL_ID"

    def get_logs(self):
        """Get recent violation logs (from DB or local)"""
        logs = self.db.get_recent_violations(limit=50)
        if not logs:
            return self._get_local_logs()
        return logs

    def _save_to_local_fallback(self, lane, v_type, v_id):
        import json
        import os
        from datetime import datetime
        
        file_path = "violation_logs_local.json"
        
        new_log = {
            "lane": lane,
            "violation_type": v_type,
            "vehicle_id": v_id,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "Localized (DB Offline)"
        }
        
        try:
            data = []
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
            
            data.insert(0, new_log)
            # Keep only last 50
            data = data[:50]
            
            with open(file_path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Local save error: {e}")

    def _get_local_logs(self):
        import json
        import os
        file_path = "violation_logs_local.json"
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []
