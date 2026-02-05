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
    
    # Assign color index based on stable hash of vcenter_id
    def get_vc_color(vc_id):
        import hashlib
        return int(hashlib.md5(vc_id.encode()).hexdigest(), 16) % 5

    for vm in vms:
        vm['vc_color_index'] = get_vc_color(vm.get('vcenter_id', ''))

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
    hosts.sort(key=lambda x: (x.get('vcenter_name', '').lower(), x.get('name', '').lower()))
    
    # Assign color index based on stable hash of vcenter_id
    def get_vc_color(vc_id):
        import hashlib
        return int(hashlib.md5(vc_id.encode()).hexdigest(), 16) % 5

    for host in hosts:
        host['vc_color_index'] = get_vc_color(host.get('vcenter_id', ''))

    from main import templates
    return templates.TemplateResponse("partials/inventory_hosts_list.html", {
        "request": request,
        "hosts": hosts
    })

@router.get("/host-details/{vcenter_id}/{mo_id}")
async def get_host_details(request: Request, vcenter_id: str, mo_id: str):
    """Returns the details panel for a specific ESXi Host."""
    require_auth(request)
    
    hosts = request.app.state.vcenter_manager.cache.get_all_hosts()
    host = next((h for h in hosts if h.get('vcenter_id') == vcenter_id and h.get('mo_id') == mo_id), None)
    
    if not host:
        return HTMLResponse("<div style='padding: 2rem; color: var(--text-dim);'>Host not found in cache.</div>")
    
    # 1. Split FQDN
    name = host.get('name', '')
    parts = name.split('.')
    host['hostname'] = parts[0]
    host['domain'] = '.'.join(parts[1:]) if len(parts) > 1 else ""

    # 2. Calculate Uptime
    from datetime import datetime, timezone
    boot_time_str = host.get('boot_time')
    if boot_time_str:
        try:
            # boot_time_str is ISO format from isoformat()
            boot_time = datetime.fromisoformat(boot_time_str)
            # Ensure it has timezone info if now() has it, or strip both
            if boot_time.tzinfo:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()
                
            uptime_delta = now - boot_time
            days = uptime_delta.days
            if days > 0:
                hours = uptime_delta.seconds // 3600
                host['uptime_formatted'] = f"{days}d {hours}h"
            else:
                hours = uptime_delta.seconds // 3600
                minutes = (uptime_delta.seconds % 3600) // 60
                host['uptime_formatted'] = f"{hours}h {minutes}m"
            
            if uptime_delta.total_seconds() < 0:
                host['uptime_formatted'] = "Just booted"
        except Exception as e:
            logger.error(f"Uptime calc error: {e}")
            host['uptime_formatted'] = "Error calculating"
    else:
        host['uptime_formatted'] = "N/A"

    # 3. Memory & CPU Formatting
    mem_total = host.get('memory_total_mb', 0)
    host['memory_total_formatted'] = f"{mem_total / 1024:.2f} GB" if mem_total >= 1024 else f"{mem_total} MB"
    host['memory_usage_formatted'] = f"{host.get('memory_usage_mb', 0) / 1024:.2f} GB"
    
    from main import templates
    return templates.TemplateResponse("partials/inventory_host_details.html", {
        "request": request,
        "host": host
    })
@router.get("/snapshots")
async def get_snapshots_partial(request: Request, today_only: bool = False):
    """Returns a global list of snapshots across all vCenters."""
    require_auth(request)
    if not hasattr(request.app.state, 'vcenter_manager'):
        return HTMLResponse("<p>Manager not ready</p>")
        
    vms = request.app.state.vcenter_manager.cache.get_all_vms()
    
    global_snapshots = []
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Assign color index based on stable hash of vcenter_id
    def get_vc_color(vc_id):
        import hashlib
        return int(hashlib.md5(vc_id.encode()).hexdigest(), 16) % 5

    # Calculate age in days
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    for vm in vms:
        if vm.get('snapshots'):
            for snap in vm['snapshots']:
                created_date_str = snap.get('created', '')
                try:
                    # Parse created date
                    created_date_dt = datetime.fromisoformat(created_date_str)
                    # Convert to UTC if it has tz info, else assume UTC for calculation
                    if created_date_dt.tzinfo is None:
                        created_date_dt = created_date_dt.replace(tzinfo=timezone.utc)
                    
                    age_delta = now - created_date_dt
                    age_days = age_delta.days
                except:
                    age_days = 0

                created_date = created_date_str.split('T')[0]
                if today_only and created_date != today_str:
                    continue
                    
                global_snapshots.append({
                    "vm_id": vm.get('id'),
                    "vm_name": vm.get('name'),
                    "vcenter_id": vm.get('vcenter_id'),
                    "vcenter_name": vm.get('vcenter_name'),
                    "vc_color_index": get_vc_color(vm.get('vcenter_id', '')),
                    "name": snap.get('name'),
                    "description": snap.get('description'),
                    "created": snap.get('created'),
                    "age_days": age_days
                })
                
    # Sort by creation date (newest first)
    global_snapshots.sort(key=lambda x: x.get('created', ''), reverse=True)
    
    from main import templates
    return templates.TemplateResponse("partials/snapshots_table.html", {
        "request": request,
        "global_snapshots": global_snapshots,
        "snap_count": len(global_snapshots)
    })
