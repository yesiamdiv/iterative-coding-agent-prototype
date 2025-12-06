import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, filedialog, ttk
import threading
import queue
from pathlib import Path
from typing import Optional, Dict, Any, List, Union, Tuple
import time
from agent import Agent
from audio_recorder import AudioRecorder
from file_system_tools import FileSystemTools
from config import Config


# ============================================================================
# GUI Application
# ============================================================================

class AppGUI:
    """Main GUI application"""
    
    def __init__(self):
        # Load configuration
        self.config = Config()
        
        # GUI state
        self.is_recording = False
        self.is_feedback_recording = False
        self.log_queue = queue.Queue()
        self.pending_actions = []
        self.review_window = None
        self.settings_window = None
        
        # Initialize components
        self.fs_tools = FileSystemTools(self.config)
        self.audio_recorder = AudioRecorder(self.config)
        self.agent = Agent(
            config=self.config,
            fs_tools=self.fs_tools,
            log_callback=self.update_log_display,
            action_callback=self.show_action_review_popup,
            status_callback=self.handle_agent_status
        )
        
        # Build GUI
        self.build_gui()
        
        # Start log queue processor
        self.process_log_queue()
    
    def build_gui(self):
        """Build the Tkinter interface"""
        self.root = tk.Tk()
        self.root.title("The Architect v0.3 - Voice-to-Code")
        self.root.geometry("800x600")

        # --- Tkinter Variables ---
        self.debug_var = tk.BooleanVar(value=self.config.get("enable_debug_logging", "False").lower() == "true")
        self.persistent_session_var = tk.BooleanVar(value=self.config.get("persistent_session", "False").lower() == "true")

        # --- Menu Bar ---
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Change Working Directory...", command=self._change_working_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        # Settings Menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_checkbutton(label="Enable Debug Logging", variable=self.debug_var, command=self._toggle_debug_logging)
        settings_menu.add_checkbutton(label="Persistent Session", variable=self.persistent_session_var, command=self._toggle_persistent_session)
        settings_menu.add_separator()
        settings_menu.add_command(label="Advanced Settings...", command=self._open_settings_window)
        
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
        self.log_text.tag_config("info", foreground=theme.get("success_color", "#4caf50"))
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
        self.log_message("🚀 The Architect is ready. Hold SPACE to start.", "info")
        self.log_message(f"📂 Working directory: {self.fs_tools.working_dir}", "ai")
    
    # --- Agent Callback Implementations ---

    def update_log_display(self, message: str, level: str):
        """Callback for the Agent to send log messages."""
        self.log_queue.put(("log", (message, level)))

    def show_action_review_popup(self, action_details: Dict[str, Any], id_bundle: tuple):
        """Callback for the Agent to request user approval for an action."""
        # This is called from a background thread, so we schedule the GUI update
        self.log_queue.put(("action", (action_details, id_bundle)))

    def handle_agent_status(self, status: str):
        """Callback for the Agent to signal task completion or error."""
        self.log_queue.put(("agent_status", status))

    # --- Settings and Configuration ---

    def _change_working_directory(self):
        """Opens a dialog to select a new working directory."""
        new_dir = filedialog.askdirectory(
            title="Select Project Folder",
            initialdir=self.fs_tools.working_dir
        )
        if new_dir:
            self.config.set("working_directory", new_dir)
            
            # Re-initialize components that depend on the working directory
            self.fs_tools = FileSystemTools(self.config)
            self.agent = Agent(
                config=self.config,
                fs_tools=self.fs_tools,
                log_callback=self.update_log_display,
                action_callback=self.show_action_review_popup,
                status_callback=self.handle_agent_status
            )
            # Update debug/persistent states on the new agent instance
            self.agent.debug_enabled = self.debug_var.get()
            self.agent.persistent_session_enabled = self.persistent_session_var.get()
            
            self.log_message(f"🚀 Project directory changed. Restarting agent...", "info")
            self.log_message(f"📂 New working directory: {self.fs_tools.working_dir}", "ai")

    def _toggle_debug_logging(self):
        """Toggles debug logging on/off."""
        is_enabled = self.debug_var.get()
        self.config.set("enable_debug_logging", str(is_enabled))
        if self.agent:
            self.agent.debug_enabled = is_enabled
        self.log_message(f"Debug logging {'enabled' if is_enabled else 'disabled'}.", "info")

    def _toggle_persistent_session(self):
        """Toggles persistent session on/off."""
        is_enabled = self.persistent_session_var.get()
        self.config.set("persistent_session", str(is_enabled))
        if self.agent:
            self.agent.persistent_session_enabled = is_enabled
        self.log_message(f"Persistent session {'enabled' if is_enabled else 'disabled'}. A restart may be required for full effect.", "info")

    def _open_settings_window(self):
        """Creates and manages the advanced settings window."""
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Advanced Settings")
        self.settings_window.geometry("600x650")

        theme = self.config.get("gui_theme", {})
        bg_color = theme.get("bg_color", "#1e1e1e")
        fg_color = theme.get("fg_color", "#ffffff")
        entry_bg = theme.get("log_bg", "#2d2d2d")
        
        self.settings_window.configure(bg=bg_color)

        main_frame = tk.Frame(self.settings_window, bg=bg_color, padx=15, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Helper to create rows
        def create_setting_row(parent, label_text, row):
            label = tk.Label(parent, text=label_text, bg=bg_color, fg=fg_color, anchor="w")
            label.grid(row=row, column=0, sticky="w", pady=(0, 5))
            frame = tk.Frame(parent, bg=bg_color)
            frame.grid(row=row, column=1, sticky="ew", pady=(0, 5))
            return frame

        # --- Settings Widgets ---
        # STT Provider
        stt_frame = create_setting_row(main_frame, "STT Provider:", 0)
        stt_provider_var = tk.StringVar(value=self.config.get("stt_provider"))
        stt_options = ["gemini", "whisper"]
        stt_dropdown = ttk.Combobox(stt_frame, textvariable=stt_provider_var, values=stt_options, state="readonly")
        stt_dropdown.pack(fill=tk.X)

        # Agent Model
        agent_model_frame = create_setting_row(main_frame, "Agent Model:", 1)
        agent_model_var = tk.StringVar(value=self.config.get("gemini_model"))
        agent_model_entry = tk.Entry(agent_model_frame, textvariable=agent_model_var, bg=entry_bg, fg=fg_color, insertbackground=fg_color)
        agent_model_entry.pack(fill=tk.X)

        # STT Model
        stt_model_frame = create_setting_row(main_frame, "Gemini STT Model:", 2)
        stt_model_var = tk.StringVar(value=self.config.get("gemini_stt_model"))
        stt_model_entry = tk.Entry(stt_model_frame, textvariable=stt_model_var, bg=entry_bg, fg=fg_color, insertbackground=fg_color)
        stt_model_entry.pack(fill=tk.X)

        # System Prompt
        tk.Label(main_frame, text="System Prompt:", bg=bg_color, fg=fg_color, anchor="w").grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 5))
        prompt_text = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, height=15, bg=entry_bg, fg=fg_color, font=("Courier", 10), insertbackground=fg_color)
        prompt_text.grid(row=4, column=0, columnspan=2, sticky="nsew")
        prompt_text.insert(tk.END, self.config.get("system_prompt"))
        
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(4, weight=1)

        # --- Save/Cancel Buttons ---
        def save_settings():
            self.config.set("stt_provider", stt_provider_var.get())
            self.config.set("gemini_model", agent_model_var.get())
            self.config.set("gemini_stt_model", stt_model_var.get())
            self.config.set("system_prompt", prompt_text.get("1.0", tk.END).strip())
            
            self.log_message("Settings saved. A restart is recommended for all changes to take effect.", "info")
            # Re-initialize agent with new models/prompts
            self.agent = Agent(
                config=self.config,
                fs_tools=self.fs_tools,
                log_callback=self.update_log_display,
                action_callback=self.show_action_review_popup,
                status_callback=self.handle_agent_status
            )
            self.settings_window.destroy()

        button_frame = tk.Frame(main_frame, bg=bg_color)
        button_frame.grid(row=5, column=0, columnspan=2, pady=(10, 0), sticky="e")
        
        save_button = tk.Button(button_frame, text="Save & Close", command=save_settings, bg="#4caf50", fg="white")
        save_button.pack(side=tk.RIGHT, padx=5)
        
        cancel_button = tk.Button(button_frame, text="Cancel", command=self.settings_window.destroy, bg="#f44336", fg="white")
        cancel_button.pack(side=tk.RIGHT)

    # --- Core GUI Logic ---

    def process_log_queue(self):
        """Process messages from background threads to safely update the GUI."""
        try:
            while True:
                msg_type, data = self.log_queue.get_nowait()
                
                if msg_type == "log":
                    message, level = data
                    self.log_message(message, level)
                elif msg_type == "action":
                    action_details, id_bundle = data
                    self._add_action_to_review_ui(action_details, id_bundle)
                elif msg_type == "status_update":
                    self.set_status(data)
                elif msg_type == "agent_status":
                    if data in ["completed", "error"]:
                        self.set_status("⚪ Idle")
                elif msg_type == "feedback_text":
                    if self.review_window and self.review_window.winfo_exists():
                        self.feedback_entry.delete(0, tk.END)
                        self.feedback_entry.insert(0, data)


        except queue.Empty:
            pass
        
        self.root.after(100, self.process_log_queue)

    def log_message(self, message: str, tag: str = "info"):
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
    
    # --- User Interaction Handlers ---

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
        if self.is_feedback_recording:
            return # Don't allow main recording if feedback recording is active
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
        """Process recorded audio and pass prompt to the Agent."""
        try:
            text = self.audio_recorder.stop_recording()
            
            if not text:
                self.log_queue.put(("log", ("❌ No speech detected", "error")))
                self.log_queue.put(("status_update", "⚪ Idle"))
                return
            
            self.log_queue.put(("log", (f"📝 You said: {text}", "user")))
            
            # This is the entry point to start a new task with the Agent
            if self.agent:
                self.agent.process_prompt(text)
            else:
                self.log_queue.put(("log", ("❌ Agent not initialized!", "error")))
                self.log_queue.put(("status_update", "⚪ Idle"))

        except Exception as e:
            self.log_queue.put(("log", (f"❌ Audio processing error: {str(e)}", "error")))
            self.log_queue.put(("status_update", "⚪ Idle"))

    # --- Action Review UI ---

    def _add_action_to_review_ui(self, action_details: Dict[str, Any], id_bundle: tuple):
        """Adds a new action to the review window, creating it if necessary."""
        if not self.review_window or not self.review_window.winfo_exists():
            self._create_review_window()

        self.pending_actions.append({'details': action_details, 'id': id_bundle})
        
        path = action_details.get('path', 'Unknown Path')
        is_new = action_details.get('is_new_file', False)
        prefix = "✨ New: " if is_new else "📝 Mod: "
        
        self.review_listbox.insert(tk.END, f"{prefix}{path}")

        # If nothing is selected, select the first item by default.
        if not self.review_listbox.curselection():
            self.review_listbox.selection_set(0)
            self._on_review_select()
        
        self.review_window.deiconify() # Show window if it was minimized/hidden
        self.review_window.lift() # Bring to front

    def _create_review_window(self):
        """Creates the persistent Toplevel window for reviewing actions."""
        self.review_window = tk.Toplevel(self.root)
        self.review_window.title("🔒 The Gatekeeper - Action Review")
        self.review_window.geometry("900x700")

        theme = self.config.get("gui_theme", {})
        bg_color = theme.get("bg_color", "#1e1e1e")
        self.review_window.configure(bg=bg_color)
        
        paned_window = tk.PanedWindow(self.review_window, orient=tk.HORIZONTAL, bg=bg_color, sashrelief=tk.RAISED)
        paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left Panel (File List)
        left_frame = tk.Frame(paned_window, bg=bg_color)
        tk.Label(left_frame, text="Pending Actions:", bg=bg_color, fg="white", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 5))
        self.review_listbox = tk.Listbox(left_frame, bg="#2d2d2d", fg="white", selectbackground="#0d47a1", exportselection=False)
        self.review_listbox.pack(fill=tk.BOTH, expand=True)
        paned_window.add(left_frame, width=300)

        # Right Panel (Code Diff/Preview)
        right_frame = tk.Frame(paned_window, bg=bg_color)
        self.preview_label = tk.Label(right_frame, text="Select an action to preview", bg=bg_color, fg="#ffeb3b", font=("Arial", 12, "bold"))
        self.preview_label.pack(pady=5)
        self.code_preview = scrolledtext.ScrolledText(right_frame, bg="#2d2d2d", fg="white", font=("Courier", 10), state=tk.DISABLED)
        self.code_preview.pack(fill=tk.BOTH, expand=True)
        paned_window.add(right_frame)

        self.review_listbox.bind('<<ListboxSelect>>', self._on_review_select)
        
        # Bottom Panel (Feedback & Buttons)
        bottom_frame = tk.Frame(self.review_window, bg=bg_color)
        bottom_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        tk.Label(bottom_frame, text="Rejection Feedback (Optional):", bg=bg_color, fg="white").pack(side=tk.LEFT, padx=(0, 10))
        self.feedback_entry = tk.Entry(bottom_frame, bg="#2d2d2d", fg="white", width=50)
        self.feedback_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.feedback_record_button = tk.Button(bottom_frame, text="🎤", command=self.toggle_feedback_recording, bg="#3c3c3c", fg="white", width=4)
        self.feedback_record_button.pack(side=tk.LEFT, padx=5)

        btn_accept = tk.Button(bottom_frame, text="✅ Accept", command=self._handle_accept, bg="#4caf50", fg="white")
        btn_accept.pack(side=tk.RIGHT, padx=10)
        btn_reject = tk.Button(bottom_frame, text="❌ Reject", command=self._handle_reject, bg="#f44336", fg="white")
        btn_reject.pack(side=tk.RIGHT)

        self.review_window.protocol("WM_DELETE_WINDOW", self._on_review_window_close)


    def _on_review_select(self, event=None):
        """Handles selection change in the review listbox."""
        selection_indices = self.review_listbox.curselection()
        if not selection_indices:
            self.code_preview.config(state=tk.NORMAL)
            self.code_preview.delete("1.0", tk.END)
            self.code_preview.insert(tk.END, 'No content to display.')
            self.code_preview.config(state=tk.DISABLED)
            return
        
        index = selection_indices[0]
        action = self.pending_actions[index]
        details = action['details']
        
        path = details.get('path', 'Unknown')
        diff_content = details.get('diff', details.get('content', 'No content to display.'))

        self.preview_label.config(text=f"Diff for: {path}")
        self.code_preview.config(state=tk.NORMAL)
        self.code_preview.delete("1.0", tk.END)
        self.code_preview.insert(tk.END, diff_content)
        self.code_preview.config(state=tk.DISABLED)

    def _handle_accept(self):
        """Handles the 'Accept' button click for the selected action."""
        self._send_action_result(approved=True)

    def _handle_reject(self):
        """Handles the 'Reject' button click for the selected action."""
        self._send_action_result(approved=False)

    def _send_action_result(self, approved: bool):
        """Sends the user's decision back to the agent for the selected action."""
        selection_indices = self.review_listbox.curselection()
        if not selection_indices:
            self.log_message("No action selected to respond to.", "error")
            return
            
        index = selection_indices[0]
        action_to_process = self.pending_actions.pop(index)
        self.review_listbox.delete(index)

        id_bundle = action_to_process['id']
        result = {'approved': approved}
        
        if not approved:
            feedback = self.feedback_entry.get()
            if feedback:
                result['feedback'] = feedback
        
        if self.agent:
            self.agent.handle_action_result(id_bundle, result)
            self.log_message(f"Responded {'ACCEPTED' if approved else 'REJECTED'} for {action_to_process['details']['path']}", "info")
        
        self.feedback_entry.delete(0, tk.END) # Clear feedback entry
        
        if self.review_listbox.size() == 0:
            self.review_window.withdraw() # Hide window if empty
        else:
            # Select the next item if possible
            if self.review_listbox.size() > index:
                self.review_listbox.selection_set(index)
            elif self.review_listbox.size() > 0:
                self.review_listbox.selection_set(self.review_listbox.size() - 1)
            self._on_review_select()

    def _on_review_window_close(self):
        """Handle the closing of the review window."""
        if self.is_feedback_recording:
            # Stop recording but discard the result
            self.is_feedback_recording = False
            self.audio_recorder.stop_recording() # Just call to stop recording
            self.record_button.config(state=tk.NORMAL) # Re-enable main button
            self.log_message("Feedback recording cancelled.", "info")
        self.review_window.withdraw()

    def toggle_feedback_recording(self):
        """Toggle feedback recording state."""
        if self.is_feedback_recording:
            self.stop_feedback_recording()
        else:
            self.start_feedback_recording()

    def start_feedback_recording(self):
        """Start audio recording for feedback."""
        if self.is_recording:
            messagebox.showwarning("Busy", "Main recording is already in progress.")
            return
        
        self.is_feedback_recording = True
        self.feedback_record_button.config(text="...")
        self.record_button.config(state=tk.DISABLED) # Disable main button
        self.audio_recorder.start_recording()
        self.log_message("🎤 Listening for feedback...", "user")

    def stop_feedback_recording(self):
        """Stop feedback recording and process."""
        self.is_feedback_recording = False
        self.feedback_record_button.config(text="🎤")
        self.record_button.config(state=tk.NORMAL) # Re-enable main button
        
        # Process in background thread to not freeze GUI
        threading.Thread(target=self.process_feedback_audio, daemon=True).start()

    def process_feedback_audio(self):
        """Process recorded audio for feedback and update the entry."""
        try:
            text = self.audio_recorder.stop_recording()
            
            if text:
                # Send text to be inserted in the entry via the main thread queue
                self.log_queue.put(("feedback_text", text))
            else:
                self.log_queue.put(("log", ("❌ No speech detected for feedback.", "error")))

        except Exception as e:
            self.log_queue.put(("log", (f"❌ Feedback audio error: {str(e)}", "error")))

    def run(self):
        """Start the application"""
        self.root.mainloop()

