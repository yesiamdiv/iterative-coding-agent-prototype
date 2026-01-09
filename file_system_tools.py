import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import shutil # Import shutil for backup operations

from config import Config

# ============================================================================
# File System Tools
# ============================================================================

class FileSystemTools:
    """Provides file system operations for the AI"""
    
    def __init__(self, config: Config, working_dir: Optional[Union[str, Path]] = None):
        self.config = config
        if working_dir:
            self.working_dir = Path(working_dir).resolve()
        else:
            self.working_dir = Path(config.get("working_directory", ".")).resolve()
        
        # Load ignored folders specific to the current working directory
        self.ignored_folders = self.config.get_project_ignored_files(self.working_dir)
        
        self.max_file_size = config.get("max_file_size_kb", 500) * 1024
        self.backup_ext = config.get("backup_extension", ".bak")
    
    def update_working_dir(self, new_working_dir: Union[str, Path]):
        """Update the working directory and reload ignored folders."""
        self.working_dir = Path(new_working_dir).resolve()
        # Reload ignored folders based on the new working directory
        self.ignored_folders = self.config.get_project_ignored_files(self.working_dir)
        self.config.set("working_directory", str(self.working_dir))

    def get_file_tree(self) -> str:
        """Generate a tree structure of the project"""
        tree_lines = [f"📁 {self.working_dir.name}/"]
        
        def build_tree(path: Path, prefix: str = "", is_last: bool = True):
            try:
                # Get all items, then filter out ignored ones
                all_items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                items = [item for item in all_items if item.name not in self.ignored_folders]
                
                for i, item in enumerate(items):
                    is_last_item = (i == len(items) - 1)
                    current_prefix = "└── " if is_last_item else "├── "
                    tree_lines.append(f"{prefix}{current_prefix}{item.name}")
                    
                    if item.is_dir():
                        extension = "    " if is_last_item else "│   "
                        # Recursively call build_tree only for non-ignored directories
                        build_tree(item, prefix + extension, is_last_item)
            except PermissionError:
                # Silently ignore permission errors for directories
                pass
            except FileNotFoundError:
                # Handle cases where a directory might disappear during iteration
                pass
        
        # Start building the tree from the working directory
        build_tree(self.working_dir)
        return "\n".join(tree_lines)
    
    def read_file(self, path: str) -> str:
        """Read file content"""
        try:
            # Construct the absolute path
            file_path = (self.working_dir / path).resolve()
            
            # Security check: ensure path is within working directory
            if not str(file_path).startswith(str(self.working_dir)):
                return f"ERROR: Access denied - path outside working directory"
            
            if not file_path.exists():
                return f"ERROR: File not found - {path}"
            
            # Check if the file is in an ignored folder (even if path is explicit)
            relative_path_parts = file_path.relative_to(self.working_dir).parts
            for ignored in self.ignored_folders:
                if ignored in relative_path_parts:
                    return f"ERROR: Access denied - file is in an ignored folder: {path}"

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
            
            # Security check: ensure path is within working directory
            if not str(file_path).startswith(str(self.working_dir)):
                return {
                    "success": False,
                    "error": "Access denied - path outside working directory"
                }
            
            # Check if the file is in an ignored folder
            relative_path_parts = file_path.relative_to(self.working_dir).parts
            is_ignored = False
            for ignored in self.ignored_folders:
                 if ignored in relative_path_parts:
                    is_ignored = True
                    break
            
            if is_ignored:
                # Return a specific status for ignored files
                return {
                    "success": "ignored", # Custom status for ignored files
                    "path": str(file_path),
                    "relative_path": path,
                    "content": content,
                    "needs_backup": file_path.exists(),
                    "is_new": not file_path.exists()
                }
            
            # If not ignored, proceed as before
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
                try:
                    shutil.copy2(file_path, backup_path)
                    action = "Updated (with backup created)"
                except Exception as backup_err:
                    # Log or return error if backup fails, but proceed with write
                    print(f"Warning: Failed to create backup for {path}: {backup_err}")
                    action = "Updated (backup failed)"
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
