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
        self.ignore_settings_window = None
        self.current_file_tree = ""
        
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
        
        # Fetch initial file tree
        self.update_file_tree()
    
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
        file_menu.add_command(label="Ignore Files/Folders...", command=self._open_ignore_settings_window) # Added menu item
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
        
        # Input area for text
        input_frame = tk.Frame(self.root, bg=bg_color)
        input_frame.pack(pady=5, padx=10, fill=tk.X)

        self.text_input = tk.Entry(input_frame, font=("Arial", 12), bg=log_bg, fg=log_fg, insertbackground=fg_color)
        self.text_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.text_input.bind("<Return>", self.send_text_input) # Bind Enter key

        self.send_button = tk.Button(
            input_frame,
            text="Send",
            command=self.send_text_input,
            font=("Arial", 10, "bold"),
            bg=theme.get("button_bg", "#0d47a1"),
            fg=theme.get("button_fg", "#ffffff")
        )
        self.send_button.pack(side=tk.LEFT)

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
        
        # Initial log message
        self.log_message("🚀 The Architect is ready. Hold SPACE or use the text input to start.", "info")
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
            # Update FileSystemTools first to load new ignored files
            self.fs_tools.update_working_dir(new_dir)
            
            # Re-initialize agent with the updated FileSystemTools
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
            
            self.log_message(f"🚀 Project directory changed.", "info")
            self.log_message(f"📂 New working directory: {self.fs_tools.working_dir}", "ai")
            
            # Update the file tree after changing directory
            self.update_file_tree()

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
        
        # Ignored Files/Folders (Global)
        tk.Label(main_frame, text="Global Ignored Files/Folders:", bg=bg_color, fg=fg_color, anchor="w").grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 5))
        ignored_frame = tk.Frame(main_frame, bg=bg_color)
        ignored_frame.grid(row=6, column=0, columnspan=2, sticky="nsew")
        ignored_frame.grid_columnconfigure(0, weight=1)

        self.ignored_listbox = tk.Listbox(ignored_frame, selectmode=tk.EXTENDED, height=10, bg=entry_bg, fg=fg_color)
        self.ignored_listbox.grid(row=0, column=0, sticky="nsew")
        # Populate with global ignored folders
        for item in self.config.get("ignored_folders", []):
            self.ignored_listbox.insert(tk.END, item)

        ignored_buttons_frame = tk.Frame(ignored_frame, bg=bg_color)
        ignored_buttons_frame.grid(row=0, column=1, sticky="ns", padx=(10, 0))

        def add_ignored_item():
            item = simpledialog.askstring("Add Ignored Item", "Enter file or folder name to ignore:", parent=self.settings_window)
            if item and item not in self.config.get("ignored_folders", []):
                self.config.get("ignored_folders", []).append(item)
                self.ignored_listbox.insert(tk.END, item)
                self.config.set("ignored_folders", self.config.get("ignored_folders", []))

        def remove_ignored_item():
            selected_indices = self.ignored_listbox.curselection()
            if not selected_indices:
                return
            
            for index in sorted(selected_indices, reverse=True):
                item = self.ignored_listbox.get(index)
                self.ignored_listbox.delete(index)
                if item in self.config.get("ignored_folders", []):
                    self.config.get("ignored_folders", []).remove(item)
            self.config.set("ignored_folders", self.config.get("ignored_folders", []))

        tk.Button(ignored_buttons_frame, text="+ Add", command=add_ignored_item, bg="#0d47a1", fg="white").pack(fill=tk.X, pady=2)
        tk.Button(ignored_buttons_frame, text="- Remove", command=remove_ignored_item, bg="#f44336", fg="white").pack(fill=tk.X, pady=2)

        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(4, weight=1)
        main_frame.grid_rowconfigure(6, weight=1)

        # --- Save/Cancel Buttons ---
        def save_settings():
            self.config.set("stt_provider", stt_provider_var.get())
            self.config.set("gemini_model", agent_model_var.get())
            self.config.set("gemini_stt_model", stt_model_var.get())
            self.config.set("system_prompt", prompt_text.get("1.0", tk.END).strip())
            # Ignored folders are updated directly when added/removed
            
            self.log_message("Settings saved. A restart is recommended for some changes to take effect.", "info")
            # Re-initialize agent with new models/prompts if necessary
            self.agent = Agent(
                config=self.config,
                fs_tools=self.fs_tools,
                log_callback=self.update_log_display,
                action_callback=self.show_action_review_popup,
                status_callback=self.handle_agent_status
            )
            self.settings_window.destroy()

        button_frame = tk.Frame(main_frame, bg=bg_color)
        button_frame.grid(row=7, column=0, columnspan=2, pady=(10, 0), sticky="e")
        
        save_button = tk.Button(button_frame, text="Save & Close", command=save_settings, bg="#4caf50", fg="white")
        save_button.pack(side=tk.RIGHT, padx=5)
        
        cancel_button = tk.Button(button_frame, text="Cancel", command=self.settings_window.destroy, bg="#f44336", fg="white")
        cancel_button.pack(side=tk.RIGHT)

    # --- Ignore Settings Window ---
    def _open_ignore_settings_window(self):
        """Opens a window to manage ignored files/folders for the current project."""
        if self.ignore_settings_window and self.ignore_settings_window.winfo_exists():
            self.ignore_settings_window.lift()
            return

        self.ignore_settings_window = tk.Toplevel(self.root)
        self.ignore_settings_window.title(f"Ignore Settings for: {self.fs_tools.working_dir.name}")
        self.ignore_settings_window.geometry("500x600") # Increased height slightly

        theme = self.config.get("gui_theme", {})
        bg_color = theme.get("bg_color", "#1e1e1e")
        fg_color = theme.get("fg_color", "#ffffff")
        entry_bg = theme.get("log_bg", "#2d2d2d")
        
        self.ignore_settings_window.configure(bg=bg_color)

        main_frame = tk.Frame(self.ignore_settings_window, bg=bg_color, padx=15, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="Ignored Files/Folders:", bg=bg_color, fg=fg_color, anchor="w", font=("Arial", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        
        listbox_frame = tk.Frame(main_frame, bg=bg_color)
        listbox_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        listbox_frame.grid_columnconfigure(0, weight=1)
        listbox_frame.grid_rowconfigure(0, weight=1)

        # Listbox for ignored items (removed insertbackground)
        self.ignore_listbox = tk.Listbox(listbox_frame, selectmode=tk.EXTENDED, height=15, bg=entry_bg, fg=fg_color)
        self.ignore_listbox.grid(row=0, column=0, sticky="nsew")
        
        # Populate with current project's ignored items
        current_project_ignores = self.config.get_project_ignored_files(self.fs_tools.working_dir)
        for item in current_project_ignores:
            self.ignore_listbox.insert(tk.END, item)

        buttons_frame = tk.Frame(listbox_frame, bg=bg_color)
        buttons_frame.grid(row=0, column=1, sticky="ns", padx=(10, 0))

        def select_files_to_ignore():
            selected_items = filedialog.askopenfilenames(
                title="Select files to ignore",
                initialdir=self.fs_tools.working_dir
            )
            if selected_items:
                for item_path in selected_items:
                    item_name = Path(item_path).name
                    if item_name not in list(self.ignore_listbox.get(0, tk.END)):
                        self.ignore_listbox.insert(tk.END, item_name)

        def select_folder_to_ignore():
            selected_folder = filedialog.askdirectory(
                title="Select a folder to ignore",
                initialdir=self.fs_tools.working_dir,
                parent=self.ignore_settings_window
            )
            if selected_folder:
                folder_name = Path(selected_folder).name
                if folder_name not in list(self.ignore_listbox.get(0, tk.END)):
                    self.ignore_listbox.insert(tk.END, folder_name)

        def add_ignore_item_manually():
            item = simpledialog.askstring("Add Ignored Item", "Enter file or folder name to ignore:", parent=self.ignore_settings_window)
            if item:
                if item not in list(self.ignore_listbox.get(0, tk.END)):
                    self.ignore_listbox.insert(tk.END, item)

        def remove_ignore_item():
            selected_indices = self.ignore_listbox.curselection()
            if not selected_indices:
                return
            
            for index in sorted(selected_indices, reverse=True):
                self.ignore_listbox.delete(index)

        tk.Button(buttons_frame, text="+ Add Files", command=select_files_to_ignore, bg="#0d47a1", fg="white").pack(fill=tk.X, pady=2)
        tk.Button(buttons_frame, text="+ Add Folder", command=select_folder_to_ignore, bg="#0d47a1", fg="white").pack(fill=tk.X, pady=2)
        tk.Button(buttons_frame, text="+ Add Manually", command=add_ignore_item_manually, bg="#0d47a1", fg="white").pack(fill=tk.X, pady=2)
        tk.Button(buttons_frame, text="- Remove", command=remove_ignore_item, bg="#f44336", fg="white").pack(fill=tk.X, pady=2)

        main_frame.grid_rowconfigure(1, weight=1)

        # --- Save/Cancel Buttons ---
        def save_ignore_settings():
            updated_ignores = list(self.ignore_listbox.get(0, tk.END))
            self.config.set_project_ignored_files(self.fs_tools.working_dir, updated_ignores)
            
            # Update the FileSystemTools instance with the new ignored list
            self.fs_tools.update_working_dir(self.fs_tools.working_dir)

            self.log_message(f"Ignored files/folders updated for {self.fs_tools.working_dir.name}", "info")
            
            # --- NEW: Update Agent's file tree context if in a persistent session ---
            if self.agent and self.agent.persistent_session_enabled:
                self.agent.update_file_tree_context(self.agent.persistent_conversation_id)
            # --- END NEW ---

            self.ignore_settings_window.destroy()

        button_frame = tk.Frame(main_frame, bg=bg_color)
        button_frame.grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky="e")
        
        save_button = tk.Button(button_frame, text="Save & Close", command=save_ignore_settings, bg="#4caf50", fg="white")
        save_button.pack(side=tk.RIGHT, padx=5)
        
        cancel_button = tk.Button(button_frame, text="Cancel", command=self.ignore_settings_window.destroy, bg="#f44336", fg="white")
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

    def send_text_input(self, event=None):
        """Sends the text from the input field to the agent."""
        user_input = self.text_input.get().strip()
        if user_input:
            self.log_message(f"📝 You said: {user_input}", "user")
            self.text_input.delete(0, tk.END) # Clear input field
            if self.agent:
                # --- CONCEPTUAL INTEGRATION POINT ---
                # The agent should use the file tree from fs_tools, which is already filtered.
                # If the agent needs to actively fetch the file tree upon receiving a prompt,
                # it should call self.fs_tools.get_file_tree() here or within its processing logic.
                # Example (if agent directly fetches file tree): 
                # file_tree_for_llm = self.fs_tools.get_file_tree()
                # self.agent.process_prompt(user_input, file_tree=file_tree_for_llm)
                # 
                # For now, assuming the agent internally calls fs_tools.get_file_tree() when needed:
                self.agent.process_prompt(user_input)
                # --- END CONCEPTUAL INTEGRATION ---
            else:
                self.log_message("❌ Agent not initialized!", "error")
        else:
            self.log_message("Input is empty.", "info")

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
        # Placeholder for the code editor
        self.code_editor_placeholder = tk.Frame(right_frame, bg="#2d2d2d") # Will be replaced by actual editor
        self.code_editor_placeholder.pack(fill=tk.BOTH, expand=True)
        # self.code_preview = scrolledtext.ScrolledText(right_frame, bg="#2d2d2d", fg="white", font=("Courier", 10), state=tk.DISABLED)
        # self.code_preview.pack(fill=tk.BOTH, expand=True)
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
            # Clear the code editor placeholder or show a message
            for widget in self.code_editor_placeholder.winfo_children():
                widget.destroy()
            tk.Label(self.code_editor_placeholder, text='No content to display.', bg="#2d2d2d", fg="white").pack(fill=tk.BOTH, expand=True)
            self.preview_label.config(text="Select an action to preview")
            return
        
        index = selection_indices[0]
        action = self.pending_actions[index]
        details = action['details']
        
        path = details.get('path', 'Unknown')
        diff_content = details.get('diff', details.get('content', 'No content to display.'))

        self.preview_label.config(text=f"Diff for: {path}")
        
        # Clear previous editor content and create a new one or update existing
        for widget in self.code_editor_placeholder.winfo_children():
            widget.destroy()
        
        # --- Placeholder for Cupcake Editor Integration ---
        # In a real implementation, you would instantiate your code editor here.
        # For now, we'll use a simple ScrolledText as a placeholder.
        self.code_preview = scrolledtext.ScrolledText(self.code_editor_placeholder, wrap=tk.WORD, bg="#2d2d2d", fg="white", font=("Courier", 10), insertbackground="white")
        self.code_preview.pack(fill=tk.BOTH, expand=True)
        self.code_preview.insert(tk.END, diff_content)
        self.code_preview.config(state=tk.DISABLED) # Start as disabled, enable for editing if needed
        # --- End Placeholder ---

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

    def update_file_tree(self):
        """Fetches and updates the file tree, respecting ignored files."""
        # This method is called when the working directory changes or potentially on startup.
        # It ensures that self.current_file_tree is updated with the latest filtered view.
        try:
            self.current_file_tree = self.fs_tools.get_file_tree()
            self.log_message("File tree updated.", "info")
            # If the Agent needs to be explicitly updated with the file tree, 
            # this is where you would call a method on the agent instance.
            # For example: self.agent.set_file_tree(self.current_file_tree)
            # (Assuming such a method exists in the Agent class)
        except Exception as e:
            self.log_message(f"Error updating file tree: {e}", "error")
            self.current_file_tree = ""

    def run(self):
        """Start the application"""
        self.root.mainloop()

