# 🛠️ Installation Guide for vCompanion

This guide provides detailed instructions for installing and configuring vCompanion on different platforms.

## Prerequisites

Before starting, ensure you have the following installed:

1.  **Git**: For cloning the repository. [Download Git](https://git-scm.com/downloads)
2.  **Python 3.12+**: The application requires Python 3.12 or newer. [Download Python](https://www.python.org/downloads/)
    *   *Windows users*: Ensure you check "Add Python to PATH" during installation.

---

## 1. Clone the Repository

Open your terminal (Command Prompt, PowerShell, or Bash) and run:

```bash
git clone https://github.com/MaciejLukaszewicz/vCompanion.git
cd vCompanion
```

---

## 2. Automated Setup (Windows)

vCompanion includes a setup script for Windows that handles virtual environment creation and dependency installation.

1.  Run the setup script:
    ```powershell
    .\setup\setup.bat
    ```
2.  The script will:
    *   Create a virtual environment (`venv`)
    *   Upgrade `pip`
    *   Install all required packages from `requirements.txt`
    *   Create a default `config/config.json` if one doesn't exist

---

## 3. Manual Setup (Linux / Mac / Manual Windows)

If you prefer manual installation or are using Linux/macOS:

1.  **Create a virtual environment**:
    ```bash
    python -m venv venv
    ```

2.  **Activate the virtual environment**:
    *   **Windows**:
        ```powershell
        .\venv\Scripts\activate
        ```
    *   **Linux/macOS**:
        ```bash
        source venv/bin/activate
        ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Create Configuration**:
    Copy the example configuration to the config directory:
    ```bash
    cp config/config.example.json config/config.json
    # Or create it manually
    ```

---

## 4. Configuration

Edit `config/config.json` to add your vCenter servers.

**Example `config.json`**:

```json
{
  "vcenters": [
    {
      "id": "vc1",
      "name": "Production vCenter",
      "host": "vcenter-prod.example.com",
      "port": 443,
      "verify_ssl": false
    },
    {
      "id": "vc2",
      "name": "DR vCenter",
      "host": "vcenter-dr.example.com",
      "port": 443,
      "verify_ssl": false
    }
  ],
  "app_settings": {
    "title": "vCompanion",
    "theme": "dark",
    "accent_color": "blue",
    "default_refresh_interval": 60,
    "session_timeout": 3600
  }
}
```

### Configuration Options

*   **vcenters**: List of vCenter server objects.
    *   `id`: Unique identifier (string).
    *   `name`: Display name.
    *   `host`: FQDN or IP address.
    *   `port`: (Optional) HTTPS port, default 443.
    *   `verify_ssl`: (Optional) Set to `true` to verify SSL certificates, `false` to ignore self-signed warnings.
*   **app_settings**: Global application settings.
    *   `theme`: `dark` (default) or `light`.
    *   `accent_color`: `blue`, `purple`, `green`, `orange`, or `red`.
    *   `session_timeout`: Inactivity timeout in seconds.

---

## 5. Running the Application

### Windows (Automated)

Double-click `run.bat` or execute in terminal:

```powershell
.\setup\run.bat
```

### Manual Start

With the virtual environment activated:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 6. Accessing the Dashboard

Open your web browser and navigate to:

[http://localhost:8000](http://localhost:8000)

Login with your Active Directory or SSO credentials. These credentials are unrelated to the application itself; they are passed directly to vCenter for authentication.
