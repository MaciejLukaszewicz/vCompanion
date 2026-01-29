from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from app.api import auth, dashboard
from app.core.session import is_authenticated
from app.core.config import settings
import uvicorn
import secrets
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="vCompanion")

# Add session middleware
# In production, use a secure secret key from environment variable
SECRET_KEY = secrets.token_urlsafe(32)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth.router)
app.include_router(dashboard.router)



@app.get("/login")
async def login_page(request: Request):
    """Display login page."""
    # If already authenticated, redirect to dashboard
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse("login.html", {"request": request})


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
    
    # Try to load real data
    try:
        if hasattr(request.app.state, 'vcenter_manager'):
            vcenter_manager = request.app.state.vcenter_manager
            stats_data = vcenter_manager.get_stats()
            
            stats = {
                'total_vms': f"{stats_data['total_vms']:,}",
                'vms_delta': f"{stats_data['powered_on_vms']} powered on",
                'snapshots': str(stats_data['snapshot_count']),
                'snapshots_delta': f"{stats_data['snapshot_count']} active",
                'clusters': str(stats_data['host_count']),
                'clusters_status': f"{stats_data['host_count']} host(s)",
                'alerts': '0',
                'alerts_status': 'No critical alerts'
            }
            
            # Add a simple event
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
            'description': 'Error loading vCenter data',
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
        "stats": stats,
        "events": events
    })



@app.get("/inventory")
async def inventory(request: Request):
    """Inventory page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("inventory.html", {
        "request": request,
        "username": request.session.get("username"),
        "active_page": "inventory"
    })


@app.get("/reports")
async def reports(request: Request):
    """Reports page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("reports.html", {
        "request": request,
        "username": request.session.get("username"),
        "active_page": "reports"
    })




if __name__ == "__main__":
    logger.info("Starting vCompanion server...")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
