from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from app.core.session import is_authenticated
from app.core.config import settings
import logging

router = APIRouter(prefix="/api/vcenters")
logger = logging.getLogger(__name__)

@router.get("/status-bar")
async def get_status_bar(request: Request):
    """Returns the partial HTML for the vCenter status bar."""
    if not is_authenticated(request):
        return Response(status_code=401)
        
    from main import templates, get_vcenter_status
    vcenter_status = get_vcenter_status(request)
    
    return templates.TemplateResponse("partials/vcenter_status_bar.html", {
        "request": request,
        "vcenter_status": vcenter_status
    })

@router.post("/refresh/{vc_id}")
async def refresh_vcenter(vc_id: str, request: Request):
    """Triggers a manual refresh for a specific vCenter."""
    if not is_authenticated(request):
        return Response(status_code=401)
        
    if hasattr(request.app.state, 'vcenter_manager'):
        vcenter_manager = request.app.state.vcenter_manager
        vcenter_manager.trigger_refresh(vc_id)
        return Response(status_code=200)
    
    return Response(status_code=400)

@router.get("/stats-cards")
async def get_stats_cards(request: Request):
    """Returns the partial HTML for the dashboard stats cards."""
    if not is_authenticated(request):
        return Response(status_code=401)
        
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
        
        from main import templates
        return templates.TemplateResponse("partials/stats_grid.html", {
            "request": request,
            "stats": stats,
            "per_vcenter_stats": stats_data.get('per_vcenter', {})
        })
        
    return Response(status_code=400)
