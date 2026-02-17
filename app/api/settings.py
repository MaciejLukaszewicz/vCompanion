from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from app.core.session import require_auth
from app.core.config import settings, save_config, VCenterConfig
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

@router.get("/vcenters")
async def get_vcenters_list(request: Request):
    """Returns the vCenter list partial for settings."""
    require_auth(request)
    from main import templates
    return templates.TemplateResponse("partials/settings_vcenters.html", {
        "request": request,
        "vcenters": settings.vcenters
    })

@router.post("/vcenters/add")
async def add_vcenter(
    request: Request,
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(443),
    verify_ssl: bool = Form(False),
    refresh_interval: int = Form(None)
):
    """Adds a new vCenter to the configuration."""
    require_auth(request)
    
    # Generate a unique ID if not provided or just use a slug from name
    new_id = str(uuid.uuid4())[:8]
    
    new_vc = VCenterConfig(
        id=new_id,
        name=name,
        host=host,
        port=port,
        verify_ssl=verify_ssl,
        refresh_interval=refresh_interval
    )
    
    settings.vcenters.append(new_vc)
    save_config(settings)
    
    # After saving, we should also update the VCenterManager if it exists
    if hasattr(request.app.state, 'vcenter_manager'):
        manager = request.app.state.vcenter_manager
        from app.services.vcenter_service import VCenterConnection
        manager.connections[new_id] = VCenterConnection(new_vc)
        manager.configs.append(new_vc)
        manager._last_refresh_trigger[new_id] = 0
    
    from main import templates
    return templates.TemplateResponse("partials/settings_vcenters.html", {
        "request": request,
        "vcenters": settings.vcenters,
        "success_msg": f"vCenter '{name}' added successfully."
    })

@router.post("/vcenters/delete/{vc_id}")
async def delete_vcenter(request: Request, vc_id: str):
    """Removes a vCenter from the configuration."""
    require_auth(request)
    
    original_vcenters = settings.vcenters
    settings.vcenters = [vc for vc in original_vcenters if vc.id != vc_id]
    
    if len(settings.vcenters) == len(original_vcenters):
        raise HTTPException(status_code=404, detail="vCenter not found")
    
    save_config(settings)
    
    # Update manager
    if hasattr(request.app.state, 'vcenter_manager'):
        manager = request.app.state.vcenter_manager
        if vc_id in manager.connections:
            conn = manager.connections.pop(vc_id)
            conn.disconnect()
        if vc_id in manager._last_refresh_trigger:
            manager._last_refresh_trigger.pop(vc_id)
        manager.configs = [cfg for cfg in manager.configs if cfg.id != vc_id]
    
    from main import templates
    return templates.TemplateResponse("partials/settings_vcenters.html", {
        "request": request,
        "vcenters": settings.vcenters,
        "success_msg": "vCenter removed successfully."
    })

@router.get("/vcenters/add")
async def get_add_form(request: Request):
    """Returns the clean add form for a vCenter."""
    require_auth(request)
    from main import templates
    return templates.TemplateResponse("partials/settings_vcenter_form.html", {
        "request": request,
        "vc": None,
        "mode": "add"
    })

@router.get("/vcenters/edit/{vc_id}")
async def get_edit_form(request: Request, vc_id: str):
    """Returns the edit form for a vCenter."""
    require_auth(request)
    vc = next((vc for vc in settings.vcenters if vc.id == vc_id), None)
    if not vc:
        raise HTTPException(status_code=404, detail="vCenter not found")
    
    from main import templates
    return templates.TemplateResponse("partials/settings_vcenter_form.html", {
        "request": request,
        "vc": vc,
        "mode": "edit"
    })

@router.post("/vcenters/update/{vc_id}")
async def update_vcenter(
    request: Request,
    vc_id: str,
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(443),
    verify_ssl: bool = Form(False),
    refresh_interval: int = Form(None)
):
    """Updates an existing vCenter configuration."""
    require_auth(request)
    
    vc_index = next((i for i, v in enumerate(settings.vcenters) if v.id == vc_id), None)
    if vc_index is None:
        raise HTTPException(status_code=404, detail="vCenter not found")
    
    updated_vc = VCenterConfig(
        id=vc_id,
        name=name,
        host=host,
        port=port,
        verify_ssl=verify_ssl,
        refresh_interval=refresh_interval
    )
    
    settings.vcenters[vc_index] = updated_vc
    save_config(settings)
    
    # Update manager
    if hasattr(request.app.state, 'vcenter_manager'):
        manager = request.app.state.vcenter_manager
        # If host changed, we might need to reconnect, but for now just update config
        if vc_id in manager.connections:
            # Update the config inside the existing connection object
            manager.connections[vc_id].config = updated_vc
        else:
            from app.services.vcenter_service import VCenterConnection
            manager.connections[vc_id] = VCenterConnection(updated_vc)
            
        # Update configs list
        cfg_index = next((i for i, c in enumerate(manager.configs) if c.id == vc_id), None)
        if cfg_index is not None:
            manager.configs[cfg_index] = updated_vc
        else:
            manager.configs.append(updated_vc)
    
    from main import templates
    return templates.TemplateResponse("partials/settings_vcenters.html", {
        "request": request,
        "vcenters": settings.vcenters,
        "success_msg": f"vCenter '{name}' updated successfully."
    })

@router.get("/application")
async def get_application_settings(request: Request):
    """Returns the application settings partial."""
    require_auth(request)
    from main import templates
    return templates.TemplateResponse("partials/settings_application.html", {
        "request": request,
        "app_settings": settings.app_settings
    })

@router.post("/application/update")
async def update_application_settings(
    request: Request,
    title: str = Form(...),
    refresh_interval_seconds: int = Form(...),
    log_level: str = Form(...),
    log_to_file: bool = Form(False),
    theme: str = Form(...),
    accent_color: str = "blue",
    port: int = Form(8000),
    open_browser_on_start: bool = Form(True)
):
    """Updates global application settings."""
    require_auth(request)
    settings.app_settings.title = title
    settings.app_settings.refresh_interval_seconds = refresh_interval_seconds
    settings.app_settings.log_level = log_level
    settings.app_settings.log_to_file = log_to_file
    settings.app_settings.theme = theme
    settings.app_settings.accent_color = accent_color
    settings.app_settings.port = port
    settings.app_settings.open_browser_on_start = open_browser_on_start
    save_config(settings)
    
    # Update logging configuration dynamically
    from main import configure_logging
    configure_logging(settings.app_settings)
    
    # Update manager if needed
    if hasattr(request.app.state, 'vcenter_manager'):
        request.app.state.vcenter_manager.global_refresh_interval = refresh_interval_seconds
        
    from main import templates
    return templates.TemplateResponse("partials/settings_application.html", {
        "request": request,
        "app_settings": settings.app_settings,
        "success_msg": "Application settings updated successfully."
    })

@router.get("/security")
async def get_security_settings(request: Request):
    """Returns the security settings partial."""
    require_auth(request)
    from main import templates
    return templates.TemplateResponse("partials/settings_security.html", {
        "request": request,
        "app_settings": settings.app_settings
    })

@router.post("/security/update")
async def update_security_settings(
    request: Request,
    session_timeout: int = Form(...)
):
    """Updates security-related settings."""
    require_auth(request)
    settings.app_settings.session_timeout = session_timeout
    save_config(settings)
    
    from main import templates
    return templates.TemplateResponse("partials/settings_security.html", {
        "request": request,
        "app_settings": settings.app_settings,
        "success_msg": "Security settings updated successfully."
    })

@router.post("/restart")
async def restart_server(request: Request):
    """Triggers a server restart by exiting with code 123."""
    require_auth(request)
    import os
    import threading
    import time

    logger.error("!!! RESTART INITIATED BY USER !!!")
    
    def shutdown():
        time.sleep(1)  # Give time for the response to reach the browser
        # os._exit is used to bypass uvicorn's shutdown handlers and exit immediately
        # with the code our run.bat is looking for.
        os._exit(123)

    threading.Thread(target=shutdown).start()
    return JSONResponse({
        "status": "ok", 
        "message": "Restarting server..."
    })

@router.post("/shutdown")
async def shutdown_server(request: Request):
    """Triggers a server shutdown by exiting with code 0."""
    require_auth(request)
    import os
    import threading
    import time

    logger.error("!!! SHUTDOWN INITIATED BY USER !!!")
    
    def shutdown():
        time.sleep(1)
        os._exit(0)  # Exit code 0 means normal shutdown (loop stops)

    threading.Thread(target=shutdown).start()
    return JSONResponse({
        "status": "ok", 
        "message": "Server is shutting down. You can close this window."
    })

@router.post("/security/purge-cache")
async def purge_cache(request: Request):
    """Deletes all encrypted cache files and locks the manager."""
    require_auth(request)
    import os
    from pathlib import Path
    
    # Get cache dir (data/)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    cache_dir = Path(project_root) / "data"
    
    deleted_count = 0
    if cache_dir.exists():
        for f in cache_dir.glob("*.enc"):
            try:
                os.remove(f)
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete {f}: {e}")
            
    # Lock the cache in manager
    if hasattr(request.app.state, 'vcenter_manager'):
        request.app.state.vcenter_manager.cache.lock()
        
    return JSONResponse({
        "status": "ok", 
        "message": f"Local encrypted cache purged. Deleted {deleted_count} files. Please log in again to rebuild cache."
    })
