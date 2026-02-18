# 🛡️ vCompanion

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![vSphere Support](https://img.shields.io/badge/vSphere-7.0U3%2B-orange.svg)](https://www.vmware.com/products/vsphere.html)
[![License](https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-lightgrey.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](https://github.com/MaciejLukaszewicz/vCompanion)

**vCompanion** is a unified management dashboard for vSphere administrators. It lets you monitor and manage multiple, independent vCenter environments through a single, modern web interface — no federation required.

> [!NOTE]
> Designed for simplicity. Built for performance. Dedicated to administrators who manage diverse vSphere environments without the complexity of full federation.

---

## 📸 Screenshots

### Dashboard - Dark Mode
![Dashboard Dark Mode](.github/images/dashboard_dark.png)
*Real-time monitoring with alerts, resource distribution, and performance metrics*

### Dashboard - Light Mode
![Dashboard Light Mode](.github/images/dashboard_light.png)
*Clean, modern interface with customizable themes*

### Settings Panel
![Settings Panel](.github/images/settings.png)
*Comprehensive configuration for vCenter connections, themes, and security*

---

## ✨ Key Features

### 🌐 Multi-vCenter Management
*   **Unified Inventory**: A clean, consistent view of all your resources (VMs, Hosts, Networks, Storage) across multiple vCenters
*   **Zero Federation Required**: Manage independent vCenter environments without complex federation setup
*   **Dynamic Status Indicators**: Real-time connection status with refresh progress
*   **Background Synchronization**: Intelligent worker that updates data automatically (configurable per-vCenter)

### 📊 Comprehensive Dashboard
*   **Proactive Monitoring**: High-level metrics for VMs, snapshots, hosts, and critical issues
*   **Time-Sorted Alerts**: Infrastructure alarms sorted by time with severity indicators (Critical, Warning, Info)
*   **Performance Metrics**: CPU, Memory, and Storage utilization across all hosts
*   **Cluster Resource Overview**: Detailed breakdown of cluster resources with capacity planning insights
*   **Recent Tasks & Events**: Live feed of vCenter tasks and events across all environments

### 🔍 Advanced Search & Discovery
*   **Global Search**: Instant search for VMs, IP addresses, and hosts across your entire infrastructure
*   **Indexed Cache**: Lightning-fast search using optimized cached data
*   **Cross-vCenter Results**: Single search query spans all connected environments

### 📂 Storage Management
*   **Storage Topology**: Dedicated view for Datastore Clusters and individual Datastores
*   **Visual Capacity Bars**: Color-coded capacity indicators with used/free space breakdown
*   **Storage Type Detection**: Distinguishes between local and shared storage
*   **Host Access Tracking**: Shows which hosts can access each datastore

### 🔗 Network Visualization
*   **Enhanced Networking**: Detailed visualization of Distributed and Standard switches
*   **VLAN Mapping**: Complete VLAN ID detection and portgroup association
*   **VMkernel Services**: Track enabled services (Management, vMotion, vSAN, FT, etc.) per adapter
*   **Network Labels**: Display portgroup names for each VMkernel interface

### 🖥️ Host Details
*   **Performance Metrics**: Real-time CPU, memory, and storage utilization per host
*   **Uptime Tracking**: Accurate uptime calculation with build information
*   **Network Profile**: Detailed networking configuration including VMkernel adapters
*   **Storage Profile**: Connected datastores with capacity and accessibility status

### ⚙️ Settings Panel
*   **vCenter Management**: Add, edit, enable/disable, and remove vCenter connections
*   **Theme Customization**: Light/Dark mode with multiple accent color options (Blue, Purple, Emerald, Orange)
*   **Session Control**: Configurable session timeout with visual countdown timer
*   **Cache Management**: Manual cache purge for troubleshooting
*   **Refresh Intervals**: Per-vCenter and global refresh rate configuration

### 🔒 Security & Privacy
*   **Zero Password Storage**: vCenter passwords are never stored on disk or in browser cookies
*   **Volatile RAM Keys**: Encryption keys derived from user passwords (PBKDF2) kept only in volatile memory
*   **AES-128 Encryption**: All cached data is encrypted with industry-standard encryption
*   **Session Management**: Secure sessions with configurable inactivity timeout and visual countdown
*   **Auto-Invalidation**: Server restarts automatically invalidate all encryption keys

### 📈 Reporting & Export
*   **CSV Reports**: Generate detailed reports for inventory and critical events
*   **Time-Based Filtering**: Filter alerts by time periods (Last Day, Last Week)

### 🎨 Modern UI/UX
*   **Glassmorphism Design**: Modern, premium interface with smooth animations
*   **Responsive Layout**: Works seamlessly on desktop and tablet devices
*   **HTMX-Powered**: Dynamic updates without page reloads or complex JavaScript
*   **Lucide Icons**: Clean, modern iconography throughout the interface

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) |
| **Templating** | [Jinja2](https://jinja.palletsprojects.com/) |
| **Frontend** | [HTMX](https://htmx.org/) + Vanilla CSS |
| **vSphere API** | [pyvmomi](https://github.com/vmware/pyvmomi) |
| **Charts** | [ApexCharts](https://apexcharts.com/) |
| **Reporting** | [Pandas](https://pandas.pydata.org/) + [OpenPyXL](https://openpyxl.readthedocs.io/) |
| **Security** | PBKDF2 key derivation + AES-128 encryption |
| **Icons** | [Lucide](https://lucide.dev/) |

---

## 📋 Requirements

- **vCenter Server**: Version 7.0 Update 3 or later (vSphere 8.x fully supported)
- **Python**: Version 3.12 or newer
- **OS**: Windows (primary); Linux supported for manual setup
- **Connectivity**: Network access to managed vCenters on HTTPS (port 443)
- **Permissions**: Read-only credentials for vCenter access (AD or SSO)
- **Browser**: Any modern web browser with JavaScript enabled

---

## 🚀 Quick Start

### 1. Clone & Install
```powershell
git clone https://github.com/MaciejLukaszewicz/vCompanion.git
cd vCompanion
.\setup\setup.bat
```

### 2. Configure
On first run, `config/config.json` is created automatically with a default template. Edit it to add your vCenter servers:

```json
{
  "app_settings": {
    "title": "vCompanion",
    "theme": "light",
    "accent_color": "blue",
    "session_timeout": 3600,
    "refresh_interval_seconds": 120,
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

> **Tip:** You can also manage all settings through the web UI under **Settings** after logging in.

### 3. Run
```powershell
.\run.bat
```
The browser opens automatically at `http://localhost:8000`.

### 4. First Login
- Use your vCenter credentials (Active Directory or SSO)
- Select which vCenters to connect to
- The dashboard loads cached data immediately and refreshes in the background

---

## 🔄 Updates
Keep your installation up-to-date:
```powershell
.\setup\update.bat
```

---

## 📝 Documentation
- [Installation Guide](INSTALL.md) — detailed setup instructions
- [Technical Description](description.md) — architecture and internals

---

## 🎯 Use Cases

- **Multi-Site Management**: Oversee production, DR, and development vCenters from one interface
- **Capacity Planning**: Track resource utilization and plan for growth
- **Incident Response**: Quickly identify and respond to infrastructure alerts
- **Compliance Reporting**: Generate reports for audits and documentation
- **Network Troubleshooting**: Visualize network topology and VMkernel configurations

---

## 🤝 Contributing
Feedback and contributions are welcome! Please feel free to submit issues or pull requests.

---

## 📄 License
This project is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) - see the [LICENSE](LICENSE) file for details.

---

*vCompanion — Managing vSphere has never looked this good.*
