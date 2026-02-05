from fastapi import APIRouter, Request, Depends, Response
from fastapi.responses import JSONResponse
from app.core.session import require_auth
from app.services.vcenter_service import VCenterManager
from app.core.config import settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/stats")
async def get_stats(request: Request):
    require_auth(request)
    try:
        if not hasattr(request.app.state, 'vcenter_manager'):
            return JSONResponse({"error": "No manager"}, status_code=503)
        
        vcenter_manager = request.app.state.vcenter_manager
        stats_data = vcenter_manager.get_stats()
        
        has_data = stats_data.get('has_data', False)
        stats = {
            "total_vms": f"{stats_data['total_vms']:,}" if isinstance(stats_data['total_vms'], int) else stats_data['total_vms'],
            "vms_delta": f"{stats_data['powered_on_vms']} powered on" if has_data else "No data",
            "snapshots": str(stats_data['snapshot_count']),
            "snapshots_delta": f"{stats_data['snapshot_count']} active" if has_data else "No data",
            "clusters": str(stats_data['host_count']),
            "clusters_status": f"{stats_data['host_count']} host(s)" if has_data else "No data",
            "critical_alerts": stats_data.get('critical_alerts', 0),
            "warning_alerts": stats_data.get('warning_alerts', 0)
        }
        return JSONResponse(stats)
    except Exception as e:
        logger.error(f"Dashboard stats error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/alerts")
async def get_alerts_api(request: Request):
    require_auth(request)
    if hasattr(request.app.state, 'vcenter_manager'):
        stats_data = request.app.state.vcenter_manager.get_stats()
        return JSONResponse(stats_data.get("raw_alerts", []))
    return JSONResponse([])

@router.get("/events-table")
async def get_events_table(request: Request, filter_logon: bool = True):
    require_auth(request)
    logger.info(f"API: Received request for recent events (filter_logon={filter_logon})")
    events = []
    if hasattr(request.app.state, 'vcenter_manager'):
        # Reduced to 5 minutes as requested
        events = request.app.state.vcenter_manager.get_all_recent_events(minutes=5)
    
    if filter_logon:
        # Filter out logon/logoff events. 
        # Check for types like UserLoginSession, UserLogoutSession, and related variants.
        original_count = len(events)
        
        # Robust filtering: check if ANY of our ignored strings are in the event type name
        events = [e for e in events if not any(sub in e.get("type", "") for sub in ["UserLogin", "UserLogout"])]
        
        logger.info(f"API: Filtered out {original_count - len(events)} logon/logoff events")
    
    # Extra debug: log the unique types being returned to help diagnose
    if events:
        unique_types = set(e.get("type") for e in events)
        logger.info(f"API: Unique event types in result: {unique_types}")
        
    from main import templates
    logger.info(f"API: Returning {len(events)} events")
    return templates.TemplateResponse("partials/events_table.html", {"request": request, "events": events})

@router.get("/tasks-table")
async def get_tasks_table(request: Request, active_only: bool = False):
    require_auth(request)
    logger.info(f"API: Received request for recent tasks (active_only={active_only})")
    tasks = []
    if hasattr(request.app.state, 'vcenter_manager'):
        tasks = request.app.state.vcenter_manager.get_all_recent_tasks(minutes=30)
    
    if active_only:
        # Active only means running or queued
        tasks = [t for t in tasks if t.get("status") in ["running", "queued"]]
        
    from main import templates
    logger.info(f"API: Returning {len(tasks)} tasks")
    return templates.TemplateResponse("partials/tasks_table.html", {"request": request, "tasks": tasks})

@router.get("/alerts-table")
async def get_alerts_table(request: Request):
    require_auth(request)
    alerts = []
    if hasattr(request.app.state, 'vcenter_manager'):
        stats_data = request.app.state.vcenter_manager.get_stats()
        alerts = stats_data.get("raw_alerts", [])
    from main import templates
    return templates.TemplateResponse("partials/dashboard_alerts_table.html", {"request": request, "alerts": alerts})
