# views/pages/settings.py
import tkinter as tk
from tkinter import ttk
from ..styles import Colors, Fonts
from utils.app_config import SETTINGS

class SettingsPage:
    """Settings page for system preferences"""
    
    def __init__(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        
        # Store variables to prevent garbage collection
        self.toggles = {} 
        
        self.create_widgets()
    
    def create_widgets(self):
        """Create settings page layout"""
        print("Initializing Settings Page Widgets...")
        
        # Title
        title = tk.Label(self.frame, text="System Preferences",
                        font=Fonts.TITLE, bg=Colors.BACKGROUND,
                        fg=Colors.PRIMARY)
        title.pack(pady=15)
        
        # Main content container
        content_frame = tk.Frame(self.frame, bg=Colors.BACKGROUND)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # 1. Visualization Settings
        self.create_section(content_frame, "Visual & Display", [
            ("Show Bounding Boxes", "show_bounding_boxes"),
            ("Show Confidence Scores", "show_confidence"),
            ("Show Simulation Overlay", "show_simulation_text"),
        ])
        
        # 2. Performance/System Settings
        self.create_section(content_frame, "System & Performance", [
            ("Enable AI Detection", "enable_detection"),
            ("Simulate Accidents/Violations", "enable_sim_events"), 
            ("Camera Filter (Invert)", "dark_mode_cam"),
        ])

        # 3. Notifications
        self.create_section(content_frame, "Notifications", [
            ("Turn on Notification", "enable_notifications"),
        ])
        
        # Note
        note_frame = tk.Frame(self.frame, bg=Colors.BACKGROUND)
        note_frame.pack(fill=tk.X, padx=20, pady=20)
        note_lbl = tk.Label(note_frame, text="* Changes apply immediately", 
                           font=("Segoe UI", 10, "italic"), bg=Colors.BACKGROUND, fg=Colors.TEXT_LIGHT)
        note_lbl.pack(anchor=tk.E)

    def create_section(self, parent, title_text, options):
        """Create a styled settings section"""
        frame = tk.Frame(parent, bg=Colors.CARD_BG, relief=tk.RAISED, bd=1)
        frame.pack(fill=tk.X, pady=10)
        
        # Header
        header = tk.Label(frame, text=title_text, font=Fonts.HEADING, 
                         bg=Colors.CARD_BG, fg=Colors.PRIMARY)
        header.pack(anchor=tk.W, padx=15, pady=(10, 5))
        
        # Options
        for label_text, config_key in options:
            self.create_toggle(frame, label_text, config_key)
            
        # Spacing
        tk.Frame(frame, bg=Colors.CARD_BG, height=5).pack()

    def create_toggle(self, parent, label_text, config_key):
        """Create a checkbox that modifies SETTINGS directly"""
        # Get current value from global config
        current_val = SETTINGS.get(config_key, False)
        
        # Create and store BooleanVar
        var = tk.BooleanVar(value=current_val)
        self.toggles[config_key] = var
        
        def on_toggle():
            # Apply to global config
            new_val = self.toggles[config_key].get()
            SETTINGS[config_key] = new_val
            print(f"Setting '{config_key}' toggled to {new_val}")
            
        chk = tk.Checkbutton(parent, text=label_text, variable=var, 
                            command=on_toggle,
                            font=Fonts.BODY, 
                            bg=Colors.CARD_BG, 
                            fg=Colors.TEXT,
                            activebackground=Colors.CARD_BG, 
                            activeforeground=Colors.TEXT,
                            selectcolor=Colors.CARD_BG, # Matches background
                            padx=10, pady=5)
        chk.pack(anchor=tk.W, padx=20)
    
    def get_widget(self):
        return self.frame
