from contextlib import asynccontextmanager
from pathlib import Path
import logging
import uvicorn
import os
import sys

# 1. IMMEDIATE LOGGING CONFIGURATION
# We define this first so we can capture all imports and early logs
class ColorFormatter(logging.Formatter):
    GREY = "\x1b[38;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"
    
    LEVEL_COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, "")
        reset = self.RESET if color else ""
        fmt = f"{color}%(levelname)s:{reset} %(asctime)s - %(name)s - %(message)s"
        formatter = logging.Formatter(fmt)
        return formatter.format(record)

def configure_logging(app_settings=None):
    from app.core.config import settings
    level_name = app_settings.log_level if app_settings else settings.app_settings.log_level
    log_to_file = app_settings.log_to_file if app_settings else settings.app_settings.log_to_file
    level = getattr(logging, level_name.upper(), logging.INFO)
    
    root_logger = logging.getLogger()
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColorFormatter())
    root_logger.addHandler(console_handler)
    
    if log_to_file:
        file_handler = logging.FileHandler("log.txt")
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        root_logger.addHandler(file_handler)
    
    root_logger.setLevel(level)
    
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "watchfiles"]:
        l = logging.getLogger(logger_name)
        l.setLevel(level)
        l.propagate = True 
        for h in l.handlers[:]:
            l.removeHandler(h)

    # Always show startup success in GREEN
    orig_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    port = app_settings.port if app_settings else settings.app_settings.port
    # Note: We assume http as default local dev
    url = f"http://localhost:{port}"
    logging.getLogger("vCompanion").info(f"Application started successfully and running at {url}")
    root_logger.setLevel(orig_level)

# Run initial config
from app.core.config import settings
configure_logging()
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth, dashboard, vcenters, inventory, settings as settings_api
from app.core.session import is_authenticated, is_elevated_unlocked

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    from app.services.vcenter_service import VCenterManager
    app.state.vcenter_manager = VCenterManager(settings.vcenters)
    yield
    # Shutdown tasks
    if hasattr(app.state, 'vcenter_manager'):
        app.state.vcenter_manager.disconnect_all()

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
templates.env.globals["settings"] = settings

# Include routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(vcenters.router)
app.include_router(inventory.router)
app.include_router(settings_api.router)

def get_vcenter_status(request: Request):
    """Helper to get vCenter connection status for templates."""
    if hasattr(request.app.state, 'vcenter_manager'):
        return request.app.state.vcenter_manager.get_connection_status()
    
    connected_ids = request.session.get("connected_vcenters", [])
    return [{
        "id": vc.id, "name": vc.name, "host": vc.host, "connected": vc.id in connected_ids,
        "refresh_status": "READY", "unlocked": False
    } for vc in settings.vcenters if vc.enabled]

@app.api_route("/login", methods=["GET", "HEAD"])
async def login_page(request: Request):
    """Display login page."""
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "vcenters": [{"id": vc.id, "name": vc.name, "host": vc.host} for vc in settings.vcenters if vc.enabled]
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
        "vcenter_status": get_vcenter_status(request),
        "elevated_unlocked": is_elevated_unlocked(request)
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

@app.get("/hosts")
async def hosts_page(request: Request):
    if not is_authenticated(request): return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("hosts.html", {
        "request": request, "username": request.session.get("username"),
        "active_page": "hosts", "vcenter_status": get_vcenter_status(request)
    })

@app.get("/datastores")
async def datastores_page(request: Request):
    if not is_authenticated(request): return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("datastores.html", {
        "request": request, "username": request.session.get("username"),
        "active_page": "datastores", "vcenter_status": get_vcenter_status(request)
    })

@app.get("/performance")
async def performance_page(request: Request):
    if not is_authenticated(request): return RedirectResponse(url="/login", status_code=303)
    
    # Calculate performance stats
    vcenter_manager = request.app.state.vcenter_manager
    vms = vcenter_manager.cache.get_all_vms()
    hosts = vcenter_manager.cache.get_all_hosts()
    clusters = vcenter_manager.cache.get_all_clusters()
    
    # Calculate CPU percentage for VMs and add to dict
    for vm in vms:
        # For VMs: cpu_usage is in MHz, we need to calculate % based on allocated vCPUs
        # Typical approach: assume ~2000-3000 MHz per vCPU as baseline
        # Better: use max_cpu_mhz if available, otherwise estimate
        vcpu = vm.get('vcpu', 0)
        current_cpu = vm.get('cpu_usage', 0)
        max_cpu = vm.get('max_cpu_mhz', 0)
        
        # If max_cpu_mhz is 0 or unreliable, estimate based on vCPU count
        if max_cpu == 0 and vcpu > 0:
            max_cpu = vcpu * 2400  # Assume 2.4 GHz per vCPU
        
        vm['cpu_pct'] = (current_cpu / max_cpu * 100) if max_cpu > 0 else 0
        vm['max_cpu_mhz'] = max_cpu
    
    # Calculate CPU percentage for Hosts
    for host in hosts:
        cpu_cores = host.get('cpu_cores', 0)
        cpu_mhz = host.get('cpu_mhz', 0)
        max_cpu = cpu_cores * cpu_mhz
        current_cpu = host.get('cpu_usage_mhz', 0)
        host['cpu_pct'] = (current_cpu / max_cpu * 100) if max_cpu > 0 else 0
        host['max_cpu_mhz'] = max_cpu
    
    # Calculate percentages for Clusters
    for cluster in clusters:
        # CPU percentage
        total_cpu = cluster.get('total_cpu_mhz', 0)
        cpu_usage = cluster.get('cpu_usage_mhz', 0)
        cluster['cpu_pct'] = (cpu_usage / total_cpu * 100) if total_cpu > 0 else 0
        
        # Memory percentage
        total_mem = cluster.get('total_memory_mb', 0)
        mem_usage = cluster.get('memory_usage_mb', 0)
        cluster['mem_pct'] = (mem_usage / total_mem * 100) if total_mem > 0 else 0
        
        # Storage percentage
        storage_capacity = cluster.get('storage_capacity_gb', 0)
        storage_used = cluster.get('storage_used_gb', 0)
        cluster['storage_pct'] = (storage_used / storage_capacity * 100) if storage_capacity > 0 else 0
    
    # Top 10 VMs by CPU % (only powered on VMs)
    powered_on_vms = [vm for vm in vms if vm.get('power_state') == 'poweredOn']
    top_cpu_vms = sorted(powered_on_vms, key=lambda x: x.get('cpu_pct', 0), reverse=True)[:10]
    
    # Top 10 VMs by Memory (Guest)
    top_mem_vms = sorted(powered_on_vms, key=lambda x: x.get('mem_usage_guest', 0), reverse=True)[:10]
    
    # Top 10 Hosts by CPU %
    top_cpu_hosts = sorted(hosts, key=lambda x: x.get('cpu_pct', 0), reverse=True)[:10]
    
    # Top 10 Hosts by Memory
    top_mem_hosts = sorted(hosts, key=lambda x: x.get('memory_usage_mb', 0), reverse=True)[:10]

    return templates.TemplateResponse("performance.html", {
        "request": request, "username": request.session.get("username"),
        "active_page": "performance", "vcenter_status": get_vcenter_status(request),
        "clusters": clusters,
        "top_cpu_vms": top_cpu_vms,
        "top_mem_vms": top_mem_vms,
        "top_cpu_hosts": top_cpu_hosts,
        "top_mem_hosts": top_mem_hosts,
        "total_vms": len(powered_on_vms),
        "total_hosts": len(hosts)
    })

@app.get("/settings")
async def settings_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "username": request.session.get("username"),
        "active_page": "settings",
        "vcenter_status": get_vcenter_status(request),
        "vcenters": settings.vcenters
    })

if __name__ == "__main__":
    # IMPORTANT: If you are using --reload, exclude the 'data' directory to prevent 
    # the server from restarting every time the encrypted cache is saved!
    # CLI: uvicorn main:app --reload --reload-exclude "data/*"
    uvicorn.run("main:app", host="127.0.0.1", port=settings.app_settings.port, reload=False, log_config=None)
