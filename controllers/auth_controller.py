# controllers/auth_controller.py
from models.user import User
from models.database import TrafficDB
from utils.email_service import EmailService
from views.components.message_box import MessageBox


class AuthController:
    """Handle authentication logic"""
    
    def __init__(self, db: TrafficDB):
        self.db = db
        self.current_user = None
        self.email_service = EmailService()
        self.pending_verification = {}  # Store pending registrations
    
    def register_user(self, username: str, email: str, password: str, 
                     role: str = "operator") -> bool:
        """Register a new user and send verification email"""
        # Validate inputs
        if not username or not email or not password:
            MessageBox.showerror("Error", "All fields are required")
            return False
        
        # Check if username is available
        if not self.db.check_username_available(username):
            MessageBox.showerror("Error", "Username already exists")
            return False
        
        # Check if email is available
        if not self.db.check_email_available(email):
            MessageBox.showerror("Error", "Email already exists")
            return False
        
        # Store pending registration
        password_hash = User.hash_password(password)
        self.pending_verification[email] = {
            'username': username,
            'email': email,
            'password_hash': password_hash,
            'role': role
        }
        
        # Send verification email
        success, code, email_sent = self.email_service.send_verification_email(email, username)
        if success:
            if not email_sent:
                # Fallback message for failed/unconfigured email
                msg = (
                    f"⚠️ Email delivery failed or not configured.\n\n"
                    f"Here is your verification code for testing:\n"
                    f"👉 {code}\n\n"
                    f"Please enter this code on the next screen."
                )
            else:
                # standard message
                msg = (
                    f"✅ Registration Successful!\n\n"
                    f"A verification code has been sent to:\n{email}\n\n"
                    f"⏱️ The code expires in 10 minutes.\n"
                    f"📧 Please check your email and enter the code on the next screen."
                )
            
            MessageBox.showinfo("Verification", msg)
            return True
        else:
            del self.pending_verification[email]
            MessageBox.showerror("Error", "Failed to generate verification code.")
            return False
    
    def verify_email(self, email: str, code: str) -> bool:
        """Verify email code and complete registration"""
        if email not in self.pending_verification:
            MessageBox.showerror("Error", "No pending registration for this email")
            return False
        
        # Verify code
        is_valid, message = self.email_service.verify_code(email, code)
        
        if not is_valid:
            MessageBox.showerror("Verification Error", message)
            return False
        
        # Create user
        pending = self.pending_verification[email]
        user_id, error_msg = self.db.create_user(
            pending['username'],
            pending['email'],
            pending['password_hash'],
            pending['role']
        )
        
        if user_id:
            del self.pending_verification[email]
            MessageBox.showsuccess("Success", "Account created successfully! Please login.")
            return True
        else:
            MessageBox.showerror("Error", f"Failed to create account: {error_msg}")
            return False
    
    def login(self, username: str, password: str) -> bool:
        """Authenticate user"""
        # Validate inputs
        if not username or not password:
            MessageBox.showerror("Error", "Please enter username and password")
            return False
        
        # Hash password
        password_hash = User.hash_password(password)
        
        # Authenticate user
        user = self.db.authenticate_user(username, password_hash)
        
        if user:
            self.current_user = user
            return True
        else:
            MessageBox.showerror("Error", "Invalid username or password")
            return False
    
    def reset_password(self, username: str, email: str) -> bool:
        """Send password reset email"""
        # Get user
        user = self.db.get_user_by_username(username)
        
        if not user:
            MessageBox.showerror("Error", "User not found")
            return False
        
        # Verify email matches
        if user['email'].lower() != email.lower():
            MessageBox.showerror("Error", "Email does not match username")
            return False
        
        # Store pending password reset
        self.pending_verification[f"reset_{user['email']}"] = {
            'username': username,
            'email': user['email'],
            'user_id': user['user_id']
        }
        
        # Send password reset email
        success, code, email_sent = self.email_service.send_password_reset_email(user['email'], username)
        if success:
            if not email_sent:
                # Fallback message
                msg = (
                    f"⚠️ Email delivery failed or not configured.\n\n"
                    f"Here is your reset code for testing:\n"
                    f"👉 {code}\n\n"
                    f"Please enter this code on the next screen."
                )
            else:
                # Show message without displaying the code
                msg = (
                    f"✅ Password Reset Initiated!\n\n"
                    f"A reset code has been sent to:\n{user['email']}\n\n"
                    f"⏱️ The code expires in 15 minutes.\n"
                    f"📧 Please check your email and enter the code on the next screen."
                )
                
            MessageBox.showinfo("Reset Code", msg)
            return True
        else:
            del self.pending_verification[f"reset_{user['email']}"]
            MessageBox.showerror("Error", "Failed to send password reset email")
            return False
    
    def verify_reset_code(self, email: str, code: str, new_password: str) -> bool:
        """Verify password reset code and update password"""
        key = f"reset_{email}"
        
        if key not in self.pending_verification:
            MessageBox.showerror("Error", "No password reset request for this email")
            return False
        
        # Verify code
        is_valid, message = self.email_service.verify_reset_code(email, code)
        
        if not is_valid:
            MessageBox.showerror("Verification Error", message)
            return False
        
        # Update password
        pending = self.pending_verification[key]
        password_hash = User.hash_password(new_password)
        
        success = self.db.update_user(pending['user_id'], password_hash=password_hash)
        
        if success:
            del self.pending_verification[key]
            MessageBox.showsuccess("Success", "Password reset successfully! Please login with your new password.")
            return True
        else:
            MessageBox.showerror("Error", "Failed to reset password")
            return False
    
    def logout(self):
        """Logout current user"""
        self.current_user = None
    
    def get_current_user(self):
        """Get current logged in user"""
        return self.current_user
    
    # Admin User Management
    
    def add_user(self, username: str, email: str, password: str, 
                role: str = "operator") -> bool:
        """Add new user (admin only)"""
        # Validate inputs
        if not username or not email or not password:
            MessageBox.showerror("Error", "All fields are required")
            return False
        
        # Check if username is available
        if not self.db.check_username_available(username):
            MessageBox.showerror("Error", "Username already exists")
            return False
        
        # Check if email is available
        if not self.db.check_email_available(email):
            MessageBox.showerror("Error", "Email already exists")
            return False
        
        # Hash password
        password_hash = User.hash_password(password)
        
        # Create user
        user_id, error_msg = self.db.create_user(username, email, password_hash, role)
        
        if not user_id and error_msg:
             MessageBox.showerror("Error", f"Failed to add user: {error_msg}")
        
        return user_id is not None
    
    def get_all_users(self) -> list:
        """Get all users (admin only)"""
        return self.db.get_all_users()
    
    def edit_user(self, user_id: str, email: str, role: str) -> bool:
        """Edit user information (admin only)"""
        return self.db.update_user(user_id, email=email, role=role)
    
    def delete_user(self, user_id: str) -> bool:
        """Delete user (admin only)"""
        return self.db.delete_user(user_id)
