# views/pages/issue_reports.py
import tkinter as tk
from tkinter import ttk, filedialog
import customtkinter as ctk
from views.components.message_box import MessageBox
from ..styles import Colors, Fonts
from datetime import datetime
import os
import shutil

class IssueReportsPage:
    """Page for managing and viewing issue reports with CustomTkinter styling"""
    
    def __init__(self, parent, db=None, current_user=None):
        self.parent = parent
        self.db = db
        self.current_user = current_user
        self.frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        self.create_widgets()
        
    def create_widgets(self):
        """Create page layout"""
        # Header
        header_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        header_frame.pack(fill=tk.X, padx=40, pady=(30, 15))
        
        # Title
        title_container = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_container.pack(side=tk.LEFT)
        
        ctk.CTkLabel(title_container, text="Issue Reports",
                     font=('Segoe UI', 24, 'bold'),
                     text_color=Colors.TEXT).pack(anchor=tk.W)
                
        ctk.CTkLabel(title_container, text="Submit, track, and resolve system issues directly.",
                     font=('Segoe UI', 14),
                     text_color=Colors.TEXT_MUTED).pack(anchor=tk.W, pady=(5, 0))
        
        # New Report Button
        new_btn = ctk.CTkButton(header_frame, text="+ NEW REPORT",
                                font=('Segoe UI', 13, 'bold'),
                                fg_color=Colors.PRIMARY, 
                                hover_color=Colors.PRIMARY_DARK,
                                corner_radius=8,
                                width=140, height=36,
                                command=self.show_create_report_dialog)
        new_btn.pack(side=tk.RIGHT)
        
        # Reports List Card (Treeview)
        # Main content - Premium card styling
        card_frame = ctk.CTkFrame(self.frame, fg_color='#161F33', corner_radius=15, border_width=1, border_color='#2c3a52')
        card_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=(10, 30))
        
        # Inner padding frame
        list_frame = ctk.CTkFrame(card_frame, fg_color="transparent")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Style for Treeview matching dashboard theme
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Reports.Treeview", 
                        background="#0B111D",
                        foreground=Colors.TEXT,
                        fieldbackground="#0B111D",
                        rowheight=45,
                        borderwidth=0,
                        font=('Segoe UI', 11))
        
        style.configure("Reports.Treeview.Heading",
                        font=('Segoe UI', 12, 'bold'),
                        background="#1A2332",
                        foreground=Colors.TEXT_LIGHT,
                        relief="flat", borderwidth=0)
                       
        style.map("Reports.Treeview", 
                  background=[('selected', Colors.PRIMARY)],
                  foreground=[('selected', 'white')])
        
        style.map('Reports.Treeview.Heading', background=[('active', '#2c3a52')])
        
        columns = ("id", "date", "title", "priority", "status", "author")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", 
                                 style="Reports.Treeview", selectmode="browse")
        
        # Column Headings
        self.tree.heading("id", text="ID")
        self.tree.heading("date", text="DATE")
        self.tree.heading("title", text="TITLE")
        self.tree.heading("priority", text="PRIORITY")
        self.tree.heading("status", text="STATUS")
        self.tree.heading("author", text="AUTHOR")
        
        # Column Widths
        self.tree.column("id", width=0, stretch=tk.NO) # Hidden ID
        self.tree.column("date", width=150, anchor="center")
        self.tree.column("title", width=400, anchor="w")
        self.tree.column("priority", width=100, anchor="center")
        self.tree.column("status", width=100, anchor="center")
        self.tree.column("author", width=150, anchor="center")
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Modern Scrollbar
        scrollbar = ctk.CTkScrollbar(list_frame, orientation="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        
        # Priority row colors
        self.tree.tag_configure('priority_low',    background='#0D2B20', foreground='#10B981')
        self.tree.tag_configure('priority_medium', background='#2B2207', foreground='#F59E0B')
        self.tree.tag_configure('priority_high',   background='#2B0D0D', foreground='#EF4444')

        # Bind double click
        self.tree.bind("<Double-1>", self.on_item_double_click)

        # Initial Load
        self.load_reports()
        
    def load_reports(self):
        """Load reports from database"""
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        if self.db:
            reports = self.db.get_all_reports()
            for report in reports:
                # Format date
                try:
                    dt = datetime.fromisoformat(report.get('created_at', '').replace('Z', '+00:00'))
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    date_str = report.get('created_at', '')
                    
                priority_tag = {'Low': 'priority_low', 'Medium': 'priority_medium', 'High': 'priority_high'}.get(
                    report.get('priority', 'Medium'), 'priority_medium')
                self.tree.insert("", tk.END, values=(
                    report.get('report_id'),
                    date_str,
                    f" {report.get('title')}",
                    report.get('priority', 'Medium').upper(),
                    report.get('status', 'Open').upper(),
                    report.get('author_name', 'Unknown')
                ), tags=(priority_tag,))
    
    def show_create_report_dialog(self):
        """Show modern CTk dialog to create new report"""
        dialog = ctk.CTkToplevel(self.parent)
        dialog.title("Create New Report")
        dialog.geometry("600x750")
        dialog.configure(fg_color=Colors.BACKGROUND)
        
        # Optional: Make sure it layers properly if Main Dashboard is zoomed
        dialog.attributes('-topmost', True)
        
        # Center dialog
        dialog.transient(self.parent)
        dialog.grab_set()
        
        # Use scrollable frame for better layout with PDF attachment
        scroll_frame = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        # Form Container inside dialog
        container = ctk.CTkFrame(scroll_frame, fg_color='#161F33', corner_radius=15, border_width=1, border_color='#2c3a52')
        container.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)
        
        inner = ctk.CTkFrame(container, fg_color="transparent")
        inner.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)

        # Header
        ctk.CTkLabel(inner, text="Create Issue Report", font=('Segoe UI', 22, 'bold'), 
                     text_color=Colors.TEXT).pack(pady=(0, 25), anchor="w")
        
        # Title
        ctk.CTkLabel(inner, text="Title / Subject", font=('Segoe UI', 12, 'bold'), 
                     text_color=Colors.TEXT_MUTED).pack(anchor=tk.W, pady=(0, 5))
                
        title_entry = ctk.CTkEntry(inner, font=('Segoe UI', 14), 
                                   fg_color="#0B111D", border_color="#2c3a52", border_width=1,
                                   text_color=Colors.TEXT, placeholder_text="Describe the core issue simply...")
        title_entry.pack(fill=tk.X, ipady=6, pady=(0, 20))
        
        # Priority
        ctk.CTkLabel(inner, text="Priority", font=('Segoe UI', 12, 'bold'), 
                     text_color=Colors.TEXT_MUTED).pack(anchor=tk.W, pady=(0, 5))
                
        priority_cb = ctk.CTkOptionMenu(inner, values=["Low", "Medium", "High"],
                                        fg_color="#0B111D",
                                        button_color="#1E293B",
                                        button_hover_color="#334155",
                                        dropdown_fg_color="#0B111D",
                                        dropdown_hover_color="#1E293B",
                                        font=('Segoe UI', 13))
        priority_cb.set("Medium")
        priority_cb.pack(fill=tk.X, ipady=6, pady=(0, 20))
        
        # Description
        ctk.CTkLabel(inner, text="Description", font=('Segoe UI', 12, 'bold'), 
                     text_color=Colors.TEXT_MUTED).pack(anchor=tk.W, pady=(0, 5))
                
        desc_text = ctk.CTkTextbox(inner, font=('Segoe UI', 14), 
                                   fg_color="#0B111D", border_color="#2c3a52", border_width=1, 
                                   text_color=Colors.TEXT, corner_radius=6, height=120)
        desc_text.pack(fill=tk.BOTH, expand=False, pady=(0, 25))
        
        # PDF Attachment Section
        ctk.CTkLabel(inner, text="Attach PDF (Optional)", font=('Segoe UI', 12, 'bold'), 
                     text_color=Colors.TEXT_MUTED).pack(anchor=tk.W, pady=(0, 5))
        
        pdf_frame = ctk.CTkFrame(inner, fg_color="#0B111D", border_color="#2c3a52", border_width=1, corner_radius=6)
        pdf_frame.pack(fill=tk.X, pady=(0, 25))
        
        pdf_info_label = ctk.CTkLabel(pdf_frame, text="No file selected", font=('Segoe UI', 12), 
                                      text_color=Colors.TEXT_MUTED)
        pdf_info_label.pack(anchor=tk.W, padx=15, pady=(10, 5))
        
        selected_pdf = {"path": None}
        
        def select_pdf_file():
            file_path = filedialog.askopenfilename(
                parent=dialog,
                title="Select a PDF file",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
                initialdir=os.path.expanduser("~")
            )
            if file_path:
                selected_pdf["path"] = file_path
                file_name = os.path.basename(file_path)
                file_size = os.path.getsize(file_path) / 1024  # Size in KB
                pdf_info_label.configure(text=f"✓ {file_name} ({file_size:.1f} KB)")
                pdf_info_label.configure(text_color=Colors.SUCCESS)
        
        def clear_pdf_file():
            selected_pdf["path"] = None
            pdf_info_label.configure(text="No file selected", text_color=Colors.TEXT_MUTED)
        
        pdf_btn_frame = ctk.CTkFrame(pdf_frame, fg_color="transparent")
        pdf_btn_frame.pack(fill=tk.X, padx=15, pady=(5, 10))
        
        ctk.CTkButton(pdf_btn_frame, text="Browse PDF", command=select_pdf_file,
                      font=('Segoe UI', 11, 'bold'), fg_color=Colors.PRIMARY, 
                      hover_color=Colors.PRIMARY_DARK,
                      corner_radius=6, width=100, height=30).pack(side=tk.LEFT, padx=(0, 10))
        
        ctk.CTkButton(pdf_btn_frame, text="Clear", command=clear_pdf_file,
                      font=('Segoe UI', 11, 'bold'), fg_color='#1E293B', 
                      hover_color='#334155', text_color=Colors.TEXT,
                      corner_radius=6, width=80, height=30).pack(side=tk.LEFT)
        
        def submit():
            title = title_entry.get().strip()
            desc = desc_text.get("1.0", tk.END).strip()
            priority = priority_cb.get()
            
            if not title:
                MessageBox.showwarning("Required", "Please enter a title", parent=dialog)
                return
                
            if self.db:
                # Handle PDF attachment
                pdf_path = None
                if selected_pdf["path"]:
                    try:
                        # Create attachments folder if it doesn't exist
                        attachments_dir = os.path.join(os.getcwd(), "attachments", "reports")
                        os.makedirs(attachments_dir, exist_ok=True)
                        
                        # Copy PDF to attachments folder with timestamp to avoid conflicts
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        file_name = f"{timestamp}_{os.path.basename(selected_pdf['path'])}"
                        pdf_path = os.path.join(attachments_dir, file_name)
                        shutil.copy2(selected_pdf["path"], pdf_path)
                    except Exception as e:
                        MessageBox.showerror("Error", f"Failed to attach PDF: {str(e)}", parent=dialog)
                        return
                
                success = self.db.create_report(
                    title=title,
                    description=desc,
                    priority=priority,
                    author_id=self.current_user.get('user_id') if self.current_user else None,
                    author_name=self.current_user.get('username') if self.current_user else 'Anonymous',
                    pdf_attachment=pdf_path
                )
                
                if success:
                    MessageBox.showsuccess("Success", "Report created successfully", parent=dialog)
                    # We can drop topmost before destroying to prevent z-layer issues
                    dialog.attributes('-topmost', False)
                    dialog.destroy()
                    self.load_reports()
                else:
                    MessageBox.showerror("Error", "Failed to create report", parent=dialog)
            else:
                MessageBox.showerror("Error", "Database connection not available", parent=dialog)
        
        def safely_close():
             # Drop topmost locking rule
             dialog.attributes('-topmost', False)
             dialog.destroy()
        
        # Buttons
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(fill=tk.X)
        
        ctk.CTkButton(btn_frame, text="Submit Report", command=submit,
                      font=('Segoe UI', 13, 'bold'), fg_color=Colors.PRIMARY, 
                      hover_color=Colors.PRIMARY_DARK,
                      corner_radius=8, width=140, height=40).pack(side=tk.RIGHT)
                 
        ctk.CTkButton(btn_frame, text="Cancel", command=safely_close,
                      font=('Segoe UI', 13, 'bold'), fg_color='transparent',
                      hover_color='#334155', text_color=Colors.TEXT,
                      border_width=1, border_color='#334155',
                      corner_radius=8, width=100, height=40).pack(side=tk.RIGHT, padx=15)

    def on_item_double_click(self, event):
        """View report details"""
        item = self.tree.selection()[0]
        values = self.tree.item(item, "values")
        report_id = values[0]
        
        if self.db:
            report = self.db.get_report(report_id)
            if report:
                self.show_view_report_dialog(report)
    
    def show_view_report_dialog(self, report):
        """Show modern CTk dialog to view report details"""
        dialog = ctk.CTkToplevel(self.parent)
        dialog.title(f"Report: {report.get('title')}")
        dialog.geometry("650x700")
        dialog.configure(fg_color=Colors.BACKGROUND)
        
        dialog.attributes('-topmost', True)
        
        # Content Container
        # To simulate scrollable frame natively in CTk:
        scrollable_frame = ctk.CTkScrollableFrame(dialog, fg_color="transparent", bg_color="transparent")
        scrollable_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        # Report Card
        card = ctk.CTkFrame(scrollable_frame, fg_color='#161F33', corner_radius=15, border_width=1, border_color='#2c3a52')
        card.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)
        
        # Title
        ctk.CTkLabel(inner, text=report.get('title'), font=('Segoe UI', 24, 'bold'), 
                     text_color=Colors.TEXT, wraplength=520, justify="left").pack(anchor=tk.W, pady=(0, 25))
        
        # Metadata Frame (sleeker inline badges)
        meta_frame = ctk.CTkFrame(inner, fg_color='#0B111D', corner_radius=10)
        meta_frame.pack(fill=tk.X, pady=(0, 30))
        
        # We will pack the metadata horizontally
        inner_meta = ctk.CTkFrame(meta_frame, fg_color="transparent")
        inner_meta.pack(padx=20, pady=20, fill=tk.X)

        # Helper method for metadata groups
        def create_meta_block(parent, label, value, val_color=Colors.TEXT):
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.pack(side=tk.LEFT, expand=True, anchor="w")
            ctk.CTkLabel(frame, text=label, font=('Segoe UI', 10, 'bold'), text_color=Colors.TEXT_MUTED).pack(anchor="w")
            ctk.CTkLabel(frame, text=value, font=('Segoe UI', 14, 'bold'), text_color=val_color).pack(anchor="w", pady=(2, 0))

        priority_color = Colors.WARNING if report.get('priority') == 'Medium' else (Colors.DANGER if report.get('priority') == 'High' else Colors.SUCCESS)
        status_color = Colors.PRIMARY if report.get('status') == 'Open' else Colors.SUCCESS

        create_meta_block(inner_meta, "STATUS", report.get('status').upper(), status_color)
        create_meta_block(inner_meta, "PRIORITY", report.get('priority').upper(), priority_color)
        create_meta_block(inner_meta, "AUTHOR", report.get('author_name'))
        create_meta_block(inner_meta, "DATE", report.get('created_at')[:10])
        
        # Description
        ctk.CTkLabel(inner, text="DESCRIPTION", font=('Segoe UI', 11, 'bold'), 
                     text_color=Colors.TEXT_MUTED).pack(anchor=tk.W, pady=(0, 8))
        
        desc_lbl = ctk.CTkLabel(inner, text=report.get('description'), font=('Segoe UI', 15), 
                                text_color=Colors.TEXT, wraplength=520, justify="left")
        desc_lbl.pack(anchor=tk.W, pady=(0, 25))
        
        # PDF Attachment Section
        pdf_attachment = report.get('pdf_attachment')
        if pdf_attachment:
            ctk.CTkLabel(inner, text="ATTACHMENT", font=('Segoe UI', 11, 'bold'), 
                         text_color=Colors.TEXT_MUTED).pack(anchor=tk.W, pady=(0, 8))
            
            pdf_card = ctk.CTkFrame(inner, fg_color="#0B111D", corner_radius=10, border_width=1, border_color="#2c3a52")
            pdf_card.pack(fill=tk.X, pady=(0, 25))
            
            pdf_content = ctk.CTkFrame(pdf_card, fg_color="transparent")
            pdf_content.pack(fill=tk.BOTH, expand=True, padx=15, pady=12)
            
            # File info with icon
            pdf_info_frame = ctk.CTkFrame(pdf_content, fg_color="transparent")
            pdf_info_frame.pack(anchor=tk.W, fill=tk.X)
            
            ctk.CTkLabel(pdf_info_frame, text="📄", font=('Segoe UI', 16)).pack(side=tk.LEFT, padx=(0, 10))
            
            pdf_name = os.path.basename(pdf_attachment)
            try:
                pdf_size = os.path.getsize(pdf_attachment) / 1024  # KB
                pdf_size_str = f"{pdf_size:.1f} KB" if pdf_size < 1024 else f"{pdf_size/1024:.1f} MB"
            except:
                pdf_size_str = "Unknown size"
            
            info_text = f"{pdf_name} ({pdf_size_str})"
            ctk.CTkLabel(pdf_info_frame, text=info_text, font=('Segoe UI', 13, 'bold'), 
                         text_color=Colors.TEXT).pack(side=tk.LEFT, anchor=tk.W)
            
            # Action buttons
            btn_frame = ctk.CTkFrame(pdf_content, fg_color="transparent")
            btn_frame.pack(fill=tk.X, pady=(12, 0))
            
            def view_pdf():
                try:
                    if os.path.exists(pdf_attachment):
                        import subprocess
                        if os.name == 'nt':  # Windows
                            os.startfile(pdf_attachment)
                        else:  # Mac/Linux
                            subprocess.Popen(['open', pdf_attachment])
                    else:
                        MessageBox.showerror("Error", "PDF file not found", parent=dialog)
                except Exception as e:
                    MessageBox.showerror("Error", f"Failed to open PDF: {str(e)}", parent=dialog)
            
            def download_pdf():
                try:
                    if os.path.exists(pdf_attachment):
                        # Get default downloads folder
                        downloads_path = os.path.expanduser("~/Downloads")
                        dest_path = os.path.join(downloads_path, os.path.basename(pdf_attachment))
                        
                        # If file exists, add number suffix
                        if os.path.exists(dest_path):
                            base, ext = os.path.splitext(os.path.basename(pdf_attachment))
                            counter = 1
                            while os.path.exists(os.path.join(downloads_path, f"{base}_{counter}{ext}")):
                                counter += 1
                            dest_path = os.path.join(downloads_path, f"{base}_{counter}{ext}")
                        
                        shutil.copy2(pdf_attachment, dest_path)
                        MessageBox.showsuccess("Success", f"PDF downloaded to:\n{dest_path}", parent=dialog)
                    else:
                        MessageBox.showerror("Error", "PDF file not found", parent=dialog)
                except Exception as e:
                    MessageBox.showerror("Error", f"Failed to download PDF: {str(e)}", parent=dialog)
            
            ctk.CTkButton(btn_frame, text="👁 View PDF", command=view_pdf,
                          font=('Segoe UI', 11, 'bold'), fg_color=Colors.PRIMARY, 
                          hover_color=Colors.PRIMARY_DARK,
                          corner_radius=6, width=100, height=30).pack(side=tk.LEFT, padx=(0, 10))
            
            ctk.CTkButton(btn_frame, text="⬇ Download", command=download_pdf,
                          font=('Segoe UI', 11, 'bold'), fg_color='#1E293B', 
                          hover_color='#334155', text_color=Colors.TEXT,
                          corner_radius=6, width=100, height=30).pack(side=tk.LEFT)

        def safely_close():
            dialog.attributes('-topmost', False)
            dialog.destroy()

        # Close Button
        ctk.CTkButton(inner, text="Close Window", command=safely_close,
                      font=('Segoe UI', 13, 'bold'),
                      fg_color='#1E293B', hover_color='#334155', text_color=Colors.TEXT,
                      corner_radius=8, width=140, height=40).pack(pady=(40, 0))

    def get_widget(self):
        return self.frame
