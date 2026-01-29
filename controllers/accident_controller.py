# controllers/accident_controller.py
from models.database import TrafficDB

class AccidentController:
    """Handle accident detection and reporting"""
    def __init__(self, db: TrafficDB):
        self.db = db
    
    def report_accident(self, lane: int, severity: str = "Moderate", description: str = "Detected by AI"):
        """Report an accident to the database"""
        return self.db.save_accident(lane, severity, detection_type="SYSTEM", description=description)

    def get_incidents(self):
        """Get recent incident history"""
        return self.db.get_recent_accidents()
