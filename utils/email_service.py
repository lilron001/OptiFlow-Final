# utils/email_service.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import random
import string
from datetime import datetime, timedelta
import logging
import threading
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

class EmailService:
    """Handle email sending and verification"""
    
    def __init__(self):
        self.smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.sender_email = os.environ.get("SENDER_EMAIL", "your_email@gmail.com")
        self.sender_password = os.environ.get("SENDER_PASSWORD", "your_app_password")
        self.verification_codes = {}  # Store codes temporarily
    
    def generate_verification_code(self, length=6):
        """Generate a random verification code"""
        return ''.join(random.choices(string.digits, k=length))
    
    def send_verification_email(self, recipient_email, username):
        """Send verification email with code"""
        # Generate code
        code = self.generate_verification_code()
        
        # Store code with expiration (10 minutes)
        self.verification_codes[recipient_email] = {
            'code': code,
            'expires': datetime.now() + timedelta(minutes=10),
            'username': username
        }
        
        # Check if using default credentials or missing credentials
        email_sent = False
        
        if self.sender_password == "your_app_password" or not self.sender_password:
            print(f"\n[DEV MODE] Email not configured. Verification code: {code}\n")
            logger.warning(f"Email not configured. Verification code for {recipient_email}: {code}")
            # In dev mode, we consider it "handled" but email_sent is False
            return True, code, False
        
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = "OptiFlow - Email Verification"
            message["From"] = self.sender_email
            message["To"] = recipient_email
            
            # Plain text version
            text = f"""
            Hello {username},
            
            Welcome to OptiFlow Traffic Management System!
            
            Your verification code is: {code}
            
            This code will expire in 10 minutes.
            
            If you did not create an account, please ignore this email.
            
            Best regards,
            OptiFlow Team
            """
            
            # HTML version - Dark Theme
            html = f"""
            <html>
              <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #0f172a; padding: 20px; color: #f8fafc;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #1e293b; padding: 40px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5); border: 1px solid #334155;">
                  <h2 style="color: #3b82f6; text-align: center; margin-top: 0; font-size: 24px;">🛡️ OptiFlow</h2>
                  <h3 style="color: #f8fafc; text-align: center; margin-bottom: 30px; font-weight: 500;">Email Verification</h3>
                  
                  <p style="color: #e2e8f0; font-size: 16px; line-height: 1.6;">Hello <strong>{username}</strong>,</p>
                  
                  <p style="color: #cbd5e1; font-size: 16px; line-height: 1.6;">Welcome to OptiFlow Traffic Management System! To complete your registration, please verify your email address.</p>
                  
                  <div style="background-color: #0f172a; padding: 25px; border-radius: 12px; text-align: center; margin: 30px 0; border: 1px solid #3b82f6;">
                    <p style="color: #94a3b8; font-size: 13px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 1px;">Verification Code</p>
                    <h1 style="color: #3b82f6; letter-spacing: 8px; margin: 0; font-size: 36px; font-weight: bold;">{code}</h1>
                  </div>
                  
                  <p style="color: #94a3b8; font-size: 14px; text-align: center;">This code will expire in <strong>10 minutes</strong>.</p>
                  
                  <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #334155; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">If you did not create an account, you can safely ignore this email.</p>
                    <p style="color: #64748b; font-size: 12px; margin-top: 8px;">© 2026 OptiFlow. All rights reserved.</p>
                  </div>
                </div>
              </body>
            </html>
            """
            
            part1 = MIMEText(text, "plain")
            part2 = MIMEText(html, "html")
            message.attach(part1)
            message.attach(part2)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, recipient_email, message.as_string())
            
            logger.info(f"Verification email sent to {recipient_email}")
            email_sent = True
            
        except Exception as e:
            logger.error(f"Error sending email to {recipient_email}: {e}")
            print(f"\n[FALLBACK] Failed to send email. Verification code: {code}\n")
            # Email failed, but we still generated a valid code
            email_sent = False
        
        return True, code, email_sent

    def verify_code(self, email, code):
        """Verify the provided code"""
        if email not in self.verification_codes:
            return False, "No verification code found for this email"
        
        stored = self.verification_codes[email]
        
        # Check expiration
        if datetime.now() > stored['expires']:
            del self.verification_codes[email]
            return False, "Verification code has expired"
        
        # Check code
        if stored['code'] != code:
            return False, "Invalid verification code"
        
        # Code is valid, remove it
        del self.verification_codes[email]
        return True, "Email verified successfully"
    
    def is_email_verified(self, email):
        """Check if email is already verified"""
        return email not in self.verification_codes
    
    def send_password_reset_email(self, recipient_email, username):
        """Send password reset email with code"""
        # Generate code
        code = self.generate_verification_code()
        
        # Store code with expiration (15 minutes for password reset)
        self.verification_codes[f"reset_{recipient_email}"] = {
            'code': code,
            'expires': datetime.now() + timedelta(minutes=15),
            'username': username,
            'type': 'reset'
        }
        
        # Check if using default credentials or missing credentials
        email_sent = False
        if self.sender_password == "your_app_password" or not self.sender_password:
            print(f"\n[DEV MODE] Email not configured. Password reset code: {code}\n")
            logger.warning(f"Email not configured. Reset code for {recipient_email}: {code}")
            return True, code, False
        
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = "OptiFlow - Password Reset Request"
            message["From"] = self.sender_email
            message["To"] = recipient_email
            
            # Plain text version
            text = f"""
            Hello {username},
            
            We received a request to reset your password for your OptiFlow account.
            
            Your password reset code is: {code}
            
            This code will expire in 15 minutes.
            
            If you did not request a password reset, please ignore this email.
            
            Best regards,
            OptiFlow Team
            """
            
            # HTML version - Dark Theme
            html = f"""
            <html>
              <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #0f172a; padding: 20px; color: #f8fafc;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #1e293b; padding: 40px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5); border: 1px solid #334155;">
                  <h2 style="color: #3b82f6; text-align: center; margin-top: 0; font-size: 24px;">🛡️ OptiFlow</h2>
                  <h3 style="color: #f8fafc; text-align: center; margin-bottom: 30px; font-weight: 500;">Password Reset Request</h3>
                  
                  <p style="color: #e2e8f0; font-size: 16px; line-height: 1.6;">Hello <strong>{username}</strong>,</p>
                  
                  <p style="color: #cbd5e1; font-size: 16px; line-height: 1.6;">We received a request to reset your password for your OptiFlow account.</p>
                  
                  <div style="background-color: #0f172a; padding: 25px; border-radius: 12px; text-align: center; margin: 30px 0; border: 1px solid #ef4444;">
                    <p style="color: #94a3b8; font-size: 13px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 1px;">Password Reset Code</p>
                    <h1 style="color: #ef4444; letter-spacing: 8px; margin: 0; font-size: 36px; font-weight: bold;">{code}</h1>
                  </div>
                  
                  <p style="color: #94a3b8; font-size: 14px; text-align: center;">This code will expire in <strong>15 minutes</strong>.</p>
                  
                  <p style="color: #cbd5e1; font-size: 14px; text-align: center; margin-top: 20px;">If you did not request a password reset, please ignore this email or contact support.</p>
                  
                  <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #334155; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">© 2026 OptiFlow. All rights reserved.</p>
                  </div>
                </div>
              </body>
            </html>
            """
            
            part1 = MIMEText(text, "plain")
            part2 = MIMEText(html, "html")
            message.attach(part1)
            message.attach(part2)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, recipient_email, message.as_string())
            
            logger.info(f"Password reset email sent to {recipient_email}")
            email_sent = True
            
        except Exception as e:
            logger.error(f"Error sending password reset email to {recipient_email}: {e}")
            print(f"\n[FALLBACK] Failed to send email. Password reset code: {code}\n")
            email_sent = False
        
        return True, code, email_sent
    
    def verify_reset_code(self, email, code):
        """Verify password reset code"""
        key = f"reset_{email}"
        if key not in self.verification_codes:
            return False, "No password reset request found for this email"
        
        stored = self.verification_codes[key]
        
        # Check expiration
        if datetime.now() > stored['expires']:
            del self.verification_codes[key]
            return False, "Password reset code has expired"
        
        # Check code
        if stored['code'] != code:
            return False, "Invalid password reset code"
        
        # Code is valid, remove it
        del self.verification_codes[key]
        return True, "Code verified successfully"
