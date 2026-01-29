import tkinter as tk
from ..styles import Colors, Fonts

class NotificationToast(tk.Frame):
    """A single non-blocking notification toast"""
    
    def __init__(self, parent, title, message, type_="info", duration=3000, on_close=None):
        super().__init__(parent, bg=Colors.CARD_BG, highlightbackground=Colors.SECONDARY, highlightthickness=1)
        self.type_config = {
            "info": {"icon": "ℹ️", "color": Colors.INFO},
            "success": {"icon": "✅", "color": Colors.SUCCESS},
            "warning": {"icon": "⚠️", "color": Colors.WARNING},
            "error": {"icon": "🚫", "color": Colors.DANGER},
            "violation": {"icon": "👮", "color": Colors.DANGER}
        }
        
        config = self.type_config.get(type_, self.type_config["info"])
        self.on_close = on_close
        
        # Determine Border/Accent Color
        accent_color = config["color"]
        self.configure(highlightbackground=accent_color, highlightthickness=1)
        
        # Left Accent Bar
        accent_bar = tk.Frame(self, bg=accent_color, width=5)
        accent_bar.pack(side=tk.LEFT, fill=tk.Y)
        
        # Content Area
        content = tk.Frame(self, bg=Colors.CARD_BG, padx=15, pady=10)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Header (Icon + Title)
        header = tk.Frame(content, bg=Colors.CARD_BG)
        header.pack(fill=tk.X)
        
        tk.Label(header, text=config["icon"], font=("Segoe UI", 12), bg=Colors.CARD_BG, fg="white").pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(header, text=title, font=Fonts.BODY_BOLD, bg=Colors.CARD_BG, fg="white").pack(side=tk.LEFT)
        
        # Close 'X'
        close_lbl = tk.Label(header, text="✕", font=("Arial", 10), bg=Colors.CARD_BG, fg=Colors.TEXT_LIGHT, cursor="hand2")
        close_lbl.pack(side=tk.RIGHT)
        close_lbl.bind("<Button-1>", lambda e: self.close())
        
        # Message Body
        tk.Label(content, text=message, font=Fonts.SMALL, bg=Colors.CARD_BG, fg=Colors.TEXT_LIGHT, wraplength=250, justify=tk.LEFT).pack(anchor=tk.W, pady=(5, 0))
        
        # Auto-close timer
        if duration > 0:
            self.after(duration, self.close)
            
    def close(self):
        if self.on_close:
            self.on_close(self)
        self.destroy()

class NotificationManager:
    """Manages the queue and display of notifications"""
    
    def __init__(self, root):
        self.root = root
        self.notifications = []
        self.start_y = 20
        self.spacing = 10
        self.right_margin = 20
        self.width = 300
        
    def show(self, title, message, type_="info", duration=5000):
        """Show a styled notification"""
        from utils.app_config import SETTINGS
        if not SETTINGS.get("enable_notifications", True):
            return

        # Create toast
        toast = NotificationToast(self.root, title, message, type_, duration, on_close=self._remove_toast)
        
        # Calculate Position (Stacking from top-right)
        # We need to calculate how many active toasts there are to stack them
        # Note: tkinter place() is absolute.
        
        # For simple stacking, we just count existing ones
        count = len(self.notifications)
        offset_y = self.start_y + (count * (80 + self.spacing)) # Approx height 80
        
        screen_width = self.root.winfo_width()
        x_pos = screen_width - self.width - self.right_margin
        
        toast.place(x=x_pos, y=offset_y, width=self.width, height=80)
        self.notifications.append(toast)
        
        # Play generic sound? (Optional)
        if type_ in ["error", "violation", "warning"]:
            try:
                self.root.bell()
            except:
                pass
                
    def _remove_toast(self, toast):
        if toast in self.notifications:
            self.notifications.remove(toast)
            self._rearrange()
            
    def _rearrange(self):
        """Slide remaining notifications up"""
        for i, toast in enumerate(self.notifications):
            offset_y = self.start_y + (i * (80 + self.spacing))
            toast.place(y=offset_y)
