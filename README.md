# Voice-to-Code AI Coding Helper Prototype

This project is a prototype for an AI-powered coding helper designed to assist developers by translating their ideas into code.

Unlike fully autonomous coding agents, The this acts as the developer's hands, taking high-level instructions and generating the corresponding code. The developer drives the vision, and the agent executes the coding tasks.

## Getting Started

Follow these steps to set up and run the project locally.

### Prerequisites

*   Python 3.10+
*   `pip` (Python package installer)

### Installation and Setup

1.  **Create a Virtual Environment** (recommended):

    ```bash
    python -m venv venv
    ```

2.  **Activate the Virtual Environment**:

    *   **Windows (PowerShell)**:
        ```powershell
        .\venv\Scripts\Activate.ps1
        ```
    *   **macOS / Linux**:
        ```bash
        source venv/bin/activate
        ```

3.  **Install Dependencies**:

    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure API Key**:
    *   Open `config.json`.
    *   Replace `"YOUR_GEMINI_API_KEY_HERE"` with your actual Google Gemini API key.

### Running the Application

Once the setup is complete, you can run the application:

```bash
python main.py
```

This will launch the GUI, and you can start interacting with The Architect using voice commands.