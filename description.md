# vCompanion

vCompanion is a management tool designed to help administrators oversee multiple vSphere environments without requiring federation.

## 1. Environment Requirements
- **vCenter Server**: Version 7.0 Update 3 or later.
- **Connectivity**: All managed vCenters must be accessible from the host system running vCompanion.
- **Authentication**: All vCenter servers must support management via the same set of credentials (AD or SSO). Read only access is sufficient.
- **Network**: HTTPS traffic (default port 443) must be allowed between vCompanion and all managed vCenters.

## 2. Application Requirements
- **Interface**: Web-based user interface (Modern, responsive, with dark mode).
- **Runtime**: Python 3.12 or later (supported on Linux and Windows; Windows is the primary testing platform). The initialization script will automatically create the Virtual Environment (venv) and install all required libraries (assuming Python is already installed).
- **Configuration**: vCenter list and application settings provided via a JSON configuration file.
- **Deployment**: The application must be deployable and updatable via Git from GitHub.
- **Technical Stack**:
    - **Backend**: FastAPI (high performance, modern ASGI framework).
    - **API Integration**: `pyvmomi` (official VMware vSphere API Python bindings).
    - **Frontend**: Clean HTML5/CSS3 with HTMX for dynamic updates without complex JS frameworks. Charting via `ApexCharts`.
    - **Data Handling**: `pandas` and `openpyxl` for report generation.
    - **Authentication**: Native vSphere SSO integration for session management.
    - **Logging**: Rotating file logs for easy troubleshooting.


## 3. Features
- **Unified Inventory**: A clean, consistent view of resources across all connected vCenters.
- **Global Search**: Search for VMs and IP addresses across all environments simultaneously.
- **Dashboards**: 
    - **Default Dashboard**: High-level overview of critical metrics (e.g., issue counts, VM totals, snapshot counts).
    - **Specialized Dashboards**: Focused views for problems, datastores, hosts, and more.
- **Session Management**: Persistent sessions after login with a 1-hour inactivity timeout.
- **Alerting**: Ability to receive alerts for critical events.
- **Reporting**: Ability to generate reports for critical events.
- **Extensibility**: Future features will be added based on user feedback.

## 4. Architecture Diagram

```mermaid
graph TD
    User["User Browser<br/>(HTMX / ApexCharts / CSS)"]
    
    subgraph vCompanion ["vCompanion Application"]
        Backend["FastAPI Backend<br/>(Sessions / Routing / Jinja2)"]
        
        Inventory["Inventory Service"]
        Metrics["Metrics Service"]
        Reporting["Reporting (Pandas)"]
        
        Backend --> Inventory
        Backend --> Metrics
        Backend --> Reporting
    end
    
    User -- "HTTP (REST/HTML)" --> Backend
    
    Inventory -- "pyvmomi (SOAP/HTTPS)" --> VC1["vCenter Prod 1"]
    Metrics -- "pyvmomi (SOAP/HTTPS)" --> VC2["vCenter DR"]
    Reporting -- "pyvmomi (SOAP/HTTPS)" --> VC3["vCenter 3"]
    
    style vCompanion fill:#f5f5f5,stroke:#333,stroke-width:2px
    style Backend fill:#e1f5fe,stroke:#01579b
    style User fill:#fff9c4,stroke:#fbc02d
```

## 5. Documentation
- **Code comments**: Code comments should be in English.
- **Installation guide**: Installation guide should be in English, easy to follow even for non-technical users, which should include step-by-step instructions for setting up the application using Git. Will be used by persons that don't know anything about Python or web development.
- **Updates**: Provide a simple method (e.g., a script) to pull the latest changes from GitHub via Git.




