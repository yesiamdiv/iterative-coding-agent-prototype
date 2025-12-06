from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from config import Config

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
                # "needs_backup": needs_backup,
                "needs_backup": False,
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
                # backup_path = file_path.with_suffix(file_path.suffix + self.backup_ext)
                # shutil.copy2(file_path, backup_path)
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
