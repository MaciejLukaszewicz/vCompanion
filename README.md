# 🛡️ vCompanion

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![vSphere Support](https://img.shields.io/badge/vSphere-7.0U3%2B-orange.svg)](https://www.vmware.com/products/vsphere.html)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Uptime](https://img.shields.io/badge/status-active-brightgreen.svg)]()

**vCompanion** is a high-end, unified management dashboard designed for vSphere administrators. It allows you to oversee multiple, non-federated vCenter environments through a single, stunning web interface.

> [!NOTE]
> Designed for simplicity. Built for performance. Dedicated to administrators who manage diverse vSphere environments without the complexity of full federation.

---

## ✨ Key Features

*   **🌐 Unified Inventory**: A clean, consistent view of all your resources (VMs, Hosts, Networks, Storage) across multiple vCenters.
*   **📂 Storage Topology**: Dedicated view for Datastore Clusters and Datastores with visual capacity bars and host access tracking.
*   **🔗 Enhanced Networking**: Detailed visualization of Distributed and Standard switches, including VLAN IDs and VMkernel services.
*   **🔍 Global Search**: Instant search for VMs, IP addresses, and hosts across your entire infrastructure.
*   **📊 Proactive Dashboards**: High-level metrics for snapshots, critical issues, and resource distribution.
*   **📈 Reporting & Alerting**: Generate Excel/CSV reports and track critical vSphere events.
*   **🌑 Premium Dark Mode**: Modern, glassmorphism-inspired UI with interactive charts via ApexCharts.
*   **🚀 Zero Configuration Overhead**: Fast setup with automated virtual environment management.

---

## 🛠️ Tech Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Modern, high-performance Python framework)
- **Frontend**: [HTMX](https://htmx.org/) (Dynamic updates without complex JS) & Modern CSS
- **API**: [pyvmomi](https://github.com/vmware/pyvmomi) (VMware vSphere API Python bindings)
- **Charts**: [ApexCharts](https://apexcharts.com/)
- **Data**: [Pandas](https://pandas.pydata.org/) for advanced reporting

---

## 📋 Requirements

- **vCenter Server**: Version 7.0 Update 3 or later.
- **Python**: Version 3.12 or newer.
- **Connectivity**: Network access to managed vCenters on HTTPS (port 443).
- **Permissions**: Read-only credentials for vCenter access.

---

## 🚀 Quick Start

### 1. Installation
The easiest way to get started is via Git:
```powershell
git clone https://github.com/your-username/vCompanion.git
cd vCompanion
.\setup\setup.bat
```

### 2. Configuration
Edit `config/config.json` to add your vCenter environments:
```json
{
  "vcenters": [
    {
      "id": "prod-site-a",
      "name": "Production Site A",
      "host": "vc-a.example.com"
    }
  ]
}
```

### 3. Run
```powershell
.\setup\run.bat
```
Visit `http://localhost:8000` to access the dashboard.

---

## 🔄 Updates
Keep your installation up-to-date with one command:
```powershell
.\setup\update.bat
```

## 📝 Documentation
For more detailed information, please refer to:
- [Environment Requirements](description.md)
- [Installation Guide](INSTALL.md) (Coming soon)

---

## 🤝 Contributing
Feedback and contributions are welcome! Please feel free to submit issues or pull requests.

---

*vCompanion - Managing vSphere has never looked this good.*
