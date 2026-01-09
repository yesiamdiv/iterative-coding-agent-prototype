import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Union


# ============================================================================
# Configuration Management
# ============================================================================

class Config:
    """Manages application configuration from config.json"""
    
    DEFAULT_CONFIG = {
        "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
        "stt_provider": "gemini",
    
        "whisper_model_size": "base",
        "whisper_custom_model": "null",
        "whisper_device": "cpu",
        "whisper_compute_type": "int8",
        
        "gemini_stt_model": "gemini-2.5-flash",
        "gemini_stt_language": "en",
        
        "audio_sample_rate": 16000,
        "audio_channels": 1,
        "gemini_model": "gemini-2.5-flash",
        "system_prompt": "You are The Architect, an expert coding assistant. When the user asks you to create files, you MUST use the write_file tool to actually create them. Always use the available tools (get_file_tree, read_file, write_file) to complete tasks. Explain your plan briefly, then immediately execute it using the tools.",
        "ignored_folders": [
            ".git",
            "node_modules",
            "__pycache__",
            "venv",
            ".env",
            "dist",
            "build",
            ".vscode",
            ".idea",
            "venv",
            "example"
        ],
        "project_ignored_files": {},
        "max_file_size_kb": 500,
        "backup_extension": ".bak",
        "working_directory": ".",
        "enable_debug_logging": "True",
        "persistent_session": "False",
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
            "button_active_bg": "#1565c0",
            "debug_color": "#9c27b0"
        }
    }
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        # Ensure default ignored_folders is a mutable list
        if "ignored_folders" in self.DEFAULT_CONFIG and isinstance(self.DEFAULT_CONFIG["ignored_folders"], list):
            self.DEFAULT_CONFIG["ignored_folders"] = list(self.DEFAULT_CONFIG["ignored_folders"])
        # Ensure default project_ignored_files is a mutable dict
        if "project_ignored_files" in self.DEFAULT_CONFIG and isinstance(self.DEFAULT_CONFIG["project_ignored_files"], dict):
            self.DEFAULT_CONFIG["project_ignored_files"] = dict(self.DEFAULT_CONFIG["project_ignored_files"])

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
                # Deep update for nested dictionaries like gui_theme
                for key, value in loaded_config.items():
                    if isinstance(value, dict) and key in merged_config and isinstance(merged_config[key], dict):
                        merged_config[key].update(value)
                    else:
                        merged_config[key] = value
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

    def get_project_ignored_files(self, project_path: Union[str, Path]) -> List[str]:
        """Get the list of ignored files/folders for a specific project."""
        project_path_str = str(Path(project_path).resolve())
        project_ignores = self.get("project_ignored_files", {}).get(project_path_str, [])
        global_ignores = self.get("ignored_folders", [])
        
        # Combine global and project-specific ignores, avoiding duplicates
        combined_ignores = list(set(global_ignores + project_ignores))
        return combined_ignores

    def set_project_ignored_files(self, project_path: Union[str, Path], ignored_list: List[str]):
        """Set the list of ignored files/folders for a specific project."""
        project_path_str = str(Path(project_path).resolve())
        current_project_ignores = self.get("project_ignored_files", {})
        current_project_ignores[project_path_str] = ignored_list
        self.set("project_ignored_files", current_project_ignores)

