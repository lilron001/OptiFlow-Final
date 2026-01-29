# views/pages/incident_history.py
import tkinter as tk
from tkinter import ttk
from ..styles import Colors, Fonts

class IncidentHistoryPage:
    """Incident history page with past events"""
    
    def __init__(self, parent, controller=None):
        self.parent = parent
        self.controller = controller
        self.frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        self.tree = None
        self.create_widgets()
        
        # Load data if controller is available
        if self.controller:
            self.load_data()
    
    def create_widgets(self):
        """Create incident history page layout"""
        # Header Frame
        header = tk.Frame(self.frame, bg=Colors.BACKGROUND)
        header.pack(fill=tk.X, pady=15, padx=20)
        
        # Title
        title = tk.Label(header, text="Incident History",
                        font=Fonts.TITLE, bg=Colors.BACKGROUND,
                        fg=Colors.PRIMARY)
        title.pack(side=tk.LEFT)
        
        # Refresh Button
        refresh_btn = tk.Button(header, text="🔄 Refresh",
                              command=self.load_data,
                              font=Fonts.BODY,
                              bg=Colors.SECONDARY, fg=Colors.TEXT,
                              relief=tk.FLAT, padx=15, pady=5)
        refresh_btn.pack(side=tk.RIGHT)
        
        # Main content
        content_frame = tk.Frame(self.frame, bg=Colors.BACKGROUND)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Treeview for incidents
        tree_frame = tk.Frame(content_frame, bg=Colors.CARD_BG)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create columns
        columns = ('Date', 'Time', 'Lane', 'Type', 'Severity', 'Description')
        self.tree = ttk.Treeview(tree_frame, columns=columns, height=10)
        
        # Configure column headings
        self.tree.heading('#0', text='ID')
        self.tree.column('#0', width=0, stretch=tk.NO) # Hide ID column
        
        headings = {
            'Date': 100,
            'Time': 80,
            'Lane': 80,
            'Type': 100,
            'Severity': 100,
            'Description': 250
        }
        
        for col, width in headings.items():
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width)
        
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
    def load_data(self):
        """Load data from controller"""
        if not self.controller:
            return
            
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Fetch incidents
        incidents = self.controller.get_incidents()
        
        if not incidents:
            return
            
        for inc in incidents:
            # Parse timestamp "2026-01-29T20:22:46.123456"
            # Parse timestamp potentially from multiple field names
            try:
                dt_str = inc.get('created_at') or inc.get('timestamp', '')
                if 'T' in dt_str:
                    date_part, time_part = dt_str.split('T')
                    time_part = time_part.split('.')[0] # Remove microseconds
                else:
                    date_part = dt_str
                    time_part = ""
            except:
                date_part = "Unknown"
                time_part = "Unknown"
            
            self.tree.insert('', tk.END, values=(
                date_part,
                time_part,
                f"Lane {inc.get('lane', '?')}",
                "Accident", # Type is implicitly accident here
                inc.get('severity', 'Moderate'),
                inc.get('description', '')
            ))
    
    def get_widget(self):
        return self.frame
