from contextlib import asynccontextmanager
from pathlib import Path
import logging
import uvicorn

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth, dashboard, vcenters
from app.core.session import is_authenticated
from app.core.config import settings

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

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        if request.headers.get("HX-Request"):
            return Response(
                headers={"HX-Redirect": "/login"},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
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
        "id": vc.id, "name": vc.name, "host": vc.host, "connected": vc.id in connected_ids,
        "refresh_status": "READY", "unlocked": False
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
    
    vcenter_manager = request.app.state.vcenter_manager
    stats_data = vcenter_manager.get_stats()
    has_data = stats_data.get('has_data', False)
    
    total_vms = stats_data.get('total_vms', 0)
    stats = {
        'total_vms': f"{total_vms:,}" if isinstance(total_vms, int) else total_vms,
        'vms_delta': f"{stats_data.get('powered_on_vms', 0)} powered on" if has_data else "No data",
        'snapshots': str(stats_data.get('snapshot_count', 0)),
        'snapshots_delta': f"{stats_data.get('snapshot_count', 0)} active" if has_data else "No data",
        'clusters': str(stats_data.get('host_count', 0)),
        'clusters_status': f"{stats_data.get('host_count', 0)} host(s)" if has_data else "No data",
        'critical_alerts': stats_data.get('critical_alerts', 0),
        'warning_alerts': stats_data.get('warning_alerts', 0)
    }
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "username": request.session.get("username"),
        "active_page": "dashboard",
        "vcenter_count": len(settings.vcenters),
        "vcenter_status": get_vcenter_status(request),
        "stats": stats,
        "per_vcenter_stats": stats_data.get('per_vcenter', {}),
        "alerts": stats_data.get('raw_alerts', [])
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
