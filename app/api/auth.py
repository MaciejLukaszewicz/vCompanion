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
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
templates = Jinja2Templates(directory="templates")


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """
    Authenticate user with vCenter credentials.
    Attempts to connect to all configured vCenters.
    """
    try:
        # Create VCenterManager
        vcenter_manager = VCenterManager(settings.vcenters)
        
        # Attempt to connect to all vCenters
        logger.info(f"Login attempt for user: {username}")
        connection_results = vcenter_manager.connect_all(username, password)
        
        # Check if at least one vCenter connected successfully
        successful_connections = [vc_id for vc_id, success in connection_results.items() if success]
        
        if not successful_connections:
            logger.warning(f"Login failed for user {username}: No successful vCenter connections")
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "Authentication failed. Could not connect to any vCenter server. Please check your credentials."
                }
            )
        
        # Store credentials in session
        set_session_credentials(request, username, password)
        set_connected_vcenters(request, successful_connections)
        
        # Log partial connection failures
        failed_connections = [vc_id for vc_id, success in connection_results.items() if not success]
        if failed_connections:
            logger.warning(f"User {username} connected to {len(successful_connections)} vCenter(s), but failed to connect to: {', '.join(failed_connections)}")
        else:
            logger.info(f"User {username} successfully connected to all {len(successful_connections)} vCenter(s)")
        
        # Store manager in app state for reuse (we'll implement this pattern)
        request.app.state.vcenter_manager = vcenter_manager
        
        # Redirect to dashboard
        return RedirectResponse(url="/", status_code=303)
        
    except Exception as e:
        logger.error(f"Login error for user {username}: {str(e)}")
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": f"An unexpected error occurred: {str(e)}"
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
