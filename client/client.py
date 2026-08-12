import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import requests
import threading
import time
import json
import os
import sys

# Get the directory of the executable or script
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
    bundle_path = sys._MEIPASS
else:
    application_path = os.path.dirname(os.path.abspath(__file__))
    bundle_path = application_path

def get_server_url():
    # 1. Try local config.json next to the executable
    local_config = os.path.join(application_path, "config.json")
    if os.path.exists(local_config):
        try:
            with open(local_config, "r") as f:
                data = json.load(f)
                url = data.get("server_url")
                if url and "YOUR_SERVER_IP" not in url:
                    return url
        except Exception:
            pass

    # 2. Try bundled config.json inside the exe
    bundled_config = os.path.join(bundle_path, "config.json")
    if os.path.exists(bundled_config):
        try:
            with open(bundled_config, "r") as f:
                data = json.load(f)
                url = data.get("server_url")
                if url and "YOUR_SERVER_IP" not in url:
                    return url
        except Exception:
            pass

    # Default fallback
    return "http://127.0.0.1:8000"

SERVER_URL = get_server_url()

class TranscriberApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Deepgram Transcriber")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        # Upload Section
        frame = ttk.Frame(root, padding="10")
        frame.pack(fill="x")
        
        ttk.Label(frame, text="Audio File:", font=("Arial", 10, "bold")).pack(anchor="w")
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=5)
        
        self.file_path = tk.StringVar()
        ttk.Entry(btn_frame, textvariable=self.file_path, width=50).pack(side="left", padx=(0,5))
        ttk.Button(btn_frame, text="Browse", command=self.browse_file, width=10).pack(side="left")
        
        self.upload_btn = ttk.Button(frame, text="Upload & Transcribe", command=self.upload_file)
        self.upload_btn.pack(pady=10)
        
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var, foreground="gray").pack(anchor="w")
        
        # Jobs List
        ttk.Separator(root, orient="horizontal").pack(fill="x", pady=5)
        
        list_frame = ttk.Frame(root, padding="10")
        list_frame.pack(fill="both", expand=True)
        
        ttk.Label(list_frame, text="Recent Jobs:", font=("Arial", 10, "bold")).pack(anchor="w")
        
        columns = ("ID", "File", "Status", "Time")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=6)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120 if col != "File" else 180)
        self.tree.pack(fill="both", expand=True, pady=5)
        self.tree.bind("<Double-1>", self.show_result)
        
        ttk.Button(list_frame, text="Refresh List", command=self.refresh_jobs).pack(anchor="e")
        
        # Result viewer (hidden by default, shown on double-click)
        self.result_text = scrolledtext.ScrolledText(root, height=8, wrap=tk.WORD, state="disabled")
        
        self.refresh_jobs()
    
    def browse_file(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Video/Audio", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wav *.mp3 *.m4a *.ogg *.flac"),
                ("Video Files", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v"),
                ("Audio Files", "*.wav *.mp3 *.m4a *.ogg *.flac"),
                ("All Files", "*.*")
            ]
        )
        if path:
            self.file_path.set(path)
    
    def upload_file(self):
        path = self.file_path.get()
        if not path:
            messagebox.showwarning("No File", "Please select an audio file")
            return
        
        self.upload_btn.config(state="disabled")
        self.status_var.set("Uploading...")
        
        def do_upload():
            try:
                with open(path, "rb") as f:
                    files = {"file": (path.split("/")[-1], f, "audio/wav")}
                    resp = requests.post(f"{SERVER_URL}/upload", files=files, timeout=30)
                    data = resp.json()
                    
                self.root.after(0, lambda: self.status_var.set(f"Job started: {data['job_id'][:8]}..."))
                self.root.after(0, self.refresh_jobs)
                
                # Auto-poll this job
                self.poll_job(data["job_id"])
                
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self.status_var.set(f"Error: {err_msg}"))
            finally:
                self.root.after(0, lambda: self.upload_btn.config(state="normal"))
        
        threading.Thread(target=do_upload, daemon=True).start()
    
    def poll_job(self, job_id):
        def check():
            while True:
                try:
                    resp = requests.get(f"{SERVER_URL}/job/{job_id}", timeout=10)
                    data = resp.json()
                    if data["status"] in ("completed", "failed"):
                        self.root.after(0, lambda: self.status_var.set(f"Job {data['status']}!"))
                        self.root.after(0, self.refresh_jobs)
                        if data["status"] == "completed":
                            self.root.after(0, lambda: self.show_job_result(data))
                        break
                except:
                    pass
                time.sleep(3)
        
        threading.Thread(target=check, daemon=True).start()
    
    def refresh_jobs(self):
        try:
            resp = requests.get(f"{SERVER_URL}/jobs", timeout=10)
            jobs = resp.json()
            
            for item in self.tree.get_children():
                self.tree.delete(item)
            
            for job in jobs:
                self.tree.insert("", "end", values=(
                    job["id"][:8] + "...",
                    job["filename"][:20],
                    job["status"],
                    job["created_at"][:16]
                ), tags=(job["id"],))
                
        except Exception as e:
            self.status_var.set(f"Server unreachable: {e}")
    
    def show_result(self, event):
        item = self.tree.selection()[0]
        job_id = self.tree.item(item, "tags")[0]
        
        try:
            resp = requests.get(f"{SERVER_URL}/job/{job_id}", timeout=10)
            data = resp.json()
            self.show_job_result(data)
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    def show_job_result(self, data):
        self.result_text.pack(fill="both", expand=True, padx=10, pady=5)
        self.result_text.config(state="normal")
        self.result_text.delete(1.0, tk.END)
        
        if data["status"] == "completed":
            self.result_text.insert(tk.END, f"File: {data['filename']}\n")
            self.result_text.insert(tk.END, f"Completed: {data.get('completed_at', 'N/A')}\n")
            self.result_text.insert(tk.END, "-"*50 + "\n\n")
            self.result_text.insert(tk.END, data.get("result", "No result"))
        else:
            self.result_text.insert(tk.END, f"Status: {data['status']}\n")
            self.result_text.insert(tk.END, data.get("result", ""))
        
        self.result_text.config(state="disabled")

if __name__ == "__main__":
    root = tk.Tk()
    app = TranscriberApp(root)
    root.mainloop()