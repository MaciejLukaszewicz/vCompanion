# 🛠️ Installation Guide — vCompanion

This guide provides step-by-step instructions for installing and running vCompanion on Windows.

---

## Prerequisites

Before starting, ensure you have the following:

1. **Git** — for cloning the repository. [Download Git](https://git-scm.com/downloads)
2. **Python 3.12+** — the application requires Python 3.12 or newer. [Download Python](https://www.python.org/downloads/)
   - *Windows*: Check **"Add Python to PATH"** during installation.

---

## 1. Get the Code

### Option A: Clone with Git (Recommended)
Cloning the repository allows you to use the automatic `update.bat` script later.

```powershell
git clone https://github.com/MaciejLukaszewicz/vCompanion.git
cd vCompanion
```

### Option B: Download ZIP
1. Go to the [Releases](https://github.com/MaciejLukaszewicz/vCompanion/releases) page.
2. Download the `Source code (zip)` for the latest version.
3. Extract the contents to your desired location and open a terminal in that folder.

---

## 2. Run Setup (Windows)

```powershell
.\setup\setup.bat
```

The script will:
- Create a Python virtual environment (`venv/`)
- Upgrade `pip`
- Install all required packages from `requirements.txt`

> **Note:** `config/config.json` is **not** included in the repository. It will be created automatically with default values on the first run of the application.

---

## 3. Manual Setup (Linux / macOS)

If you prefer manual installation or are on Linux/macOS:

```bash
python -m venv venv
source venv/bin/activate       # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
```

---

## 4. Configuration

On first launch, `config/config.json` is created automatically with sensible defaults and one example vCenter entry. Edit it to match your environment:

```json
{
  "app_settings": {
    "title": "vCompanion",
    "session_timeout": 3600,
    "log_level": "ERROR",
    "log_to_file": false,
    "refresh_interval_seconds": 120,
    "theme": "light",
    "accent_color": "blue",
    "port": 8000,
    "open_browser_on_start": true
  },
  "vcenters": [
    {
      "id": "prod",
      "name": "Production",
      "host": "vcenter-prod.example.com",
      "port": 443,
      "verify_ssl": false,
      "enabled": true,
      "refresh_interval": 180
    }
  ]
}
```

### Configuration Reference

#### `app_settings`

| Field | Type | Default | Description |
|---|---|---|---|
| `title` | string | `"vCompanion"` | Application name shown in the UI |
| `session_timeout` | int | `3600` | Inactivity timeout in seconds |
| `log_level` | string | `"ERROR"` | Logging verbosity: `DEBUG`, `INFO`, `ERROR` |
| `log_to_file` | bool | `false` | Write logs to `log.txt` |
| `refresh_interval_seconds` | int | `120` | Global background refresh interval |
| `theme` | string | `"light"` | UI theme: `"light"` or `"dark"` |
| `accent_color` | string | `"blue"` | Accent color: `"blue"`, `"purple"`, `"emerald"`, `"orange"` |
| `port` | int | `8000` | TCP port the server listens on |
| `open_browser_on_start` | bool | `true` | Automatically open browser on startup |

#### `vcenters[]`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | ✅ | Unique identifier (used internally) |
| `name` | string | ✅ | Display name shown in the UI |
| `host` | string | ✅ | FQDN or IP address of the vCenter |
| `port` | int | | HTTPS port, default `443` |
| `verify_ssl` | bool | | Verify SSL certificate, default `false` |
| `enabled` | bool | | Include in connections, default `true` |
| `refresh_interval` | int | | Per-vCenter refresh interval in seconds |

> **Tip:** All settings can also be managed through the **Settings** panel in the web UI after logging in.

---

## 5. Running the Application

### Windows (recommended)

```powershell
.\run.bat
```

The browser opens automatically at `http://localhost:8000`.

### Manual start

With the virtual environment activated:

```bash
python main.py
```

Or directly with uvicorn:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

---

## 6. First Login

1. Navigate to `http://localhost:8000`
2. Enter your **vCenter credentials** (Active Directory or SSO account)
3. Select which vCenters to connect to
4. Click **Login** — the dashboard loads immediately from cache and refreshes in the background

> **Security note:** Your password is never stored on disk or in cookies. It is used only to derive an in-memory encryption key and authenticate against vCenter.

---

## 7. Updating

To pull the latest version:

```powershell
.\setup\update.bat
```

This runs `git pull` and reinstalls any updated dependencies.

---

## 8. Troubleshooting

| Problem | Solution |
|---|---|
| `Python not found` | Ensure Python 3.12+ is installed and added to PATH |
| `Cannot connect to vCenter` | Check network connectivity and firewall rules on port 443 |
| `Session expires immediately` | Restart the application — the previous session cookie is stale |
| `Port already in use` | Change `port` in `config.json` or stop the conflicting process |
| `SSL errors` | Set `"verify_ssl": false` for self-signed certificates |
| `Blank dashboard` | Wait for the background refresh to complete (first run takes ~30s) |
