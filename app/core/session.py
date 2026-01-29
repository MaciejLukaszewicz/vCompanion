from fastapi import Request, HTTPException, status
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Session configuration
SESSION_TIMEOUT_SECONDS = 3600  # 1 hour
SESSION_KEY_USERNAME = "username"
SESSION_KEY_PASSWORD = "password"
SESSION_KEY_LAST_ACTIVITY = "last_activity"
SESSION_KEY_CONNECTED_VCENTERS = "connected_vcenters"


def is_authenticated(request: Request) -> bool:
    """Check if the current session is authenticated."""
    if SESSION_KEY_USERNAME not in request.session:
        return False
    
    # Check session timeout
    last_activity = request.session.get(SESSION_KEY_LAST_ACTIVITY)
    if last_activity:
        last_activity_time = datetime.fromisoformat(last_activity)
        if datetime.now() - last_activity_time > timedelta(seconds=SESSION_TIMEOUT_SECONDS):
            logger.info("Session expired due to inactivity")
            return False
    
    return True


def update_session_activity(request: Request):
    """Update the last activity timestamp for the session."""
    request.session[SESSION_KEY_LAST_ACTIVITY] = datetime.now().isoformat()


def get_session_credentials(request: Request) -> Optional[tuple[str, str]]:
    """Retrieve username and password from session."""
    if not is_authenticated(request):
        return None
    
    username = request.session.get(SESSION_KEY_USERNAME)
    password = request.session.get(SESSION_KEY_PASSWORD)
    
    if username and password:
        return (username, password)
    return None


def set_session_credentials(request: Request, username: str, password: str):
    """Store credentials in session."""
    request.session[SESSION_KEY_USERNAME] = username
    request.session[SESSION_KEY_PASSWORD] = password
    request.session[SESSION_KEY_LAST_ACTIVITY] = datetime.now().isoformat()
    request.session[SESSION_KEY_CONNECTED_VCENTERS] = []


def clear_session(request: Request):
    """Clear all session data."""
    request.session.clear()


def require_auth(request: Request):
    """Dependency to require authentication for a route."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    update_session_activity(request)


def get_connected_vcenters(request: Request) -> list[str]:
    """Get list of vCenter IDs that are currently connected."""
    return request.session.get(SESSION_KEY_CONNECTED_VCENTERS, [])


def set_connected_vcenters(request: Request, vcenter_ids: list[str], merge: bool = False):
    """
    Store list of connected vCenter IDs in session.
    If merge=True, add to existing connections instead of replacing.
    """
    if merge:
        existing = request.session.get(SESSION_KEY_CONNECTED_VCENTERS, [])
        # Merge and deduplicate
        combined = list(set(existing + vcenter_ids))
        request.session[SESSION_KEY_CONNECTED_VCENTERS] = combined
    else:
        request.session[SESSION_KEY_CONNECTED_VCENTERS] = vcenter_ids


def update_vcenter_status(request: Request, vcenter_id: str, connected: bool):
    """Update connection status for a specific vCenter."""
    connected_vcenters = request.session.get(SESSION_KEY_CONNECTED_VCENTERS, [])
    
    if connected and vcenter_id not in connected_vcenters:
        connected_vcenters.append(vcenter_id)
    elif not connected and vcenter_id in connected_vcenters:
        connected_vcenters.remove(vcenter_id)
    
    request.session[SESSION_KEY_CONNECTED_VCENTERS] = connected_vcenters
