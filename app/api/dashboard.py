from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from app.core.session import require_auth
from app.services.vcenter_service import VCenterManager
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_stats(request: Request):
    """
    Get dashboard statistics.
    Returns VM counts, snapshots, clusters, and alerts.
    """
    require_auth(request)
    
    try:
        # Get vCenter manager from app state
        if not hasattr(request.app.state, 'vcenter_manager'):
            return JSONResponse({
                "error": "Not connected to vCenter. Please refresh your session."
            }, status_code=503)
        
        vcenter_manager = request.app.state.vcenter_manager
        
        # Get real stats from vCenter
        stats_data = vcenter_manager.get_stats()
        
        # Format for display
        stats = {
            "total_vms": f"{stats_data['total_vms']:,}" if isinstance(stats_data['total_vms'], int) else stats_data['total_vms'],
            "vms_delta": f"{stats_data['powered_on_vms']} powered on" if stats_data.get('has_data') else "No data",
            "snapshots": str(stats_data['snapshot_count']),
            "snapshots_delta": f"{stats_data['snapshot_count']} active" if stats_data.get('has_data') else "No data",
            "clusters": str(stats_data['host_count']),
            "clusters_status": f"{stats_data['host_count']} host(s)" if stats_data.get('has_data') else "No data",
            "alerts": "0",
            "alerts_status": "No critical alerts"
        }
        
        return JSONResponse(stats)
        
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {str(e)}")
        return JSONResponse({
            "total_vms": "Error",
            "vms_delta": "Unable to fetch data",
            "snapshots": "--",
            "snapshots_delta": "Error",
            "clusters": "--",
            "clusters_status": "Error",
            "alerts": "--",
            "alerts_status": str(e)
        }, status_code=500)


@router.get("/charts/resources")
async def get_resource_charts(request: Request):
    """
    Get resource consumption chart data.
    Returns CPU and RAM usage over time.
    """
    require_auth(request)
    
    if hasattr(request.app.state, 'vcenter_manager'):
        vcenter_manager = request.app.state.vcenter_manager
        stats_data = vcenter_manager.get_stats()
        history = stats_data.get("performance_history", {})
        
        return JSONResponse({
            "cpu": history.get("cpu", [0]*12),
            "ram": history.get("ram", [0]*12),
            "time_labels": history.get("labels", ["--:--"]*12)
        })
    
    return JSONResponse({
        "cpu": [0]*12,
        "ram": [0]*12,
        "time_labels": ["--:--"]*12
    })


@router.get("/charts/os-distribution")
async def get_os_distribution(request: Request):
    """
    Get VM distribution by operating system.
    """
    require_auth(request)
    
    try:
        if not hasattr(request.app.state, 'vcenter_manager'):
            return JSONResponse({"error": "Not connected"}, status_code=503)
        
        vcenter_manager = request.app.state.vcenter_manager
        stats_data = vcenter_manager.get_stats()
        
        os_dist = stats_data.get('os_distribution', {})
        
        os_data = {
            "labels": list(os_dist.keys()),
            "values": list(os_dist.values())
        }
        
        return JSONResponse(os_data)
        
    except Exception as e:
        logger.error(f"Error fetching OS distribution: {str(e)}")
        return JSONResponse({
            "labels": ["Linux", "Windows", "Other"],
            "values": [0, 0, 0]
        })


@router.get("/events")
async def get_events(request: Request, limit: int = 10):
    """
    Get recent critical events from vCenter.
    """
    require_auth(request)
    
    # We could fetch events from vCenterManager as well in the future
    events = [
        {
            "description": "Infrastructure status updated",
            "vcenter": "System",
            "target": "vCompanion",
            "severity": "success",
            "time": datetime.now().strftime("%H:%M")
        }
    ]
    
    return JSONResponse(events)
