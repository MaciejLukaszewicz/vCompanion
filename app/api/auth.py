from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.core.session import (
    set_session_credentials, 
    clear_session, 
    set_connected_vcenters,
    is_authenticated
)
from app.core.config import settings
from app.services.vcenter_service import VCenterManager
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Resolve templates directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    selected_vcenters: str = Form(None)
):
    try:
        vcenter_ids = None
        if selected_vcenters:
            vcenter_ids = [vc_id.strip() for vc_id in selected_vcenters.split(',') if vc_id.strip()]
        
        # Create VCenterManager if doesn't exist
        if not hasattr(request.app.state, 'vcenter_manager'):
            request.app.state.vcenter_manager = VCenterManager(settings.vcenters)
        
        vcenter_manager = request.app.state.vcenter_manager
        
        # This will unlock cache (derive key from password) and attempt connections
        connection_results = vcenter_manager.connect_all(username, password, vcenter_ids)
        
        successful_connections = [vc_id for vc_id, result in connection_results.items() if result['success']]
        failed_connections = {vc_id: result for vc_id, result in connection_results.items() if not result['success']}
        
        if not successful_connections:
            # Analyze failures to provide helpful error message
            error_types = [result['error_type'] for result in failed_connections.values()]
            error_messages = [result['error_msg'] for result in failed_connections.values()]
            
            # Determine primary error type
            if 'auth' in error_types:
                error_msg = "Authentication failed. Please check your username and password."
            elif 'timeout' in error_types or 'network' in error_types:
                error_msg = "Connection failed. Please check your network connection or VPN."
                if len(failed_connections) > 1:
                    error_msg += f" ({len(failed_connections)} vCenter(s) unreachable)"
            elif 'ssl' in error_types:
                error_msg = "SSL certificate error. Please check vCenter SSL configuration."
            else:
                # Show first specific error message
                error_msg = error_messages[0] if error_messages else "Could not connect to any vCenter."
            
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": error_msg,
                    "vcenters": [{"id": vc.id, "name": vc.name, "host": vc.host} for vc in settings.vcenters]
                }
            )
        
        # Store only username in session (No Password!)
        set_session_credentials(request, username)
        set_connected_vcenters(request, successful_connections)
        
        return RedirectResponse(url="/", status_code=303)
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": f"An unexpected error occurred: {str(e)}",
                "vcenters": [{"id": vc.id, "name": vc.name, "host": vc.host} for vc in settings.vcenters]
            }
        )

@router.post("/logout")
async def logout(request: Request):
    username = request.session.get("username", "unknown")
    if hasattr(request.app.state, 'vcenter_manager'):
        request.app.state.vcenter_manager.disconnect_all()
    
    clear_session(request)
    return RedirectResponse(url="/login", status_code=303)

@router.post("/login-additional")
async def login_additional(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    selected_vcenters: str = Form(...)
):
    try:
        if not is_authenticated(request):
            return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)
        
        vcenter_ids = [vc_id.strip() for vc_id in selected_vcenters.split(',') if vc_id.strip()]
        vcenter_manager = request.app.state.vcenter_manager
        
        # Connect additional (cache already unlocked)
        connection_results = vcenter_manager.connect_all(username, password, vcenter_ids)
        
        successful_connections = [vc_id for vc_id, result in connection_results.items() if result['success']]
        failed_connections = {vc_id: result for vc_id, result in connection_results.items() if not result['success']}
        
        if successful_connections:
            set_connected_vcenters(request, successful_connections, merge=True)
        
        # Build error message if there were failures
        error_msg = None
        if failed_connections:
            error_parts = []
            for vc_id, result in failed_connections.items():
                vc_name = next((vc.name for vc in settings.vcenters if vc.id == vc_id), vc_id)
                error_parts.append(f"{vc_name}: {result['error_msg']}")
            error_msg = "; ".join(error_parts)
        
        return JSONResponse({
            "success": len(successful_connections) > 0,
            "connected": successful_connections,
            "failed": list(failed_connections.keys()),
            "error": error_msg,
            "status": vcenter_manager.get_connection_status()
        })
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.post("/restore-session")
async def restore_session(request: Request):
    """
    In Zero-Password-Storage, restoration is only possible if server didn't restart.
    If server restarted, is_authenticated() will return False because cache is locked.
    """
    if not is_authenticated(request):
        return Response(headers={"HX-Redirect": "/login"})
    
    # If we are here, it means server is up and cache is unlocked.
    # We just redirect to home.
    return Response(headers={"HX-Redirect": "/"})
