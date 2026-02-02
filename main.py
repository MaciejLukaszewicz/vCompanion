from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from app.api import auth, dashboard, vcenters
from app.core.session import is_authenticated
from app.core.config import settings
import uvicorn
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("vCompanion starting up...")
    yield
    # Shutdown
    if hasattr(app.state, 'vcenter_manager'):
        logger.info("Stopping background worker and locking cache...")
        app.state.vcenter_manager.disconnect_all()
    logger.info("vCompanion shutting down...")

app = FastAPI(
    title=settings.app_settings.title,
    lifespan=lifespan
)

# Add session middleware
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
app.include_router(vcenters.router)

def get_vcenter_status(request: Request):
    """Helper to get vCenter connection status for templates."""
    if hasattr(request.app.state, 'vcenter_manager'):
        return request.app.state.vcenter_manager.get_connection_status()
    
    connected_ids = request.session.get("connected_vcenters", [])
    return [{
        "id": vc.id,
        "name": vc.name,
        "host": vc.host,
        "connected": vc.id in connected_ids,
        "refresh_status": "READY",
        "seconds_until": 0
    } for vc in settings.vcenters]

@app.get("/login")
async def login_page(request: Request):
    """Display login page."""
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "vcenters": [{"id": vc.id, "name": vc.name, "host": vc.host} for vc in settings.vcenters]
    })

@app.get("/")
async def index(request: Request):
    """Main dashboard page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    
    # Manager check is now part of is_authenticated logic
    vcenter_manager = request.app.state.vcenter_manager
    stats_data = vcenter_manager.get_stats()
    has_data = stats_data.get('has_data', False)
    
    # Check if stats returned 'Locked' (shouldn't happen if is_authenticated passes, but for safety)
    total_vms = stats_data['total_vms']
    if total_vms == "Locked":
         return RedirectResponse(url="/login", status_code=303)

    stats = {
        'total_vms': f"{total_vms:,}" if isinstance(total_vms, int) else total_vms,
        'vms_delta': f"{stats_data['powered_on_vms']} powered on" if has_data else "No data",
        'snapshots': str(stats_data['snapshot_count']),
        'snapshots_delta': f"{stats_data['snapshot_count']} active" if has_data else "No data",
        'clusters': str(stats_data['host_count']),
        'clusters_status': f"{stats_data['host_count']} host(s)" if has_data else "No data",
        'alerts': '0' if has_data else "N/A",
        'alerts_status': 'No critical alerts' if has_data else "No data"
    }
    
    os_data = {"labels": [], "values": []}
    os_dist = stats_data.get('os_distribution', {})
    if os_dist:
        os_data = {
            "labels": list(os_dist.keys()),
            "values": list(os_dist.values())
        }
        
    chart_data = {
        "cpu": [0] * 12,
        "ram": [0] * 12,
        "time_labels": ["00:00"] * 12
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "username": request.session.get("username"),
        "active_page": "dashboard",
        "vcenter_count": len(settings.vcenters),
        "vcenter_status": get_vcenter_status(request),
        "stats": stats,
        "per_vcenter_stats": stats_data.get('per_vcenter', {}),
        "events": [],
        "chart_data": chart_data,
        "os_data": os_data
    })

@app.get("/restoring")
async def restoring(request: Request):
    """Restoration page - in current model it usually redirects to / or login."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("restoring.html", {
        "request": request,
        "username": request.session.get("username")
    })

@app.get("/inventory")
async def inventory(request: Request):
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
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("reports.html", {
        "request": request,
        "username": request.session.get("username"),
        "active_page": "reports",
        "vcenter_status": get_vcenter_status(request)
    })

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
