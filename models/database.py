# models/database.py
import os

from datetime import datetime
from dotenv import load_dotenv
import logging
try:
    from supabase import create_client, Client
except ImportError as e:
    print(f"WARNING: Could not import supabase: {e}")
    print("Attempting to install supabase...")
    import subprocess
    import sys
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "supabase", "-q"])
        from supabase import create_client, Client
    except Exception as install_err:
        print(f"Failed to auto-install supabase: {install_err}")
        create_client = None
        Client = None

from typing import Dict, List, Optional, Any

# Load environment variables from .env file FIRST - with absolute path
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path=env_path, override=True)

class TrafficDB:
    """Supabase database connection and operations"""
    
    def __init__(self):
        self.url: str = os.environ.get("SUPABASE_URL")
        self.key: str = os.environ.get("SUPABASE_KEY")
        self.supabase: Optional[Any] = None
        self.logger = self.setup_logging()
        
        # Initialize Supabase client
        self.initialize_supabase()
    
    def setup_logging(self):
        """Setup logging"""
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)
    
    def initialize_supabase(self) -> bool:
        """Initialize Supabase client with credentials"""
        if not self.url or not self.key:
            self.logger.warning("Supabase credentials not found in environment. Database operations will be limited.")
            return False
        
        try:
            if create_client is None:
                raise ImportError("supabase library not installed")
                
            self.supabase: Client = create_client(self.url, self.key)
            self.logger.info("Supabase client initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Supabase: {e}")
            return False
    
    def is_connected(self) -> bool:
        """Check if database is connected"""
        return self.supabase is not None
    
    # Vehicle Operations
    def save_vehicle(self, vehicle_type: str, lane: int) -> Optional[str]:
        """Save detected vehicle to database"""
        if not self.is_connected():
            return None
            
        try:
            data = {
                "vehicle_type": vehicle_type,
                "lane": lane,
                "detected_at": datetime.utcnow().isoformat()
            }
            response = self.supabase.table("vehicles").insert(data).execute()
            self.logger.info(f"Vehicle saved: {response.data[0]['vehicle_id']}")
            return response.data[0]['vehicle_id']
        except Exception as e:
            self.logger.error(f"Error saving vehicle: {e}")
            return None
    
    # Violation Operations
    def save_violation(self, vehicle_id: str, lane: int, 
                      violation_type: str = "Red Light Violation", 
                      source: str = "SYSTEM") -> Optional[str]:
        """Save traffic violation"""
        if not self.is_connected():
            return None
            
        try:
            data = {
                "vehicle_id": vehicle_id,
                "violation_type": violation_type,
                "lane": lane,
                "source": source,
                # "reported_by": None,  # Optional: Pass User ID if available
                "created_at": datetime.utcnow().isoformat()
            }
            response = self.supabase.table("violations").insert(data).execute()
            self.save_system_log("VIOLATION_DETECTED", f"{violation_type} on lane {lane}")
            return response.data[0]['violation_id']
        except Exception as e:
            self.logger.error(f"Error saving violation: {e}")
            return None
    
    def get_recent_violations(self, limit: int = 50) -> List[Dict]:
        """Get recent violations"""
        try:
            response = self.supabase.table("violations")\
                .select("*, vehicles(*)")\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()
            return response.data
        except Exception as e:
            self.logger.error(f"Error fetching violations: {e}")
            return []
    
    # Accident Operations
    def save_accident(self, lane: int, severity: str = "Moderate", 
                     detection_type: str = "SYSTEM", 
                     description: str = "", 
                     reported_by: str = None) -> Optional[str]:
        """Save accident detection"""
        try:
            # Ensure severity case matches CHECK constraint
            severity = severity.capitalize() 
            if severity not in ['Minor', 'Moderate', 'Severe']:
                severity = 'Moderate'
            
            data = {
                "lane": lane,
                "severity": severity,
                "detection_type": detection_type,
                "description": description,
                # "reported_by": reported_by, # Needs valid UUID, better to leave null for system
                "status": "pending",
                "created_at": datetime.utcnow().isoformat()
            }
            response = self.supabase.table("accidents").insert(data).execute()
            self.save_system_log("ACCIDENT_DETECTED", f"Accident on lane {lane} - {severity}")
            return response.data[0]['accident_id']
        except Exception as e:
            self.logger.error(f"Error saving accident: {e}")
            return None
    
    def get_recent_accidents(self, limit: int = 50) -> List[Dict]:
        """Get recent accidents"""
        try:
            response = self.supabase.table("accidents")\
                .select("*")\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()
            return response.data
        except Exception as e:
            self.logger.error(f"Error fetching accidents: {e}")
            return []
    
    def get_accident_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get accident statistics"""
        try:
            response = self.supabase.table("accidents")\
                .select("*")\
                .gte("created_at", f"now() - interval '{hours} hours'")\
                .execute()
            
            accidents = response.data
            stats = {
                "total": len(accidents),
                "by_severity": {
                    "Minor": len([a for a in accidents if a['severity'] == 'Minor']),
                    "Moderate": len([a for a in accidents if a['severity'] == 'Moderate']),
                    "Severe": len([a for a in accidents if a['severity'] == 'Severe'])
                },
                "by_type": {
                    "SYSTEM": len([a for a in accidents if a['detection_type'] == 'SYSTEM']),
                    "MANUAL": len([a for a in accidents if a['detection_type'] == 'MANUAL'])
                }
            }
            return stats
        except Exception as e:
            self.logger.error(f"Error fetching accident stats: {e}")
            return {}
    
    # Emergency Operations
    def log_emergency_event(self, vehicle_type: str, lane: int, 
                           action_taken: str) -> Optional[str]:
        """Log emergency vehicle prioritization"""
        try:
            data = {
                "vehicle_type": vehicle_type,
                "lane": lane,
                "action_taken": action_taken,
                "created_at": datetime.utcnow().isoformat()
            }
            response = self.supabase.table("emergency_events").insert(data).execute()
            return response.data[0]['event_id']
        except Exception as e:
            self.logger.error(f"Error logging emergency: {e}")
            return None
    
    # Issue Reporting
    def create_report(self, title: str, description: str, priority: str, 
                     author_id: str = None, author_name: str = "Anonymous") -> bool:
        """Create a new issue report"""
        try:
            data = {
                "title": title,
                "description": description,
                "priority": priority,
                "status": "Open",
                "author_id": author_id,
                "author_name": author_name,
                "created_at": datetime.utcnow().isoformat()
            }
            # Attempt to insert, might fail if table doesn't exist yet
            self.supabase.table("reports").insert(data).execute()
            self.save_system_log("REPORT_CREATED", f"New report: {title}")
            return True
        except Exception as e:
            self.logger.error(f"Error creating report: {e}")
            return False

    def get_all_reports(self) -> List[Dict]:
        """Get all issue reports"""
        try:
            response = self.supabase.table("reports")\
                .select("*")\
                .order("created_at", desc=True)\
                .execute()
            return response.data
        except Exception as e:
            self.logger.error(f"Error fetching reports: {e}")
            return []

    def get_report(self, report_id: str) -> Optional[Dict]:
        """Get specific report details"""
        try:
            response = self.supabase.table("reports")\
                .select("*")\
                .eq("report_id", report_id)\
                .execute()
            return response.data[0] if response.data else None
        except Exception as e:
            self.logger.error(f"Error fetching report: {e}")
            return None

    # System Logs
    def save_system_log(self, event_type: str, description: str) -> None:
        """Save system log entry"""
        try:
            data = {
                "event_type": event_type,
                "description": description,
                "created_at": datetime.utcnow().isoformat()
            }
            self.supabase.table("system_logs").insert(data).execute()
        except Exception as e:
            self.logger.error(f"Error saving log: {e}")
    
    # ==================== USER MANAGEMENT ====================
    
    def create_user(self, first_name: str, last_name: str, username: str, email: str, password_hash: str, 
                   role: str = "operator", is_active: bool = True) -> tuple[Optional[str], Optional[str]]:
        """Create a new user account. Returns (user_id, error_message)"""
        if not self.is_connected():
            return None, "Database not connected"
            
        try:
            # Check if user already exists
            existing = self.supabase.table("users")\
                .select("user_id")\
                .eq("username", username)\
                .execute()
            
            if existing.data:
                self.logger.warning(f"User {username} already exists")
                return None, f"User '{username}' already exists"
            
            data = {
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
                "email": email,
                "password_hash": password_hash,
                "role": role
            }
            response = self.supabase.table("users").insert(data).execute()
            self.logger.info(f"User created: {username}")
            return response.data[0]['user_id'], None
        except Exception as e:
            self.logger.error(f"Error creating user: {e}")
            # Try to extract a friendly error message
            msg = str(e)
            # Handle postgrest error format
            if hasattr(e, 'details') and e.details: # type: ignore
                msg = str(e.details) # type: ignore
            elif hasattr(e, 'message') and e.message: # type: ignore
                msg = e.message # type: ignore
            elif hasattr(e, 'code') and e.code:
                 msg = f"Database Error ({e.code})"
            
            return None, msg
    
    def authenticate_user(self, username: str, password_hash: str) -> Optional[Dict]:
        """Authenticate user and return user data"""
        if not self.is_connected():
            return None
            
        try:
            response = self.supabase.table("users")\
                .select("*")\
                .eq("username", username)\
                .execute()
            
            if not response.data:
                self.logger.warning(f"User not found: {username}")
                return None
            
            user = response.data[0]
            # Check is_active only if column exists
            if 'is_active' in user and not user['is_active']:
                self.logger.warning(f"User account is inactive: {username}")
                return None
            
            if user['password_hash'] != password_hash:
                self.logger.warning(f"Invalid password for user: {username}")
                return None
            
            self.logger.info(f"User authenticated: {username}")
            return user
        except Exception as e:
            self.logger.error(f"Error authenticating user: {e}")
            return None
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username"""
        try:
            response = self.supabase.table("users")\
                .select("*")\
                .eq("username", username)\
                .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            self.logger.error(f"Error fetching user: {e}")
            return None
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by ID"""
        try:
            response = self.supabase.table("users")\
                .select("*")\
                .eq("user_id", user_id)\
                .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            self.logger.error(f"Error fetching user: {e}")
            return None
    
    def get_all_users(self) -> List[Dict]:
        """Get all users (admin only)"""
        try:
            response = self.supabase.table("users")\
                .select("*")\
                .order("created_at", desc=True)\
                .execute()
            
            return response.data
        except Exception as e:
            self.logger.error(f"Error fetching users: {e}")
            return []
    
    def update_user(self, user_id: str, **kwargs) -> bool:
        """Update user information"""
        if not self.is_connected():
            return False
            
        try:
            # Filter out user_id from kwargs
            update_data = {k: v for k, v in kwargs.items() if k not in ['user_id']}
            
            response = self.supabase.table("users")\
                .update(update_data)\
                .eq("user_id", user_id)\
                .execute()
            
            self.logger.info(f"User updated: {user_id}")
            return bool(response.data)
        except Exception as e:
            self.logger.error(f"Error updating user: {e}")
            return False
    
    def delete_user(self, user_id: str) -> bool:
        """Delete user account"""
        try:
            response = self.supabase.table("users")\
                .delete()\
                .eq("user_id", user_id)\
                .execute()
            
            self.logger.info(f"User deleted: {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting user: {e}")
            return False
    
    def check_username_available(self, username: str) -> bool:
        """Check if username is available"""
        try:
            response = self.supabase.table("users")\
                .select("user_id")\
                .eq("username", username)\
                .execute()
            
            return len(response.data) == 0
        except Exception as e:
            self.logger.error(f"Error checking username: {e}")
            return False
    
    def check_email_available(self, email: str) -> bool:
        """Check if email is available"""
        try:
            response = self.supabase.table("users")\
                .select("user_id")\
                .eq("email", email)\
                .execute()
            
            return len(response.data) == 0
        except Exception as e:
            self.logger.error(f"Error checking email: {e}")
            return False