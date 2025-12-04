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
from typing import Optional, Dict, Any, List, Union
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
                action = "Updated"
            else:
                action = "Created"
            
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return f"SUCCESS: {action} {path}"
        except Exception as e:
            return f"ERROR: {str(e)}"


# ============================================================================
# Audio & Speech Recognition
# ============================================================================

class AudioRecorder:
    """Handles audio recording and transcription with multiple STT providers"""
    
    def __init__(self, config: Config):
        self.config = config
        self.sample_rate = config.get("audio_sample_rate", 16000)
        self.channels = config.get("audio_channels", 1)
        self.recording = []
        self.is_recording = False
        self.stt_provider = config.get("stt_provider", "whisper").lower()
        
        # Initialize STT provider
        if self.stt_provider == "whisper":
            self._init_whisper()
        elif self.stt_provider == "gemini":
            self._init_gemini_stt()
        else:
            raise ValueError(f"Unknown STT provider: {self.stt_provider}")
    
    def _init_whisper(self):
        """Initialize Whisper model (local or custom)"""
        custom_model = self.config.get("whisper_custom_model")
        
        if custom_model:
            # Use custom HuggingFace model
            model_name = custom_model
            print(f"Loading custom Whisper model: {model_name}...")
        else:
            # Use standard Whisper model
            model_name = self.config.get("whisper_model_size", "base")
            print(f"Loading Whisper model: {model_name}...")
        
        device = self.config.get("whisper_device", "cpu")
        compute_type = self.config.get("whisper_compute_type", "int8")
        
        try:
            self.whisper_model = WhisperModel(
                model_name, 
                device=device, 
                compute_type=compute_type
            )
            print(f"✓ Whisper model loaded successfully on {device}!")
        except Exception as e:
            print(f"✗ Error loading Whisper model: {e}")
            print("Tip: For custom models, ensure they're compatible with faster-whisper")
            raise
    
    def _init_gemini_stt(self):
        """Initialize Gemini STT"""
        api_key = self.config.get("gemini_api_key")
        if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
            raise ValueError("Please set your Gemini API key in config.json")
        
        genai.configure(api_key=api_key)
        model_name = self.config.get("gemini_stt_model", "gemini-1.5-flash")
        self.gemini_stt_model = genai.GenerativeModel(model_name)
        print(f"✓ Gemini STT initialized with {model_name}!")
    
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
        
        # Transcribe based on provider
        if self.stt_provider == "whisper":
            return self._transcribe_whisper(audio_data)
        elif self.stt_provider == "gemini":
            return self._transcribe_gemini(audio_data)
    
    def _transcribe_whisper(self, audio_data: np.ndarray) -> str:
        """Transcribe using Whisper"""
        try:
            segments, info = self.whisper_model.transcribe(
                audio_data,
                language="en",
                beam_size=5
            )
            
            text = " ".join([segment.text for segment in segments])
            return text.strip()
        except Exception as e:
            print(f"Whisper transcription error: {e}")
            return None
    
    def _transcribe_gemini(self, audio_data: np.ndarray) -> str:
        """Transcribe using Gemini API"""
        try:
            import wave
            import tempfile
            
            # Convert float32 audio to int16 WAV format
            audio_int16 = (audio_data * 32767).astype(np.int16)
            
            # Create temporary WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
                with wave.open(temp_wav.name, 'wb') as wav_file:
                    wav_file.setnchannels(self.channels)
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(audio_int16.tobytes())
                
                temp_path = temp_wav.name
            
            # Upload audio to Gemini
            audio_file = genai.upload_file(path=temp_path)
            
            # Get transcription
            language = self.config.get("gemini_stt_language", "en")
            prompt = f"Transcribe this audio to text. Language: {language}. Return only the transcribed text, nothing else."
            
            response = self.gemini_stt_model.generate_content([prompt, audio_file])
            
            # Clean up
            import os
            os.unlink(temp_path)
            genai.delete_file(audio_file.name)
            
            return response.text.strip()
            
        except Exception as e:
            print(f"Gemini STT error: {e}")
            return None


# ============================================================================
# Gemini AI Integration
# ============================================================================

class GeminiAgent:
    """Manages communication with Gemini API (Persistent Session)"""
    
    def __init__(self, config: Config, fs_tools: FileSystemTools):
        self.config = config
        self.fs_tools = fs_tools
        self.chat_session = None  # Store the session here
        
        # Configure Gemini
        api_key = config.get("gemini_api_key")
        if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
            raise ValueError("Please set your Gemini API key in config.json")
        
        genai.configure(api_key=api_key)
        
        # Define function declarations (Same as your original code)
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
                                "path": {"type": "string", "description": "Relative path to the file"}
                            },
                            "required": ["path"]
                        }
                    },
                    {
                        "name": "write_file",
                        "description": "Create or modify a file. The AI pauses here for human review.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Relative path to the file"},
                                "content": {"type": "string", "description": "Complete file content to write"}
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

        # Initialize the persistent session immediately
        self._start_new_session()

    def _start_new_session(self):
        """Internal method to start/reset the chat session"""
        system_prompt = self.config.get("system_prompt")
        file_tree = self.fs_tools.get_file_tree()
        
        # We assume the first message sets the context
        self.chat_session = self.model.start_chat(history=[
            {
                "role": "user",
                "parts": [f"{system_prompt}\n\nCurrent Project Structure:\n{file_tree}"]
            },
            {
                "role": "model",
                "parts": ["Understood. I am The Architect. Ready to analyze code and file structures."]
            }
        ])

    def process_command(self, user_input: str, log_callback) -> Optional[List[Dict[str, Any]]]:
        """Process a message (User voice OR System feedback)"""
        try:
            # Refresh file tree context periodically or on request (simplified here)
            # Send message to EXISTING session
            response = self.chat_session.send_message(user_input)
            return self._handle_model_response(response, log_callback)
            
        except Exception as e:
            log_callback(f"❌ Error communicating with Gemini: {str(e)}", "error")
            return None

    def _handle_model_response(self, response, log_callback):
        """Internal loop to handle function calls until a write occurs or completion"""
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            # Check for function calls in the current response
            if not response.candidates or not response.candidates[0].content.parts:
                break

            function_responses = []
            write_requests = []
            has_function_calls = False

            for part in response.candidates[0].content.parts:
                # 1. Handle Text
                if hasattr(part, 'text') and part.text:
                    log_callback(f"💭 {part.text}", "ai")

                # 2. Handle Function Calls
                if hasattr(part, 'function_call') and part.function_call:
                    has_function_calls = True
                    fc = part.function_call
                    function_name = fc.name
                    args = dict(fc.args)
                    
                    log_callback(f"🔧 Calling: {function_name}", "ai")

                    if function_name == "get_file_tree":
                        result = self.fs_tools.get_file_tree()
                        function_responses.append({"name": function_name, "response": {"result": result}})
                    
                    elif function_name == "read_file":
                        result = self.fs_tools.read_file(args.get("path", ""))
                        function_responses.append({"name": function_name, "response": {"result": result}})
                    
                    elif function_name == "write_file":
                        # STOP THE LOOP HERE. Return to GUI for review.
                        # We do NOT execute this yet.
                        write_info = self.fs_tools.prepare_write(args.get("path", ""), args.get("content", ""))
                        if write_info.get("success"):
                            write_requests.append(write_info)
                        else:
                            # Auto-fail if permission denied, etc.
                            function_responses.append({
                                "name": function_name, 
                                "response": {"error": write_info.get("error")}
                            })

            # If we have write requests, we must PAUSE execution and return to GUI
            if write_requests:
                return write_requests

            # If we have other function results (read/tree), send them back immediately and loop
            if has_function_calls and function_responses:
                response = self.chat_session.send_message(
                    genai.protos.Content(
                        parts=[
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=fr["name"],
                                    response=fr["response"]
                                )
                            ) for fr in function_responses
                        ]
                    )
                )
                iteration += 1
            else:
                # No function calls, just text, we are done
                break
        
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
        self.log_text.tag_config("debug", foreground=theme.get("debug_color", "#9c27b0"))
        
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
            text = self.audio_recorder.stop_recording()
            if not text:
                self.log_queue.put(("❌ No speech detected", "error"))
                self.log_queue.put(("status_update", "⚪ Idle"))
                return
            
            self.log_queue.put((f"📝 You said: {text}", "user"))
            
            # Start the chain
            self.continue_conversation(text)

        except Exception as e:
            self.log_queue.put((f"❌ Error: {str(e)}", "error"))
            self.log_queue.put(("status_update", "⚪ Idle"))
    
    def continue_conversation(self, message: str):
        """Helper to send message to Agent and handle the response loop"""
        # Run in a thread to avoid freezing GUI
        def _run():
            self.log_queue.put(("status_update", "⚡ Thinking..."))
            
            # Send to Gemini (Persistent Session)
            write_requests = self.gemini_agent.process_command(
                message,
                lambda msg, tag: self.log_queue.put((msg, tag))
            )
            
            # If Gemini wants to write files, trigger the popup
            if write_requests:
                # We only handle the first one in the batch for safety, 
                # or loop through them. Simplest is one by one.
                for write_info in write_requests:
                    self.log_queue.put(("review", write_info))
            else:
                self.log_queue.put(("status_update", "⚪ Idle"))

        threading.Thread(target=_run, daemon=True).start()

    def process_log_queue(self):
        """Process messages from background threads"""
        try:
            while True:
                item = self.log_queue.get_nowait()
                
                # Handle different message formats
                if isinstance(item, tuple) and len(item) == 2:
                    message, tag = item
                    
                    if message == "status_update":
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
            # 1. Execute the write
            result = self.fs_tools.execute_write(
                write_info["relative_path"],
                write_info["content"]
            )
            self.log_message(result, "success" if "SUCCESS" in result else "error")
            popup.destroy()
            
            # 2. CRITICAL FIX: Tell Gemini the file is done!
            # We send a "System Message" back to the agent to trigger the next step.
            system_msg = f"System: Successfully created {write_info['relative_path']}. content written. Proceed with the next step or file if any."
            self.continue_conversation(system_msg)

        def discard_changes():
            self.log_message(f"❌ Skipped {write_info['relative_path']}", "error")
            popup.destroy()
            
            # Tell Gemini we skipped it
            system_msg = f"System: User skipped creating {write_info['relative_path']}. Stop generating files."
            self.continue_conversation(system_msg)
        
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