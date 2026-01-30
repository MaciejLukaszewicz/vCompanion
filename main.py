from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from app.api import auth, dashboard
from app.core.session import is_authenticated, get_session_credentials
from app.core.config import settings
import uvicorn
import secrets
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="vCompanion")

# Add session middleware
# Using a fixed secret key to prevent session invalidation during dev reloads
SECRET_KEY = "vcompanion-secret-key-change-this-in-production"
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Resolve base directory
BASE_DIR = Path(__file__).resolve().parent

# Mount static files
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Templates
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Include routers
app.include_router(auth.router)
app.include_router(dashboard.router)



def get_vcenter_status(request: Request):
    """Helper to get vCenter connection status for templates."""
    # If manager exists, get real-time status
    if hasattr(request.app.state, 'vcenter_manager'):
        return request.app.state.vcenter_manager.get_connection_status()
    
    # Otherwise fallback to session-based status (e.g. before reconnection)
    connected_ids = request.session.get("connected_vcenters", [])
    return [{
        "id": vc.id,
        "name": vc.name,
        "host": vc.host,
        "connected": vc.id in connected_ids
    } for vc in settings.vcenters]


@app.get("/login")
async def login_page(request: Request):
    """Display login page."""
    # If already authenticated, redirect to dashboard
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "vcenters": [{"id": vc.id, "name": vc.name, "host": vc.host} for vc in settings.vcenters]
    })


@app.get("/")
async def index(request: Request):
    """Main dashboard page."""
    # Require authentication
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    
    # Get real stats if vCenter manager is available
    stats = {
        'total_vms': '---',
        'vms_delta': 'Loading...',
        'snapshots': '---',
        'snapshots_delta': 'Loading...',
        'clusters': '---',
        'clusters_status': 'Loading...',
        'alerts': '0',
        'alerts_status': 'No alerts'
    }
    
    events = []
    
    # Prepare chart/OS data with defaults
    chart_data = {
        "cpu": [45, 52, 38, 45, 19, 23, 31, 28, 43, 62, 58, 41],
        "ram": [72, 68, 65, 75, 82, 85, 78, 80, 77, 73, 75, 71],
        "time_labels": ['12am', '2am', '4am', '6am', '8am', '10am', '12pm', '2pm', '4pm', '6pm', '8pm', '10pm']
    }
    os_data = {
        "labels": ['Linux', 'Windows', 'Other'],
        "values": [540, 420, 288]
    }
    
    # Try to load real data
    try:
        # If manager is missing but we have a session, redirect to restoring page
        if not hasattr(request.app.state, 'vcenter_manager'):
            if is_authenticated(request):
                return RedirectResponse(url="/restoring", status_code=303)

        if hasattr(request.app.state, 'vcenter_manager'):
            vcenter_manager = request.app.state.vcenter_manager
            stats_data = vcenter_manager.get_stats()
            has_data = stats_data.get('has_data', False)
            
            stats = {
                'total_vms': f"{stats_data['total_vms']:,}" if isinstance(stats_data['total_vms'], int) else stats_data['total_vms'],
                'vms_delta': f"{stats_data['powered_on_vms']} powered on" if has_data else "No data",
                'snapshots': str(stats_data['snapshot_count']),
                'snapshots_delta': f"{stats_data['snapshot_count']} active" if has_data else "No data",
                'clusters': str(stats_data['host_count']),
                'clusters_status': f"{stats_data['host_count']} host(s)" if has_data else "No data",
                'alerts': '0' if has_data else "N/A",
                'alerts_status': 'No critical alerts' if has_data else "No data"
            }
            
            # Populate real chart data
            os_dist = stats_data.get('os_distribution', {})
            if os_dist:
                os_data = {
                    "labels": list(os_dist.keys()),
                    "values": list(os_dist.values())
                }
            
            # Add a success event
            events = [{
                'description': 'vCenter data loaded successfully',
                'vcenter': 'System',
                'target': 'Dashboard',
                'severity': 'success',
                'time': 'Just now'
            }]
    except Exception as e:
        logger.error(f"Error loading vCenter data: {str(e)}")
        events = [{
            'description': f"Error: {str(e)}",
            'vcenter': 'System',
            'target': 'Dashboard',
            'severity': 'warning',
            'time': 'Just now'
        }]
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "username": request.session.get("username"),
        "active_page": "dashboard",
        "vcenter_count": len(settings.vcenters),
        "vcenter_status": get_vcenter_status(request),
        "stats": stats,
        "per_vcenter_stats": stats_data.get('per_vcenter', {}) if 'stats_data' in locals() else {},
        "events": events,
        "chart_data": chart_data,
        "os_data": os_data
    })



@app.get("/restoring")
async def restoring(request: Request):
    """Loading page for session restoration."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("restoring.html", {
        "request": request,
        "username": request.session.get("username")
    })


@app.get("/inventory")
async def inventory(request: Request):
    """Inventory page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("inventory.html", {
        "request": request,
        "username": request.session.get("username"),
        "active_page": "inventory",
        "vcenter_status": get_vcenter_status(request)
    })


@app.get("/reports")
async def reports(request: Request):
    """Reports page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("reports.html", {
        "request": request,
        "username": request.session.get("username"),
        "active_page": "reports",
        "vcenter_status": get_vcenter_status(request)
    })




if __name__ == "__main__":
    logger.info("Starting vCompanion server...")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
