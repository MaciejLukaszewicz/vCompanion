from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from app.core.session import require_auth
import json
from pathlib import Path
import logging

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
logger = logging.getLogger(__name__)

@router.get("/list")
async def list_plugins(request: Request):
    require_auth(request)
    pm = getattr(request.app.state, 'plugin_manager', None)
    if not pm:
        return JSONResponse({"plugins": []})
    root = pm._plugin_root()
    plugins = []
    # enumerate manifests
    for p in root.iterdir():
        if not p.is_dir():
            continue
        m = p / 'manifest.json'
        data = {"id": p.name, "manifest": None, "loaded": False, "failed": None}
        if m.exists():
            try:
                manifest = json.loads(m.read_text())
                data['manifest'] = manifest
                data['enabled'] = manifest.get('enabled', True)
            except Exception as e:
                data['manifest_error'] = str(e)
        data['loaded'] = p.name in pm.plugins
        if p.name in pm.failed:
            data['failed'] = pm.failed.get(p.name)
        plugins.append(data)
    return JSONResponse({"plugins": plugins})

@router.post("/enable/{plugin_id}")
async def enable_plugin(request: Request, plugin_id: str):
    require_auth(request)
    pm = getattr(request.app.state, 'plugin_manager', None)
    if not pm:
        raise HTTPException(status_code=500, detail="Plugin manager not available")
    root = pm._plugin_root()
    p = root / plugin_id
    manifest_path = p / 'manifest.json'
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Plugin manifest not found")
    try:
        manifest = json.loads(manifest_path.read_text())
        manifest['enabled'] = True
        manifest_path.write_text(json.dumps(manifest, indent=2))
        await pm.load_plugin(plugin_id)
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"Enable plugin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/disable/{plugin_id}")
async def disable_plugin(request: Request, plugin_id: str):
    require_auth(request)
    pm = getattr(request.app.state, 'plugin_manager', None)
    if not pm:
        raise HTTPException(status_code=500, detail="Plugin manager not available")
    root = pm._plugin_root()
    p = root / plugin_id
    manifest_path = p / 'manifest.json'
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Plugin manifest not found")
    try:
        manifest = json.loads(manifest_path.read_text())
        manifest['enabled'] = False
        manifest_path.write_text(json.dumps(manifest, indent=2))
        # if loaded, unload
        if plugin_id in pm.plugins:
            await pm.unload_plugin(plugin_id)
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"Disable plugin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/set/{plugin_id}")
async def set_plugin_enabled(request: Request, plugin_id: str):
    """Sets plugin enabled state from a form post (checkbox)."""
    require_auth(request)
    form = await request.form()
    enabled = 'enabled' in form

    pm = getattr(request.app.state, 'plugin_manager', None)
    if not pm:
        raise HTTPException(status_code=500, detail="Plugin manager not available")

    root = pm._plugin_root()
    p = root / plugin_id
    manifest_path = p / 'manifest.json'
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Plugin manifest not found")

    try:
        manifest = json.loads(manifest_path.read_text())
        manifest['enabled'] = bool(enabled)
        manifest_path.write_text(json.dumps(manifest, indent=2))

        if enabled:
            await pm.load_plugin(plugin_id)
        else:
            if plugin_id in pm.plugins:
                await pm.unload_plugin(plugin_id)

        return JSONResponse({"ok": True, "enabled": enabled})
    except Exception as e:
        logger.error(f"Set plugin enabled error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
