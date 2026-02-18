from fastapi import Request, HTTPException, status
from datetime import datetime, timedelta
from typing import Optional
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

# Session configuration
# SESSION_TIMEOUT_SECONDS is now managed via settings.app_settings.session_timeout
SESSION_KEY_USERNAME = "username"
# PASSWORD IS NO LONGER STORED IN SESSION FOR SECURITY (ZERO-PASSWORD-STORAGE)
SESSION_KEY_LAST_ACTIVITY = "last_activity"
SESSION_KEY_CONNECTED_VCENTERS = "connected_vcenters"

def is_authenticated(request: Request) -> bool:
    """Check if the current session is authenticated."""
    if SESSION_KEY_USERNAME not in request.session:
        return False
    
    username = request.session.get(SESSION_KEY_USERNAME)
    
    # Check session timeout
    last_activity = request.session.get(SESSION_KEY_LAST_ACTIVITY)
    if last_activity:
        try:
            last_activity_time = datetime.fromisoformat(last_activity)
            timeout = settings.app_settings.session_timeout
            if datetime.now() - last_activity_time > timedelta(seconds=timeout):
                logger.info(f"Session for user '{username}' expired due to inactivity ({timeout}s)")
                request.session.clear()  # Invalidate stale cookie immediately
                return False
        except Exception as e:
            logger.error(f"Error parsing session activity for '{username}': {e}")
            request.session.clear()
            return False
    
    # In Zero-Password-Storage, session is only valid if server has the manager and cache is unlocked
    manager = getattr(request.app.state, 'vcenter_manager', None)
    if not manager:
        # This usually means the server restarted and the manager was lost
        logger.warning(f"Auth failed for '{username}': vcenter_manager missing from app state (Server restart?)")
        return False
        
    if not manager.cache.is_unlocked():
        # If server restarted, session might look alive but key is gone (Zero-Password-Storage)
        logger.warning(f"Auth failed for '{username}': Cache is locked. Key likely lost during restart.")
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
