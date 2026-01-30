from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.core.session import (
    set_session_credentials, 
    clear_session, 
    get_session_credentials,
    set_connected_vcenters,
    is_authenticated
)
from app.core.config import settings
from app.services.vcenter_service import VCenterManager
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Resolve templates directory relative to project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    selected_vcenters: str = Form(None)  # Comma-separated vCenter IDs or None for all
):
    """
    Authenticate user with vCenter credentials.
    Attempts to connect to selected vCenters or all if not specified.
    """
    try:
        # Parse selected vCenter IDs
        vcenter_ids = None
        if selected_vcenters:
            vcenter_ids = [vc_id.strip() for vc_id in selected_vcenters.split(',') if vc_id.strip()]
        
        # Create VCenterManager
        vcenter_manager = VCenterManager(settings.vcenters)
        
        # Attempt to connect to selected or all vCenters
        logger.info(f"Login attempt for user: {username}, selected vCenters: {vcenter_ids or 'all'}")
        connection_results = vcenter_manager.connect_all(username, password, vcenter_ids)
        
        # Check if at least one vCenter connected successfully
        successful_connections = [vc_id for vc_id, success in connection_results.items() if success]
        
        if not successful_connections:
            logger.warning(f"Login failed for user {username}: No successful vCenter connections")
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "Authentication failed. Could not connect to any vCenter server. Please check your credentials.",
                    "vcenters": [{"id": vc.id, "name": vc.name, "host": vc.host} for vc in settings.vcenters]
                }
            )
        
        # Store credentials in session
        set_session_credentials(request, username, password)
        set_connected_vcenters(request, successful_connections)
        
        # Log partial connection failures
        failed_connections = [vc_id for vc_id, success in connection_results.items() if not success]
        if failed_connections:
            logger.warning(f"User {username} connected to {len(successful_connections)} vCenter(s), but failed to connect to: {', '.join(failed_connections)}")
        
        # Store manager in app state for reuse
        request.app.state.vcenter_manager = vcenter_manager
        
        # Redirect to dashboard
        return RedirectResponse(url="/", status_code=303)
        
    except Exception as e:
        logger.error(f"Login error for user {username}: {str(e)}")
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
    """
    Log out user and clear session.
    """
    username = request.session.get("username", "unknown")
    
    # Disconnect from vCenters
    if hasattr(request.app.state, 'vcenter_manager'):
        try:
            request.app.state.vcenter_manager.disconnect_all()
            logger.info(f"Disconnected vCenters for user: {username}")
        except Exception as e:
            logger.error(f"Error disconnecting vCenters: {str(e)}")
        
        # Remove manager from app state
        delattr(request.app.state, 'vcenter_manager')
    
    # Clear session
    clear_session(request)
    logger.info(f"User logged out: {username}")
    
    # Redirect to login page
    return RedirectResponse(url="/login", status_code=303)


@router.post("/login-additional")
async def login_additional(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    selected_vcenters: str = Form(...)  # Comma-separated vCenter IDs
):
    """
    Login to additional vCenters without affecting existing connections.
    """
    try:
        # Check if already authenticated
        if not is_authenticated(request):
            return JSONResponse(
                {"success": False, "error": "Not authenticated"},
                status_code=401
            )
        
        # Parse selected vCenter IDs
        vcenter_ids = [vc_id.strip() for vc_id in selected_vcenters.split(',') if vc_id.strip()]
        
        if not vcenter_ids:
            return JSONResponse(
                {"success": False, "error": "No vCenters selected"},
                status_code=400
            )
        
        # Get or create VCenterManager
        if not hasattr(request.app.state, 'vcenter_manager'):
            request.app.state.vcenter_manager = VCenterManager(settings.vcenters)
        
        vcenter_manager = request.app.state.vcenter_manager
        
        # Connect to selected vCenters
        logger.info(f"Additional login attempt for user: {username}, vCenters: {vcenter_ids}")
        connection_results = vcenter_manager.connect_selected(username, password, vcenter_ids)
        
        # Update session with new connections
        successful_connections = [vc_id for vc_id, success in connection_results.items() if success]
        if successful_connections:
            set_connected_vcenters(request, successful_connections, merge=True)
            logger.info(f"User {username} connected to {len(successful_connections)} additional vCenter(s)")
        
        # Get updated status
        status = vcenter_manager.get_connection_status()
        
        return JSONResponse({
            "success": len(successful_connections) > 0,
            "connected": successful_connections,
            "failed": [vc_id for vc_id, success in connection_results.items() if not success],
            "status": status
        })
        
    except Exception as e:
        logger.error(f"Additional login error: {str(e)}")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500
        )


@router.get("/vcenter-status")
async def vcenter_status(request: Request):
    """
    Get connection status for all configured vCenters.
    """
    try:
        if not is_authenticated(request):
            return JSONResponse(
                {"authenticated": False},
                status_code=401
            )
        
        # Get connected vCenter IDs from session
        connected_ids = get_session_credentials(request)
        connected_vcenter_ids = request.session.get("connected_vcenters", [])
        
        # Build status list
        status = []
        for vc in settings.vcenters:
            status.append({
                "id": vc.id,
                "name": vc.name,
                "host": vc.host,
                "connected": vc.id in connected_vcenter_ids
            })
        
        return JSONResponse({
            "authenticated": True,
            "vcenters": status
        })
        
    except Exception as e:
        logger.error(f"Error getting vCenter status: {str(e)}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


@router.get("/status")
async def auth_status(request: Request):
    """
    Check authentication status.
    """
    authenticated = is_authenticated(request)
    
    if authenticated:
        credentials = get_session_credentials(request)
        username = credentials[0] if credentials else None
        
        return JSONResponse({
            "authenticated": True,
            "username": username,
            "connected_vcenters": request.session.get("connected_vcenters", [])
        })
    
    return JSONResponse({
        "authenticated": False
    })


@router.post("/restore-session")
async def restore_session(request: Request):
    """
    Restore vCenter connections based on session credentials.
    Called by the 'restoring' page via HTMX.
    """
    if not is_authenticated(request):
        return Response(headers={"HX-Redirect": "/login"})
    
    credentials = get_session_credentials(request)
    if not credentials:
        return Response(headers={"HX-Redirect": "/login"})
    
    username, password = credentials
    vcenter_ids = request.session.get("connected_vcenters", [])
    
    logger.info(f"Restoring session connections for user: {username}")
    
    # Initialize manager if needed
    if not hasattr(request.app.state, 'vcenter_manager'):
        request.app.state.vcenter_manager = VCenterManager(settings.vcenters)
    
    vcenter_manager = request.app.state.vcenter_manager
    results = vcenter_manager.connect_all(username, password, vcenter_ids)
    
    # Update session with actually connected vCenters
    successful_vcs = [vc_id for vc_id, success in results.items() if success]
    set_connected_vcenters(request, successful_vcs)
    
    if not successful_vcs:
        logger.warning(f"Session restoration failed for user {username}: No vCenter connected.")
    
    # Return redirect header for HTMX
    return Response(headers={"HX-Redirect": "/"})
