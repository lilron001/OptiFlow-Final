# views/pages/violation_logs.py
import tkinter as tk
from tkinter import ttk
from ..styles import Colors, Fonts
from datetime import datetime

class ViolationLogsPage:
    """Violation logs page with traffic violations database"""
    
    def __init__(self, parent, controller=None):
        self.parent = parent
        self.controller = controller
        self.frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        self.tree = None
        self.create_widgets()
        
        # Load data immediately
        self.refresh_data()
    
    def create_widgets(self):
        """Create violation logs page layout"""
        # Header Frame
        header_frame = tk.Frame(self.frame, bg=Colors.BACKGROUND)
        header_frame.pack(fill=tk.X, padx=20, pady=15)
        
        # Title
        title = tk.Label(header_frame, text="Violation Logs",
                        font=Fonts.TITLE, bg=Colors.BACKGROUND,
                        fg=Colors.PRIMARY)
        title.pack(side=tk.LEFT)
        
        # Refresh Button
        refresh_btn = tk.Button(header_frame, text="🔄 Refresh",
                               font=Fonts.BODY, bg=Colors.PRIMARY, fg=Colors.WHITE,
                               relief=tk.FLAT, padx=15, pady=5, cursor="hand2",
                               command=self.refresh_data)
        refresh_btn.pack(side=tk.RIGHT)
        
        # Main content
        content_frame = tk.Frame(self.frame, bg=Colors.BACKGROUND)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Treeview for violations
        tree_frame = tk.Frame(content_frame, bg=Colors.CARD_BG)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create columns
        columns = ('Date', 'Time', 'Lane', 'Violation Type', 'Vehicle ID', 'Status')
        self.tree = ttk.Treeview(tree_frame, columns=columns, height=15, show='headings')
        
        # Configure column headings
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120)
        
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        # Style treeview
        style = ttk.Style()
        style.configure("Treeview", 
                       background=Colors.CARD_BG,
                       foreground=Colors.TEXT, 
                       fieldbackground=Colors.CARD_BG,
                       font=Fonts.BODY,
                       rowheight=30)
        style.configure("Treeview.Heading",
                       background=Colors.SECONDARY,
                       foreground="black",
                       font=Fonts.BODY_BOLD)
        style.map('Treeview', background=[('selected', Colors.PRIMARY)])

    def refresh_data(self):
        """Fetch and display logs from controller"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        if not self.controller:
            return
            
        logs = self.controller.get_logs()
        
        for log in logs:
            # Parse timestamp safely
            # Parse timestamp safely
            try:
                date_str_raw = log.get('created_at') or log.get('timestamp', '')
                dt_obj = datetime.fromisoformat(date_str_raw.replace('Z', '+00:00'))
                date_str = dt_obj.strftime('%Y-%m-%d')
                time_str = dt_obj.strftime('%H:%M:%S')
            except:
                date_str = "Unknown"
                time_str = "Unknown"
                
                
            # Map lane ID to Direction Name
            lane_id = log.get('lane', '?')
            lane_map = {0: 'North', 1: 'South', 2: 'East', 3: 'West', '0': 'North', '1': 'South', '2': 'East', '3': 'West'}
            lane = lane_map.get(lane_id, f"Lane {lane_id}")
            
            v_type = log.get('violation_type', 'Unknown')
            veh_id = log.get('vehicle_id', 'N/A')
            status = "Recorded" # Default status
            
            self.tree.insert('', tk.END, values=(date_str, time_str, lane, v_type, veh_id, status))
            
    def get_widget(self):
        # Refresh when shown
        self.refresh_data()
        return self.frame
