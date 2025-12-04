"""
The Architect v0.2 - Voice-to-Code Desktop Application

Dependencies:
pip install sounddevice numpy faster-whisper google-generativeai

Requirements:
- Python 3.10+
- A Gemini API key (set in config.json)
- Microphone access
"""

import tkinter as tk
from tkinter import scrolledtext, messagebox
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
import google.generativeai as genai
import threading
import queue
import json
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
import time


# ============================================================================
# Configuration Management
# ============================================================================

class Config:
    """Manages application configuration from config.json"""
    
    DEFAULT_CONFIG = {
        "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
        "whisper_model_size": "base",
        "whisper_device": "cpu",
        "whisper_compute_type": "int8",
        "audio_sample_rate": 16000,
        "audio_channels": 1,
        "gemini_model": "gemini-1.5-pro",
        "system_prompt": "You are The Architect, an expert coding assistant. Analyze the user's voice command and the project file structure. Decide if you need to read existing files or write new/modified files. Always explain your reasoning first before taking action. Be concise but thorough.",
        "ignored_folders": [".git", "node_modules", "__pycache__", "venv", ".env", "dist", "build"],
        "max_file_size_kb": 500,
        "backup_extension": ".bak",
        "working_directory": ".",
        "gui_theme": {
            "bg_color": "#1e1e1e",
            "fg_color": "#ffffff",
            "log_bg": "#2d2d2d",
            "log_fg": "#ffffff",
            "user_text_color": "#ffeb3b",
            "ai_text_color": "#00bcd4",
            "success_color": "#4caf50",
            "error_color": "#f44336",
            "button_bg": "#0d47a1",
            "button_fg": "#ffffff",
            "button_active_bg": "#1565c0"
        }
    }
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file, create if not exists"""
        if not os.path.exists(self.config_file):
            print(f"Config file not found. Creating default {self.config_file}")
            self._save_config(self.DEFAULT_CONFIG)
            return self.DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_file, 'r') as f:
                loaded_config = json.load(f)
                # Merge with defaults to handle missing keys
                merged_config = self.DEFAULT_CONFIG.copy()
                merged_config.update(loaded_config)
                return merged_config
        except Exception as e:
            print(f"Error loading config: {e}. Using defaults.")
            return self.DEFAULT_CONFIG.copy()
    
    def _save_config(self, config: Dict[str, Any]):
        """Save configuration to JSON file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def get(self, key: str, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set configuration value and save"""
        self.config[key] = value
        self._save_config(self.config)


# ============================================================================
# File System Tools
# ============================================================================

class FileSystemTools:
    """Provides file system operations for the AI"""
    
    def __init__(self, config: Config):
        self.config = config
        self.working_dir = Path(config.get("working_directory", ".")).resolve()
        self.ignored_folders = config.get("ignored_folders", [])
        self.max_file_size = config.get("max_file_size_kb", 500) * 1024
        self.backup_ext = config.get("backup_extension", ".bak")
    
    def get_file_tree(self) -> str:
        """Generate a tree structure of the project"""
        tree_lines = [f"📁 {self.working_dir.name}/"]
        
        def build_tree(path: Path, prefix: str = "", is_last: bool = True):
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                items = [item for item in items if item.name not in self.ignored_folders]
                
                for i, item in enumerate(items):
                    is_last_item = (i == len(items) - 1)
                    current_prefix = "└── " if is_last_item else "├── "
                    tree_lines.append(f"{prefix}{current_prefix}{item.name}")
                    
                    if item.is_dir():
                        extension = "    " if is_last_item else "│   "
                        build_tree(item, prefix + extension, is_last_item)
            except PermissionError:
                pass
        
        build_tree(self.working_dir)
        return "\n".join(tree_lines)
    
    def read_file(self, path: str) -> str:
        """Read file content"""
        try:
            file_path = (self.working_dir / path).resolve()
            
            # Security check: ensure path is within working directory
            if not str(file_path).startswith(str(self.working_dir)):
                return f"ERROR: Access denied - path outside working directory"
            
            if not file_path.exists():
                return f"ERROR: File not found - {path}"
            
            if file_path.stat().st_size > self.max_file_size:
                return f"ERROR: File too large (max {self.max_file_size // 1024}KB)"
            
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"ERROR reading file: {str(e)}"
    
    def prepare_write(self, path: str, content: str) -> Dict[str, Any]:
        """Prepare file write operation (returns info for review)"""
        try:
            file_path = (self.working_dir / path).resolve()
            
            # Security check
            if not str(file_path).startswith(str(self.working_dir)):
                return {
                    "success": False,
                    "error": "Access denied - path outside working directory"
                }
            
            # Check if backup needed
            needs_backup = file_path.exists()
            
            return {
                "success": True,
                "path": str(file_path),
                "relative_path": path,
                "content": content,
                "needs_backup": needs_backup,
                "is_new": not needs_backup
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def execute_write(self, path: str, content: str) -> str:
        """Execute the actual file write (called after user approval)"""
        try:
            file_path = (self.working_dir / path).resolve()
            
            # Create backup if file exists
            if file_path.exists():
                backup_path = file_path.with_suffix(file_path.suffix + self.backup_ext)
                shutil.copy2(file_path, backup_path)
            
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            action = "Created" if not file_path.exists() else "Updated"
            return f"SUCCESS: {action} {path}"
        except Exception as e:
            return f"ERROR: {str(e)}"


# ============================================================================
# Audio & Speech Recognition
# ============================================================================

class AudioRecorder:
    """Handles audio recording and transcription"""
    
    def __init__(self, config: Config):
        self.config = config
        self.sample_rate = config.get("audio_sample_rate", 16000)
        self.channels = config.get("audio_channels", 1)
        self.recording = []
        self.is_recording = False
        
        # Initialize Whisper model
        model_size = config.get("whisper_model_size", "base")
        device = config.get("whisper_device", "cpu")
        compute_type = config.get("whisper_compute_type", "int8")
        
        print(f"Loading Whisper model: {model_size} on {device}...")
        self.whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print("Whisper model loaded successfully!")
    
    def start_recording(self):
        """Start recording audio"""
        self.recording = []
        self.is_recording = True
        
        def audio_callback(indata, frames, time_info, status):
            if status:
                print(f"Audio status: {status}")
            if self.is_recording:
                self.recording.append(indata.copy())
        
        self.stream = sd.InputStream(
            callback=audio_callback,
            channels=self.channels,
            samplerate=self.sample_rate,
            dtype=np.float32
        )
        self.stream.start()
    
    def stop_recording(self) -> Optional[str]:
        """Stop recording and transcribe"""
        self.is_recording = False
        self.stream.stop()
        self.stream.close()
        
        if not self.recording:
            return None
        
        # Concatenate audio chunks
        audio_data = np.concatenate(self.recording, axis=0)
        audio_data = audio_data.flatten()
        
        # Transcribe with Whisper
        segments, info = self.whisper_model.transcribe(
            audio_data,
            language="en",
            beam_size=5
        )
        
        text = " ".join([segment.text for segment in segments])
        return text.strip()


# ============================================================================
# Gemini AI Integration
# ============================================================================

class GeminiAgent:
    """Manages communication with Gemini API"""
    
    def __init__(self, config: Config, fs_tools: FileSystemTools):
        self.config = config
        self.fs_tools = fs_tools
        
        # Configure Gemini
        api_key = config.get("gemini_api_key")
        if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
            raise ValueError("Please set your Gemini API key in config.json")
        
        genai.configure(api_key=api_key)
        
        # Define function declarations for Gemini
        self.tools = [
            {
                "function_declarations": [
                    {
                        "name": "get_file_tree",
                        "description": "Get the file structure of the current project directory",
                        "parameters": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "read_file",
                        "description": "Read the content of a specific file",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Relative path to the file (e.g., 'src/main.py')"
                                }
                            },
                            "required": ["path"]
                        }
                    },
                    {
                        "name": "write_file",
                        "description": "Create or modify a file. IMPORTANT: This will trigger human review before execution.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Relative path to the file (e.g., 'fibonacci.py')"
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Complete file content to write"
                                }
                            },
                            "required": ["path", "content"]
                        }
                    }
                ]
            }
        ]
        
        model_name = config.get("gemini_model", "gemini-1.5-pro")
        self.model = genai.GenerativeModel(
            model_name=model_name,
            tools=self.tools
        )
    
    def process_command(self, user_command: str, log_callback) -> Optional[Dict[str, Any]]:
        """Process user command with Gemini"""
        try:
            system_prompt = self.config.get("system_prompt")
            file_tree = self.fs_tools.get_file_tree()
            
            initial_message = f"""{system_prompt}

Current Project Structure:
{file_tree}

User Command: {user_command}

Analyze this command and use the available tools to complete the task."""
            
            log_callback("🧠 Starting conversation with Gemini...", "ai")
            
            chat = self.model.start_chat()
            response = chat.send_message(initial_message)
            
            # Process function calls
            max_iterations = 10
            iteration = 0
            
            while iteration < max_iterations:
                # Check for function calls
                if not response.candidates[0].content.parts:
                    break
                
                part = response.candidates[0].content.parts[0]
                
                # Handle text response
                if hasattr(part, 'text') and part.text:
                    log_callback(f"💭 {part.text}", "ai")
                
                # Handle function call
                if hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    function_name = fc.name
                    args = dict(fc.args) if fc.args else {}
                    
                    log_callback(f"🔧 Calling: {function_name}({args})", "ai")
                    
                    # Execute function
                    if function_name == "get_file_tree":
                        result = self.fs_tools.get_file_tree()
                        
                    elif function_name == "read_file":
                        result = self.fs_tools.read_file(args.get("path", ""))
                        
                    elif function_name == "write_file":
                        # Return write request for human review
                        write_info = self.fs_tools.prepare_write(
                            args.get("path", ""),
                            args.get("content", "")
                        )
                        return write_info
                    
                    else:
                        result = f"Unknown function: {function_name}"
                    
                    # Send function response back to Gemini
                    response = chat.send_message(
                        genai.protos.Content(
                            parts=[genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=function_name,
                                    response={"result": result}
                                )
                            )]
                        )
                    )
                    
                    iteration += 1
                else:
                    # No more function calls
                    break
            
            log_callback("✅ Task completed", "success")
            return None
            
        except Exception as e:
            log_callback(f"❌ Error: {str(e)}", "error")
            return None


# ============================================================================
# GUI Application
# ============================================================================

class ArchitectGUI:
    """Main GUI application"""
    
    def __init__(self):
        # Load configuration
        self.config = Config()
        
        # Initialize components
        self.fs_tools = FileSystemTools(self.config)
        self.audio_recorder = AudioRecorder(self.config)
        self.gemini_agent = GeminiAgent(self.config, self.fs_tools)
        
        # GUI state
        self.is_recording = False
        self.log_queue = queue.Queue()
        
        # Build GUI
        self.build_gui()
        
        # Start log queue processor
        self.process_log_queue()
    
    def build_gui(self):
        """Build the Tkinter interface"""
        self.root = tk.Tk()
        self.root.title("The Architect v0.2 - Voice-to-Code")
        self.root.geometry("800x600")
        
        theme = self.config.get("gui_theme", {})
        bg_color = theme.get("bg_color", "#1e1e1e")
        fg_color = theme.get("fg_color", "#ffffff")
        
        self.root.configure(bg=bg_color)
        
        # Status label
        self.status_label = tk.Label(
            self.root,
            text="⚪ Idle",
            font=("Arial", 16, "bold"),
            bg=bg_color,
            fg=fg_color
        )
        self.status_label.pack(pady=10)
        
        # Log console
        log_bg = theme.get("log_bg", "#2d2d2d")
        log_fg = theme.get("log_fg", "#ffffff")
        
        self.log_text = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            width=90,
            height=25,
            bg=log_bg,
            fg=log_fg,
            font=("Courier", 10),
            state=tk.DISABLED
        )
        self.log_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        # Configure text tags for colors
        self.log_text.tag_config("user", foreground=theme.get("user_text_color", "#ffeb3b"))
        self.log_text.tag_config("ai", foreground=theme.get("ai_text_color", "#00bcd4"))
        self.log_text.tag_config("success", foreground=theme.get("success_color", "#4caf50"))
        self.log_text.tag_config("error", foreground=theme.get("error_color", "#f44336"))
        
        # Push-to-Talk button
        button_bg = theme.get("button_bg", "#0d47a1")
        button_fg = theme.get("button_fg", "#ffffff")
        button_active_bg = theme.get("button_active_bg", "#1565c0")
        
        self.record_button = tk.Button(
            self.root,
            text="🎤 Push to Talk (Hold SPACE)",
            font=("Arial", 14, "bold"),
            bg=button_bg,
            fg=button_fg,
            activebackground=button_active_bg,
            activeforeground=button_fg,
            height=2,
            command=self.toggle_recording
        )
        self.record_button.pack(pady=10, padx=10, fill=tk.X)
        
        # Keyboard bindings
        self.root.bind('<KeyPress-space>', self.on_space_press)
        self.root.bind('<KeyRelease-space>', self.on_space_release)
        
        # Initial log message
        self.log_message("🚀 The Architect is ready. Hold SPACE to start.", "success")
        self.log_message(f"📂 Working directory: {self.fs_tools.working_dir}", "ai")
    
    def log_message(self, message: str, tag: str = "normal"):
        """Add message to log console"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def set_status(self, text: str, color: str = None):
        """Update status label"""
        self.status_label.config(text=text)
        if color:
            self.status_label.config(fg=color)
    
    def on_space_press(self, event):
        """Handle spacebar press"""
        if not self.is_recording and event.widget == self.root:
            self.start_recording()
    
    def on_space_release(self, event):
        """Handle spacebar release"""
        if self.is_recording and event.widget == self.root:
            self.stop_recording()
    
    def toggle_recording(self):
        """Toggle recording state (for button click)"""
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()
    
    def start_recording(self):
        """Start audio recording"""
        self.is_recording = True
        self.set_status("🔴 Recording...", "#f44336")
        self.record_button.config(text="🔴 Recording... (Release SPACE)")
        self.audio_recorder.start_recording()
        self.log_message("🎤 Listening...", "user")
    
    def stop_recording(self):
        """Stop recording and process"""
        self.is_recording = False
        self.set_status("🟡 Thinking...", "#ffeb3b")
        self.record_button.config(text="🎤 Push to Talk (Hold SPACE)")
        
        # Process in background thread
        threading.Thread(target=self.process_audio, daemon=True).start()
    
    def process_audio(self):
        """Process recorded audio (runs in background)"""
        try:
            # Transcribe
            text = self.audio_recorder.stop_recording()
            
            if not text:
                self.log_queue.put(("❌ No speech detected", "error"))
                self.log_queue.put(("status", "⚪ Idle", None))
                return
            
            self.log_queue.put((f"📝 You said: {text}", "user"))
            
            # Send to Gemini
            write_request = self.gemini_agent.process_command(
                text,
                lambda msg, tag: self.log_queue.put((msg, tag))
            )
            
            # Handle write request
            if write_request and write_request.get("success"):
                self.log_queue.put(("review", write_request))
            
            self.log_queue.put(("status", "⚪ Idle", None))
            
        except Exception as e:
            self.log_queue.put((f"❌ Error: {str(e)}", "error"))
            self.log_queue.put(("status", "⚪ Idle", None))
    
    def process_log_queue(self):
        """Process messages from background threads"""
        try:
            while True:
                message, tag = self.log_queue.get_nowait()
                
                if message == "status":
                    self.set_status(tag)
                elif message == "review":
                    self.show_review_popup(tag)
                else:
                    self.log_message(message, tag)
        except queue.Empty:
            pass
        
        self.root.after(100, self.process_log_queue)
    
    def show_review_popup(self, write_info: Dict[str, Any]):
        """Show code review popup (The Gatekeeper)"""
        popup = tk.Toplevel(self.root)
        popup.title("🔒 The Gatekeeper - Review Changes")
        popup.geometry("800x600")
        popup.configure(bg=self.config.get("gui_theme", {}).get("bg_color", "#1e1e1e"))
        popup.grab_set()  # Make modal
        
        # Header
        action = "Create New File" if write_info["is_new"] else "Modify Existing File"
        header = tk.Label(
            popup,
            text=f"⚠️ {action}: {write_info['relative_path']}",
            font=("Arial", 14, "bold"),
            bg=self.config.get("gui_theme", {}).get("bg_color", "#1e1e1e"),
            fg="#ffeb3b"
        )
        header.pack(pady=10)
        
        if write_info["needs_backup"]:
            backup_label = tk.Label(
                popup,
                text=f"ℹ️ Original will be backed up with '{self.config.get('backup_extension')}' extension",
                font=("Arial", 10),
                bg=self.config.get("gui_theme", {}).get("bg_color", "#1e1e1e"),
                fg="#00bcd4"
            )
            backup_label.pack()
        
        # Code preview
        code_text = scrolledtext.ScrolledText(
            popup,
            wrap=tk.NONE,
            width=90,
            height=25,
            bg=self.config.get("gui_theme", {}).get("log_bg", "#2d2d2d"),
            fg=self.config.get("gui_theme", {}).get("log_fg", "#ffffff"),
            font=("Courier", 10)
        )
        code_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        code_text.insert(tk.END, write_info["content"])
        code_text.config(state=tk.DISABLED)
        
        # Button frame
        button_frame = tk.Frame(popup, bg=self.config.get("gui_theme", {}).get("bg_color", "#1e1e1e"))
        button_frame.pack(pady=10)
        
        def apply_changes():
            result = self.fs_tools.execute_write(
                write_info["relative_path"],
                write_info["content"]
            )
            self.log_message(result, "success" if "SUCCESS" in result else "error")
            popup.destroy()
        
        def discard_changes():
            self.log_message("❌ Changes discarded by user", "error")
            popup.destroy()
        
        apply_btn = tk.Button(
            button_frame,
            text="✅ Apply Changes",
            font=("Arial", 12, "bold"),
            bg="#4caf50",
            fg="#ffffff",
            command=apply_changes,
            width=20,
            height=2
        )
        apply_btn.pack(side=tk.LEFT, padx=10)
        
        discard_btn = tk.Button(
            button_frame,
            text="❌ Discard",
            font=("Arial", 12, "bold"),
            bg="#f44336",
            fg="#ffffff",
            command=discard_changes,
            width=20,
            height=2
        )
        discard_btn.pack(side=tk.LEFT, padx=10)
    
    def run(self):
        """Start the application"""
        self.root.mainloop()


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    try:
        app = ArchitectGUI()
        app.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        messagebox.showerror("Fatal Error", str(e))