import google.generativeai as genai
import threading
import uuid
from typing import Dict, Any, Callable

from file_system_tools import FileSystemTools
from config import Config

# ============================================================================
# Agent Architecture
# ============================================================================

class Agent:
    """
    Manages multi-turn, stateful, and non-blocking conversations with the Gemini API.
    Each user prompt initiates a new, independent conversation.
    """

    def __init__(self, config: Config, fs_tools: FileSystemTools, log_callback: Callable, action_callback: Callable, status_callback: Callable):
        self.config = config
        self.fs_tools = fs_tools
        self.log_callback = log_callback
        self.action_callback = action_callback
        self.status_callback = status_callback
        self.debug_enabled = self.config.get("enable_debug_logging", "False").lower() == "true"
        self.persistent_session_enabled = self.config.get("persistent_session", "False").lower() == "true"
        self.persistent_conversation_id = "persistent_conv_main"

        # Data stores for managing multiple, independent conversations
        self.conversations: Dict[str, Any] = {}
        self.pending_actions: Dict[str, Dict[str, Any]] = {}
        self.action_results: Dict[str, Dict[str, Any]] = {}
        
        # Configure Gemini
        api_key = config.get("gemini_api_key")
        if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
            raise ValueError("Please set your Gemini API key in config.json")
        genai.configure(api_key=api_key)

        # Define tools that the AI can use
        self.tools = [
            {
                "function_declarations": [
                    {
                        "name": "get_file_tree",
                        "description": "Get the file structure of the current project directory.",
                        "parameters": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "read_file",
                        "description": "Read the content of a specific file.",
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
                        "description": "Create or modify a file. Requires user approval.",
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

        if self.persistent_session_enabled:
            self._start_new_conversation(self.persistent_conversation_id)

    def _debug_log(self, message: str):
        """Logs a message if debug logging is enabled."""
        if self.debug_enabled:
            self.log_callback(f"🐞 DEBUG: {message}", "debug")

    def _start_new_conversation(self, conversation_id: str):
        """Creates and stores a new chat session with initial context."""
        system_prompt = self.config.get("system_prompt")
        file_tree = self.fs_tools.get_file_tree()
        
        history = [
            {
                "role": "user",
                "parts": [f"{system_prompt}\n\nCurrent Project Structure:\n{file_tree}"]
            },
            {
                "role": "model",
                "parts": ["Understood. I am The Architect. Ready to analyze code and file structures."]
            }
        ]
        
        self.conversations[conversation_id] = self.model.start_chat(history=history)
        self.pending_actions[conversation_id] = {}
        self.action_results[conversation_id] = {}

    def process_prompt(self, user_prompt: str):
        """
        Public entry point to start a new conversation and feedback loop in a separate thread.
        """
        thread = threading.Thread(target=self._process_prompt_thread, args=(user_prompt,))
        thread.start()

    def _process_prompt_thread(self, user_prompt: str):
        """Thread target for handling a new prompt to avoid blocking the GUI."""
        conversation_id = ""
        try:
            if self.persistent_session_enabled:
                conversation_id = self.persistent_conversation_id
                # Ensure session exists if it was somehow cleared
                if conversation_id not in self.conversations:
                    self._start_new_conversation(conversation_id)
            else:
                conversation_id = f"conv_{uuid.uuid4()}"
                self._start_new_conversation(conversation_id)
            
            chat_session = self.conversations[conversation_id]
            response = chat_session.send_message(user_prompt)
            self._debug_log(f"Initial raw response from model:\n{response}")
            
            self._process_response(conversation_id, response)
        except Exception as e:
            self.log_callback(f"❌ Error in conversation thread: {str(e)}", "error")
            self.status_callback("error")

    def handle_action_result(self, id_bundle: tuple, result: Dict[str, Any]):
        """
        Public entry point for the GUI to provide the result of a user's decision on an action.
        """
        conversation_id, action_group_id, action_id = id_bundle
        
        self.action_results.setdefault(conversation_id, {}).setdefault(action_group_id, {})[action_id] = result
        
        pending_group = self.pending_actions.get(conversation_id, {}).get(action_group_id, {})
        results_group = self.action_results.get(conversation_id, {}).get(action_group_id, {})

        # Count actual actions, ignoring internal metadata like '_immediate_read_results'
        pending_action_count = sum(1 for k in pending_group if not k.startswith('_'))

        if pending_group and pending_action_count == len(results_group):
            thread = threading.Thread(target=self._continue_conversation_thread, args=(conversation_id, action_group_id))
            thread.start()

    def _continue_conversation_thread(self, conversation_id: str, action_group_id: str):
        """Thread target to continue a conversation after an action group has been resolved by the user."""
        try:
            chat_session = self.conversations.get(conversation_id)
            if not chat_session:
                self.log_callback(f"❌ Error: Could not find conversation {conversation_id} to continue.", "error")
                return

            pending_group = self.pending_actions[conversation_id][action_group_id]
            results_group = self.action_results[conversation_id][action_group_id]

            # Combine immediate read results from the original turn with new user-provided write results
            all_function_responses = pending_group.get("_immediate_read_results", [])
            
            for action_id, result in results_group.items():
                action = pending_group[action_id]
                if result.get("approved"):
                    path = action.get("args", {}).get("path")
                    content = action.get("args", {}).get("content")
                    
                    if path is not None and content is not None:
                        write_status = self.fs_tools.execute_write(path, content)
                        log_level = "success" if "SUCCESS" in write_status else "error"
                        self.log_callback(f"💾 {write_status}", log_level)
                    else:
                        self.log_callback(f"❌ Could not write file: path or content missing.", "error")
                    
                    response_content = {"result": "User approved. File has been written."}
                else:
                    response_content = {"error": result.get("feedback", "User rejected the action.")}

                all_function_responses.append({
                    "name": action["name"],
                    "response": response_content
                })

            if all_function_responses:
                self._debug_log(f"Sending function results to model:\n{all_function_responses}")
                response = chat_session.send_message(
                    genai.protos.Content(
                        parts=[
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(name=fr["name"], response=fr["response"])
                            ) for fr in all_function_responses
                        ]
                    )
                )
                self._debug_log(f"Continued raw response from model:\n{response}")
                self._process_response(conversation_id, response)
            
            del self.pending_actions[conversation_id][action_group_id]
            del self.action_results[conversation_id][action_group_id]

        except Exception as e:
            self.log_callback(f"❌ Error continuing conversation: {str(e)}", "error")
            self.status_callback("error")

    def update_file_tree_context(self, conversation_id: str):
        """
        Updates the file tree context for an ongoing conversation.
        This is particularly useful for persistent sessions when ignore settings change.
        """
        try:
            chat_session = self.conversations.get(conversation_id)
            if chat_session:
                latest_file_tree = self.fs_tools.get_file_tree()
                self._debug_log(f"Updating file tree context for conversation {conversation_id}.")
                updated_tree_message = f"USER: The project's file tree has been updated due to recent changes in ignore settings. Please take this new project structure into account for all future actions:\n\nNew Project Structure:\n{latest_file_tree}"
                
                # Send this as a user message to the AI in the ongoing chat
                chat_session.send_message(updated_tree_message)
                self.log_callback("✅ Agent's file tree context updated for persistent session.", "info")
            else:
                self.log_callback(f"⚠️ Cannot update file tree context: Conversation {conversation_id} not found.", "info")
        except Exception as e:
            self.log_callback(f"❌ Error updating agent's file tree context: {str(e)}", "error")

    def _process_response(self, conversation_id: str, response: Any):
        """
        Processes a model's response, handling the iterative reasoning loop.
        - Executes read-only tools immediately.
        - Pauses and waits for user feedback when write tools are called.
        """
        max_iterations = 10
        for i in range(max_iterations):
            self._debug_log(f"Processing response iteration {i+1}/{max_iterations}")
            if not response.candidates or not response.candidates[0].content.parts:
                self.log_callback("✅ Task completed.", "info")
                if not self.persistent_session_enabled:
                    if conversation_id in self.conversations: del self.conversations[conversation_id]
                self.status_callback("completed")
                return

            immediate_function_responses = []
            pending_user_actions = []

            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    self.log_callback(f"💭 {part.text}", "ai")

                if hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    function_name = fc.name
                    args = dict(fc.args)
                    self.log_callback(f"🔧 Tool Call: {function_name}", "ai")

                    if function_name in ["read_file", "get_file_tree"]:
                        result = self.fs_tools.read_file(args.get("path", "")) if function_name == "read_file" else self.fs_tools.get_file_tree()
                        immediate_function_responses.append({"name": function_name, "response": {"result": result}})
                    elif function_name == "write_file":
                        pending_user_actions.append({"name": function_name, "args": args})
            
            self._debug_log(f"Parsed response. Found {len(pending_user_actions)} pending actions and {len(immediate_function_responses)} immediate actions.")
            if pending_user_actions:
                action_group_id = f"ag_{uuid.uuid4()}"
                action_group = {"_immediate_read_results": immediate_function_responses}
                
                for action in pending_user_actions:
                    action_id = f"act_{uuid.uuid4()}"
                    id_bundle = (conversation_id, action_group_id, action_id)
                    action_group[action_id] = action
                    
                    gui_action_details = self.fs_tools.prepare_write(
                        action["args"].get("path", ""), action["args"].get("content", "")
                    )
                    self.action_callback(gui_action_details, id_bundle)

                self.pending_actions[conversation_id][action_group_id] = action_group
                return

            elif immediate_function_responses:
                self._debug_log("Continuing conversation with results from immediate actions.")
                chat_session = self.conversations[conversation_id]
                response = chat_session.send_message(
                    genai.protos.Content(
                        parts=[
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(name=fr["name"], response=fr["response"])
                            ) for fr in immediate_function_responses
                        ]
                    )
                )
                continue
            
            else: # No function calls, conversation turn is complete.
                if not self.persistent_session_enabled:
                    if conversation_id in self.conversations: del self.conversations[conversation_id]
                self.status_callback("completed")
                return
