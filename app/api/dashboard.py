from fastapi import APIRouter, Request, Depends, Response
from fastapi.responses import JSONResponse
from app.core.session import require_auth
from app.services.vcenter_service import VCenterManager
from app.core.config import settings
from datetime import datetime, timedelta
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
        # Create a copy to avoid modifying the cached data
        alerts = list(stats_data.get("raw_alerts", []))
    
    # Process alerts: Sort by time descending and add 'recent' flag
    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)
    one_day_ago = now - timedelta(days=1)
    
    processed_alerts = []
    
    stats = {
        "last_day": 0,
        "last_week": 0
    }
    
    logger.info(f"Processing {len(alerts)} alerts for dashboard table...")
    
    for alert in alerts:
        # Clone dict to avoid modifying reference
        a = alert.copy()
        raw_time = a.get("time", "")
        
        try:
            # Parse time for sorting and comparison
            t_str = raw_time
            if t_str and t_str.endswith('Z'): t_str = t_str[:-1]
            
            t_dt = datetime.fromisoformat(t_str)
            
            if t_dt.tzinfo is not None:
                t_dt = t_dt.replace(tzinfo=None)
                
            a["_dt"] = t_dt
            # Highlight logic changed to 7 days (last week)
            a["is_recent"] = t_dt > seven_days_ago
            
            # Stats calculation
            if t_dt > one_day_ago:
                stats["last_day"] += 1
            if t_dt > seven_days_ago:
                stats["last_week"] += 1
            
        except Exception as e:
            logger.error(f"Failed to parse alert time '{raw_time}': {e}")
            a["_dt"] = datetime.min
            a["is_recent"] = False
            
        processed_alerts.append(a)
    
    # Sort by datetime object descending
    processed_alerts.sort(key=lambda x: x["_dt"], reverse=True)
    
    if processed_alerts:
        logger.info(f"Stats: {stats}")
    
    from main import templates
    return templates.TemplateResponse("partials/dashboard_alerts_table.html", {
        "request": request, 
        "alerts": processed_alerts,
        "stats": stats
    })
