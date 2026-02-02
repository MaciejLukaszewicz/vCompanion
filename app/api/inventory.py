from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from app.core.session import require_auth
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

@router.get("/vms")
async def get_vms_partial(request: Request, q: str = "", snaps_only: bool = False):
    """Returns the VM list partial for the inventory page with filtering."""
    require_auth(request)
    if not hasattr(request.app.state, 'vcenter_manager'):
        return HTMLResponse("<p>Manager not ready</p>")
        
    all_vms = request.app.state.vcenter_manager.cache.get_all_vms()
    
    # Process VMs: Filter vCLS and apply user filters
    vms = []
    search_query = q.lower()
    
    for vm in all_vms:
        # 1. Hide system vCLS VMs
        if vm.get('name', '').startswith('vCLS'):
            continue
            
        # 2. Filter by "Snapshots only"
        if snaps_only and vm.get('snapshot_count', 0) == 0:
            continue
            
        # 3. Search Filter (Name, IP, vCenter, Host, Snapshot names)
        if search_query:
            found = False
            # Check VM Name
            if search_query in vm.get('name', '').lower(): found = True
            # Check IP
            elif vm.get('ip') and search_query in vm.get('ip', '').lower(): found = True
            # Check vCenter Name
            elif search_query in vm.get('vcenter_name', '').lower(): found = True
            # Check Host Name
            elif vm.get('host') and search_query in vm.get('host', '').lower(): found = True
            # Check Snapshot Names
            else:
                for snap in vm.get('snapshots', []):
                    if search_query in snap.get('name', '').lower():
                        found = True
                        break
            
            if not found:
                continue
        
        vms.append(vm)
    
    # Sort VMs by vCenter name first, then VM name
    vms.sort(key=lambda x: (x.get('vcenter_name', '').lower(), x.get('name', '').lower()))
    
    from main import templates
    return templates.TemplateResponse("partials/inventory_vms_list.html", {
        "request": request,
        "vms": vms
    })

@router.get("/vm-details/{vcenter_id}/{vm_id}")
async def get_vm_details(request: Request, vcenter_id: str, vm_id: str):
    """Returns the details panel for a specific VM."""
    require_auth(request)
    
    vms = request.app.state.vcenter_manager.cache.get_all_vms()
    vm = next((v for v in vms if v.get('vcenter_id') == vcenter_id and v.get('id') == vm_id), None)
    
    if not vm:
        return HTMLResponse("<div style='padding: 2rem; color: var(--text-dim);'>VM not found in cache.</div>")
    
    # Helper to format bytes to GB/TB
    def format_bytes(size_bytes):
        if size_bytes == 0: return "0 B"
        unit = ("B", "KB", "MB", "GB", "TB")
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {unit[i]}"

    # Add formatted storage info
    total_bytes = vm.get('storage_committed', 0) + vm.get('storage_uncommitted', 0)
    vm['total_storage_formatted'] = format_bytes(total_bytes)
    vm['vram_formatted'] = f"{vm.get('vram_mb', 0) / 1024:.2f} GB" if vm.get('vram_mb', 0) >= 1024 else f"{vm.get('vram_mb', 0)} MB"
    
    from main import templates
    return templates.TemplateResponse("partials/inventory_vm_details.html", {
        "request": request,
        "vm": vm
    })

@router.get("/hosts")
async def get_hosts_partial(request: Request):
    """Returns the Hosts list partial."""
    require_auth(request)
    hosts = request.app.state.vcenter_manager.cache.get_all_hosts()
    hosts.sort(key=lambda x: x.get('name', '').lower())
    
    from main import templates
    return templates.TemplateResponse("partials/inventory_hosts_list.html", {
        "request": request,
        "hosts": hosts
    })
