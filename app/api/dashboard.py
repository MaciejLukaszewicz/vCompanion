from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from app.core.session import require_auth, get_session_credentials
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
            "total_vms": f"{stats_data['total_vms']:,}",
            "vms_delta": f"{stats_data['powered_on_vms']} powered on",
            "snapshots": str(stats_data['snapshot_count']),
            "snapshots_delta": f"{stats_data['snapshot_count']} active",
            "clusters": str(stats_data['host_count']),
            "clusters_status": f"{stats_data['host_count']} host(s)",
            "alerts": "0",  # TODO: Implement alert detection
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
        })


@router.get("/charts/resources")
async def get_resource_charts(request: Request):
    """
    Get resource consumption chart data.
    Returns CPU and RAM usage over time.
    """
    require_auth(request)
    
    # TODO: Implement actual performance metrics retrieval
    # This requires vCenter performance API which is more complex
    # For now return mock data
    chart_data = {
        "cpu": [45, 52, 38, 45, 19, 23, 31, 28, 43, 62, 58, 41],
        "ram": [72, 68, 65, 75, 82, 85, 78, 80, 77, 73, 75, 71],
        "time_labels": ['12am', '2am', '4am', '6am', '8am', '10am', '12pm', '2pm', '4pm', '6pm', '8pm', '10pm']
    }
    
    return JSONResponse(chart_data)


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
        # Return fallback data
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
    
    # TODO: Implement actual event retrieval from vCenter
    # This would use the EventManager from vSphere API
    # For now, return basic system status
    events = [
        {
            "description": "Dashboard loaded successfully",
            "vcenter": "System",
            "target": "vCompanion",
            "severity": "success",
            "time": "Just now"
        }
    ]
    
    return JSONResponse(events)

