from fastapi import Request, HTTPException, status
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Session configuration
SESSION_TIMEOUT_SECONDS = 3600  # 1 hour
SESSION_KEY_USERNAME = "username"
# PASSWORD IS NO LONGER STORED IN SESSION FOR SECURITY (ZERO-PASSWORD-STORAGE)
SESSION_KEY_LAST_ACTIVITY = "last_activity"
SESSION_KEY_CONNECTED_VCENTERS = "connected_vcenters"

def is_authenticated(request: Request) -> bool:
    """Check if the current session is authenticated."""
    if SESSION_KEY_USERNAME not in request.session:
        return False
    
    # Check session timeout
    last_activity = request.session.get(SESSION_KEY_LAST_ACTIVITY)
    if last_activity:
        try:
            last_activity_time = datetime.fromisoformat(last_activity)
            if datetime.now() - last_activity_time > timedelta(seconds=SESSION_TIMEOUT_SECONDS):
                logger.info("Session expired due to inactivity")
                return False
        except:
            return False
    
    # In Zero-Password-Storage, session is only valid if server has the manager and cache is unlocked
    if not hasattr(request.app.state, 'vcenter_manager'):
        return False
        
    if not request.app.state.vcenter_manager.cache.is_unlocked():
        # If server restarted, session might look alive but key is gone
        logger.warning("Session looks alive but cache is locked (server restart?).")
        return False
            
    return True

def update_session_activity(request: Request):
    """Update the last activity timestamp for the session."""
    request.session[SESSION_KEY_LAST_ACTIVITY] = datetime.now().isoformat()

def set_session_credentials(request: Request, username: str):
    """Store only username in session. Password is kept only in server RAM via VCenterManager."""
    request.session[SESSION_KEY_USERNAME] = username
    request.session[SESSION_KEY_LAST_ACTIVITY] = datetime.now().isoformat()
    request.session[SESSION_KEY_CONNECTED_VCENTERS] = []

def clear_session(request: Request):
    """Clear all session data and lock cache if manager exists."""
    if hasattr(request.app.state, 'vcenter_manager'):
        request.app.state.vcenter_manager.cache.lock()
    request.session.clear()

def require_auth(request: Request):
    """Dependency to require authentication for a route."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or server restarted. Please log in again."
        )
    update_session_activity(request)

def get_connected_vcenters(request: Request) -> list[str]:
    return request.session.get(SESSION_KEY_CONNECTED_VCENTERS, [])

def set_connected_vcenters(request: Request, vcenter_ids: list[str], merge: bool = False):
    if merge:
        existing = request.session.get(SESSION_KEY_CONNECTED_VCENTERS, [])
        combined = list(set(existing + vcenter_ids))
        request.session[SESSION_KEY_CONNECTED_VCENTERS] = combined
    else:
        request.session[SESSION_KEY_CONNECTED_VCENTERS] = vcenter_ids
