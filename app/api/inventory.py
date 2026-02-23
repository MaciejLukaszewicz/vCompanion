from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from app.core.session import require_auth, is_elevated_unlocked
import logging
import csv
import io
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

@router.get("/vms")
async def get_vms_partial(request: Request, q: str = "", snaps_only: bool = False, selected_vm_id: str = None, selected_vcenter_id: str = None):
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
        "vms": vms,
        "selected_vm_id": selected_vm_id,
        "selected_vcenter_id": selected_vcenter_id
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
    
    # --- BUILD NETWORK TREE (Unified) ---
    network_tree = []
    network_groups = {} # (sw_name, sw_type) -> group_info
    try:
        all_nets = request.app.state.vcenter_manager.cache.get_all_networks()
        vc_nets = all_nets.get(vcenter_id, {})
        host_id = vm.get('host_id')
        host_net = next((h for h in vc_nets.get('hosts', []) if h.get('mo_id') == host_id), None)
        
        for nic in vm.get('nic_devices', []):
            pg_name = "Unknown Network"
            sw_name = "Unknown Switch"
            sw_type = "vss"
            uplinks = []
            
            backing = nic.get('backing', {})
            if backing.get('type') == 'standard':
                pg_name = backing.get('network_name', 'Unknown Network')
                if host_net:
                    pg_info = next((pg for pg in host_net.get('portgroups', []) if pg['name'] == pg_name or pg_name in pg['name']), None)
                    if pg_info:
                        sw_name = pg_info['vswitch']
                        sw_info = next((sw for sw in host_net.get('switches', []) if sw['name'] == sw_name), None)
                        if sw_info:
                            uplinks = sw_info.get('uplinks', [])
            
            elif backing.get('type') == 'distributed':
                pg_key = backing.get('portgroup_key')
                dvpg = vc_nets.get('distributed_portgroups', {}).get(pg_key)
                if dvpg:
                    pg_name = dvpg['name']
                    sw_type = 'vds'
                    dvs = next((d for d in vc_nets.get('distributed_switches', []) if pg_key in d.get('portgroups', [])), None)
                    if dvs:
                        sw_name = dvs['name']
                        if host_net:
                            sw_info = next((sw for sw in host_net.get('switches', []) if sw['type'] == 'distributed' and sw['name'] == dvs['name']), None)
                            if sw_info:
                                uplinks = sw_info.get('uplinks', [])
            
            group_key = (sw_name, sw_type)
            if group_key not in network_groups:
                network_groups[group_key] = {
                    "switch": sw_name,
                    "switch_type": sw_type,
                    "uplinks": uplinks,
                    "portgroups": {} # pg_name -> [nics]
                }
            
            if pg_name not in network_groups[group_key]["portgroups"]:
                network_groups[group_key]["portgroups"][pg_name] = []
            
            network_groups[group_key]["portgroups"][pg_name].append({
                "label": nic['label'],
                "mac": nic['mac'],
                "connected": nic['connected']
            })
        
        # Convert to list for template
        for sw_key, sw_data in network_groups.items():
            pg_list = []
            for pg_name, nics in sw_data["portgroups"].items():
                pg_list.append({"name": pg_name, "nics": nics})
            sw_data["portgroups"] = pg_list
            network_tree.append(sw_data)
    except Exception as e:
        logger.error(f"Error building network tree: {e}")
            
    # --- BUILD STORAGE TREE ---
    storage_groups = {} # (ds_name, cluster) -> group_info
    storage_tree = []
    try:
        all_storage = request.app.state.vcenter_manager.cache.get_all_storage()
        vc_storage = all_storage.get(vcenter_id, {})
        ds_map = vc_storage.get('datastores', {})
        clusters = vc_storage.get('clusters', [])
        host_storage = vc_storage.get('host_storage', {})
        
        active_host_id = vm.get('host_id')
        active_host_storage = host_storage.get(active_host_id, {})
        
        for disk in vm.get('disk_devices', []):
            ds_id = disk.get('datastore_id')
            ds_name = disk.get('datastore_name', 'Unknown Datastore')
            
            # Find cluster
            ds_cluster = None
            if ds_id:
                for cl in clusters:
                    if ds_id in cl.get('datastores', []):
                        ds_cluster = cl['name']
                        break
            
            # Simple grouping key
            group_key = (ds_name, ds_cluster)
            
            if group_key not in storage_groups:
                storage_groups[group_key] = {
                    "datastore": ds_name,
                    "cluster": ds_cluster,
                    "disks": [],
                    "hbas": [],
                    "connection_type": "Storage"
                }

            group = storage_groups[group_key]
            group['disks'].append({
                "label": disk.get('label', 'Hard Disk'),
                "capacity_gb": disk.get('capacity_gb', 0)
            })
            
            # Enrich path info once per unique Datastore ID if available
            if ds_id and not group['hbas']:
                ds_info = ds_map.get(ds_id)
                if ds_info:
                    ds_type = ds_info.get('type', 'Unknown')
                    ds_extra = ds_info.get('extra', {})
                    
                    # Connection type
                    if ds_extra.get('is_vsan'): group['connection_type'] = "vSAN Storage"
                    elif ds_extra.get('nfs_server'): group['connection_type'] = "NFS Storage"
                    elif ds_type == 'VMFS': group['connection_type'] = "VMFS Path"
                    else: group['connection_type'] = f"{ds_type} Storage"

                    # HBAs
                    if active_host_storage:
                        hbas_map = active_host_storage.get('hbas', {})
                        disk_to_hba = active_host_storage.get('disk_to_hba', {})
                        extents = ds_info.get('extents', [])
                        
                        found_hbas = {}
                        for ext in extents:
                            norm_ext = ext.split("/")[-1]
                            hba_keys = disk_to_hba.get(norm_ext, [])
                            if isinstance(hba_keys, str): hba_keys = [hba_keys]
                            for h_key in hba_keys:
                                if h_key in hbas_map:
                                    found_hbas[h_key] = hbas_map[h_key]
                        
                        group['hbas'] = list(found_hbas.values())
                        if group['hbas']:
                            types = {h['type'].upper() for h in group['hbas']}
                            group['connection_type'] = f"{'/'.join(sorted(types))} Storage"
                        
                        # Fallback for NFS/vSAN
                        if not group['hbas']:
                            if ds_extra.get('nfs_server'):
                                group['hbas'].append({
                                    "device": "NFS Client", "type": "nfs",
                                    "id": f"{ds_extra['nfs_server']}:{ds_extra['nfs_path']}"
                                })
                            elif ds_extra.get('is_vsan'):
                                group['hbas'].append({
                                    "device": "vSAN Distributed", "type": "vsan",
                                    "id": "vSAN Object Storage"
                                })
        
        storage_tree = list(storage_groups.values())
            
    except Exception as e:
        logger.error(f"Error building storage tree: {e}")

    from main import templates
    return templates.TemplateResponse("partials/inventory_vm_details.html", {
        "request": request,
        "vm": vm,
        "network_tree": network_tree,
        "storage_tree": storage_tree,
        "elevated_unlocked": is_elevated_unlocked(request)
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
        "host": host,
        "elevated_unlocked": is_elevated_unlocked(request)
    })

@router.post("/host-service")
async def toggle_host_service(request: Request):
    """
    Toggles a service on an ESXi host.
    CRITICAL: This operation requires elevated permissions (to be implemented).
    """
    require_auth(request)
    try:
        data = await request.json()
        vc_id = data.get('vcenter_id')
        mo_id = data.get('mo_id')
        service = data.get('service')
        state = data.get('state') # "start" or "stop"
        
        if not all([vc_id, mo_id, service, state]):
            raise HTTPException(status_code=400, detail="Missing required parameters")
            
        manager = request.app.state.vcenter_manager
        success = manager.toggle_host_service(vc_id, mo_id, service, start=(state == "start"))
        
        if success:
            return JSONResponse({"success": True})
        else:
            return JSONResponse({"success": False, "error": "Failed to toggle service. Check vCenter connection or host permissions."}, status_code=500)
            
    except Exception as e:
        logger.error(f"Error in host-service endpoint: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.post("/appliance-login")
async def appliance_login(request: Request):
    """Authenticates to a VCSA REST API."""
    require_auth(request)
    try:
        data = await request.json()
        vc_id = data.get('vcenter_id')
        user = data.get('username')
        pwd = data.get('password')
        
        if not all([vc_id, user, pwd]):
            raise HTTPException(status_code=400, detail="Missing credentials")
            
        manager = request.app.state.vcenter_manager
        result = manager.login_vcenter_appliance(vc_id, user, pwd)
        
        if result == "success":
            return JSONResponse({"success": True})
        
        if result == "auth_error":
            return JSONResponse({"success": False, "error": "Invalid credentials. Please check username and password."}, status_code=401)
        elif result == "network_error":
            return JSONResponse({"success": False, "error": "Communication error. Check if port 443/5480 is open to vCenter Appliance."}, status_code=503)
        else:
            return JSONResponse({"success": False, "error": f"Appliance login failed: {result}"}, status_code=500)
    except Exception as e:
        logger.error(f"Appliance login error: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.get("/vcenter-ssh-status/{vc_id}")
async def get_vcenter_ssh_status(request: Request, vc_id: str):
    """Returns the current SSH status for a vCenter appliance."""
    require_auth(request)
    manager = request.app.state.vcenter_manager
    status = manager.get_vcenter_appliance_ssh_status(vc_id)
    
    if status is None:
        return JSONResponse({"success": False, "error": "No appliance session active. Please login first."}, status_code=401)
    
    return JSONResponse({"success": True, "enabled": status})

@router.post("/vcenter-service")
async def toggle_vcenter_service(request: Request):
    """
    Toggles a service on the vCenter appliance itself.
    Privileged operation.
    """
    require_auth(request)
    try:
        data = await request.json()
        vc_id = data.get('vcenter_id')
        service = data.get('service') # e.g. "ssh"
        state = data.get('state') # "start" or "stop"
        
        if not all([vc_id, service, state]):
            raise HTTPException(status_code=400, detail="Missing required parameters")
            
        manager = request.app.state.vcenter_manager
        success = manager.toggle_vcenter_service(vc_id, service, start=(state == "start"))
        
        if success:
            return JSONResponse({"success": True})
        else:
            return JSONResponse({"success": False, "error": "Operation failed. Make sure you have an active appliance session (Get Status) and correct permissions."}, status_code=500)
            
    except Exception as e:
        logger.error(f"Error in vcenter-service endpoint: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

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
        "snap_count": len(global_snapshots),
        "elevated_unlocked": is_elevated_unlocked(request)
    })

@router.post("/snapshots/delete")
async def delete_snapshot_endpoint(request: Request):
    """Deletes a specific snapshot. Requires elevated privileges."""
    require_auth(request)
    if not is_elevated_unlocked(request):
        return JSONResponse({"success": False, "error": "Elevated privileges required"}, status_code=403)
        
    try:
        data = await request.json()
        vc_id = data.get('vcenter_id')
        vm_id = data.get('vm_id')
        snap_name = data.get('snapshot_name')
        
        if not all([vc_id, vm_id, snap_name]):
            raise HTTPException(status_code=400, detail="Missing required parameters")
            
        manager = request.app.state.vcenter_manager
        task_id = manager.remove_snapshot(vc_id, vm_id, snap_name)
        
        if task_id:
            return JSONResponse({"success": True, "task_id": task_id})
        else:
            return JSONResponse({"success": False, "error": "Failed to delete snapshot. Check logs."}, status_code=500)
    except Exception as e:
        logger.error(f"Error in delete_snapshot_endpoint: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.get("/tasks/{vcenter_id}/{task_id}")
async def get_task_status(request: Request, vcenter_id: str, task_id: str):
    """Gets the status of an ongoing task in a vCenter."""
    if not is_authenticated(request):
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
        
    try:
        manager = request.app.state.vcenter_manager
        status = manager.check_task_status(vcenter_id, task_id)
        return JSONResponse({"success": True, "status": status})
    except Exception as e:
        logger.error(f"Error checking task status: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.post("/snapshots/delete-bulk")
async def delete_snapshots_bulk_endpoint(request: Request):
    """Deletes multiple snapshots. Requires elevated privileges."""
    require_auth(request)
    if not is_elevated_unlocked(request):
        return JSONResponse({"success": False, "error": "Elevated privileges required"}, status_code=403)
        
    try:
        data = await request.json()
        snapshots = data.get('snapshots', [])
        
        if not snapshots:
            raise HTTPException(status_code=400, detail="No snapshots provided")
            
        manager = request.app.state.vcenter_manager
        results = []
        for snap in snapshots:
            vc_id = snap.get('vcenter_id')
            vm_id = snap.get('vm_id')
            snap_name = snap.get('snapshot_name')
            task_id = manager.remove_snapshot(vc_id, vm_id, snap_name)
            results.append({"vcenter_id": vc_id, "vm_id": vm_id, "snapshot_name": snap_name, "success": task_id is not None, "task_id": task_id})
            
        return JSONResponse({"success": True, "results": results})
    except Exception as e:
        logger.error(f"Error in delete_snapshots_bulk_endpoint: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.get("/export/vms")
async def export_vms_csv(request: Request, q: str = "", snaps_only: bool = False):
    """Exports the filtered VM list as a CSV file."""
    require_auth(request)
    if not hasattr(request.app.state, 'vcenter_manager'):
        raise HTTPException(status_code=503, detail="Manager not ready")
        
    all_vms = request.app.state.vcenter_manager.cache.get_all_vms()
    
    # Apply filters (same logic as /vms)
    vms = []
    search_query = q.lower()
    for vm in all_vms:
        if vm.get('name', '').startswith('vCLS'): continue
        if snaps_only and vm.get('snapshot_count', 0) == 0: continue
        if search_query:
            found = False
            if search_query in vm.get('name', '').lower(): found = True
            elif vm.get('ip') and search_query in vm.get('ip', '').lower(): found = True
            elif search_query in vm.get('vcenter_name', '').lower(): found = True
            elif vm.get('host') and search_query in vm.get('host', '').lower(): found = True
            else:
                for snap in vm.get('snapshots', []):
                    if search_query in snap.get('name', '').lower():
                        found = True
                        break
            if not found: continue
        vms.append(vm)
    
    vms.sort(key=lambda x: (x.get('vcenter_name', '').lower(), x.get('name', '').lower()))
    
    output = io.StringIO()
    # Use semicolon as separator as requested
    writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    # Headers based on inventory_vms_list.html columns
    writer.writerow(["Name", "vCenter", "Primary IP", "Status"])
    
    for vm in vms:
        writer.writerow([
            vm.get('name', ''),
            vm.get('vcenter_name', ''),
            vm.get('ip', ''),
            'ON' if vm.get('power_state') == 'poweredOn' else 'OFF'
        ])
    
    output.seek(0)
    
    filename = f"vm_{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-cache"
        }
    )

@router.get("/export/snapshots")
async def export_snapshots_csv(request: Request, today_only: bool = False):
    """Exports the global snapshots list as a CSV file."""
    require_auth(request)
    if not hasattr(request.app.state, 'vcenter_manager'):
        raise HTTPException(status_code=503, detail="Manager not ready")
        
    vms = request.app.state.vcenter_manager.cache.get_all_vms()
    
    global_snapshots = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for vm in vms:
        if vm.get('snapshots'):
            for snap in vm['snapshots']:
                created_date = snap.get('created', '').split('T')[0]
                if today_only and created_date != today_str:
                    continue
                    
                global_snapshots.append({
                    "vm_name": vm.get('name'),
                    "vcenter_name": vm.get('vcenter_name'),
                    "name": snap.get('name'),
                    "created": snap.get('created'),
                    "description": snap.get('description')
                })
                
    # Sort by creation date (newest first)
    global_snapshots.sort(key=lambda x: x.get('created', ''), reverse=True)
    
    output = io.StringIO()
    # Use semicolon as separator as requested
    writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    # Headers based on snapshots_table.html columns
    writer.writerow(["VM Name", "vCenter", "Snapshot Name", "Age (days)", "Created At", "Description"])
    
    # Calculate now once for age calculation
    now = datetime.now(timezone.utc)

    for snap in global_snapshots:
        # Calculate age days (same logic as get_snapshots_partial)
        age_days = 0
        try:
            created_date_dt = datetime.fromisoformat(snap.get('created', ''))
            if created_date_dt.tzinfo is None:
                created_date_dt = created_date_dt.replace(tzinfo=timezone.utc)
            age_delta = now - created_date_dt
            age_days = age_delta.days
        except:
            pass

        # Format created date for better CSV readability
        created_at = snap.get('created', '').replace('T', ' ').split('.')[0]
        writer.writerow([
            snap.get('vm_name', ''),
            snap.get('vcenter_name', ''),
            snap.get('name', ''),
            age_days,
            created_at,
            snap.get('description', '')
        ])
    
    output.seek(0)
    
    filename = f"snapshots_{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-cache"
        }
    )

@router.get("/vcenters")
async def get_vcenters_partial(request: Request):
    """Returns the vCenters list partial for inventory."""
    require_auth(request)
    if not hasattr(request.app.state, 'vcenter_manager'):
        return HTMLResponse("<p>Manager not ready</p>")
        
    vcenter_statuses = request.app.state.vcenter_manager.cache.get_vcenter_status()
    
    # Sort by name
    vcenter_statuses.sort(key=lambda x: x.get('name', '').lower())
    
    from main import templates
    return templates.TemplateResponse("partials/inventory_vcenters_list.html", {
        "request": request,
        "vcenters": vcenter_statuses,
        "elevated_unlocked": is_elevated_unlocked(request)
    })

@router.get("/networks")
async def get_networks_partial(request: Request):
    """Returns the Networking view (Switches & Physical)."""
    require_auth(request)
    if not hasattr(request.app.state, 'vcenter_manager'):
        return HTMLResponse("<p>Manager not ready</p>")

    cache = request.app.state.vcenter_manager.cache
    all_networks = cache.get_all_networks()
    all_vms = cache.get_all_vms()
    all_hosts = cache.get_all_hosts()

    # Pre-map VMs for faster lookup: { (vc_id, mo_id): {name, networks: []} }
    vm_map = {}
    for vm in all_vms:
        vm_map[(vm.get('vcenter_id'), vm.get('id'))] = {
            "name": vm.get('name'),
            "networks": vm.get('networks', [])
        }

    vcenter_data = []

    for vc_id, net_data in all_networks.items():
        vcenter_status = cache.get_vcenter_status(vc_id)
        vc_name = vcenter_status.get('name', vc_id) if vcenter_status else vc_id
        
        vc_structure = {
            "name": vc_name,
            "id": vc_id,
            "hosts": [],
            "distributed_switches": []
        }

        # 1. Process Distributed Switches
        dvs_list = net_data.get('distributed_switches', [])
        dvpg_map = net_data.get('distributed_portgroups', {})

        for dvs in dvs_list:
            dvs_item = {
                "name": dvs['name'],
                "mo_id": dvs['mo_id'],
                "portgroups": [],
                "uplinks": [] # Global uplinks from all hosts
            }
            
            # Find which host pnics are connected to this DVS
            # We match by DVS name (simplest)
            for host in net_data.get('hosts', []):
                for sw in host.get('switches', []):
                    if sw['type'] == 'distributed' and sw['name'] == dvs['name']:
                        for up in sw.get('uplinks', []):
                            dvs_item['uplinks'].append(f"{host['name']}:{up}")

            dvs_item['uplinks'] = sorted(list(set(dvs_item['uplinks'])))

            # Find portgroups belonging to THIS DVS
            for pg_id in dvs.get('portgroups', []):
                pg = dvpg_map.get(pg_id)
                if pg:
                    # VMs connected to this DVPG
                    connected_vms = []
                    for vm_id in pg.get('vms', []):
                        vm_info = vm_map.get((vc_id, vm_id))
                        if vm_info:
                            connected_vms.append(vm_info['name'])
                    
                    # VMkernels connected to this DVPG (check by mo_id match in dvs_port)
                    connected_vmkernels = []
                    for host in net_data.get('hosts', []):
                        for vmk in host.get('vmkernels', []):
                            if vmk.get('dvs_port') == pg_id:
                                connected_vmkernels.append(f"{host['name']}:{vmk['device']} ({vmk['ip']})")

                    dvs_item['portgroups'].append({
                        "name": pg['name'],
                        "vlan": pg['vlan'],
                        "vms": sorted(list(set(connected_vms))),
                        "vmkernels": sorted(connected_vmkernels),
                        "is_uplink": pg.get('is_uplink', False)
                    })
            
            dvs_item['portgroups'].sort(key=lambda x: x['name'].lower())
            vc_structure['distributed_switches'].append(dvs_item)

        # 2. Process Hosts (Standard Switches)
        for host in net_data.get('hosts', []):
            h_item = {
                "name": host['name'],
                "mo_id": host['mo_id'],
                "switches": [],
                "physical_uplinks": []
            }

            for sw in host.get('switches', []):
                if sw['type'] == 'standard':
                    sw_item = {
                        "name": sw['name'],
                        "uplinks": sw.get('uplinks', []),
                        "portgroups": []
                    }
                    # Portgroups for this VSS
                    for pg in host.get('portgroups', []):
                        if pg['vswitch'] == sw['name']:
                            # VMs on this host connected to this specific PG
                            pg_vms = []
                            for (vid, vmid), v_info in vm_map.items():
                                if vid == vc_id:
                                    # Since standard PGs are local to host, we must check if VM is on this host
                                    # Actually we need VM host info here too
                                    pass # Optimization: rely on vm.networks matching pg name for VMs on this host
                            
                            # Searching all VMs on this host
                            host_vms = [v for v in all_vms if v.get('vcenter_id') == vc_id and v.get('host') == host['name']]
                            pg_vms = [v['name'] for v in host_vms if pg['name'] in v.get('networks', [])]

                            pg_vmks = [f"{vmk['device']} ({vmk['ip']})" for vmk in host.get('vmkernels', []) if vmk['portgroup'] == pg['name']]

                            sw_item['portgroups'].append({
                                "name": pg['name'],
                                "vlan": pg['vlan'],
                                "vms": sorted(list(set(pg_vms))),
                                "vmkernels": sorted(pg_vmks)
                            })
                    
                    sw_item['portgroups'].sort(key=lambda x: x['name'].lower())
                    h_item['switches'].append(sw_item)
                
                # Physical Uplinks (Standard + Distributed)
                for up in sw.get('uplinks', []):
                    h_item['physical_uplinks'].append({
                        "device": up,
                        "switch": sw['name']
                    })

            vc_structure['hosts'].append(h_item)

        # Sort hosts by name
        vc_structure['hosts'].sort(key=lambda x: x['name'].lower())
        vcenter_data.append(vc_structure)

    # Sort vcenters by name
    vcenter_data.sort(key=lambda x: x['name'].lower())

    from main import templates
    return templates.TemplateResponse("partials/inventory_networks.html", {
        "request": request,
        "vcenters": vcenter_data
    })

@router.get("/storage")
async def get_storage_partial(request: Request):
    """Returns the storage topology partial."""
    require_auth(request)

    if not hasattr(request.app.state, 'vcenter_manager'):
        return HTMLResponse("<p>Manager not ready</p>")

    cache = request.app.state.vcenter_manager.cache
    all_storage = cache.get_all_storage()
    
    vcenter_data = []

    for vc_id, storage_data in all_storage.items():
        vcenter_status = cache.get_vcenter_status(vc_id)
        vc_name = vcenter_status.get('name', vc_id) if vcenter_status else vc_id
        
        vc_structure = {
            "name": vc_name,
            "id": vc_id,
            "clusters": [],
            "standalone_datastores": []
        }

        # MOID to Name mapping for hosts
        host_names = storage_data.get('host_names', {})
        ds_map = storage_data.get('datastores', {})
        
        # Track which datastores are in clusters
        ds_in_clusters = set()

        # 1. Process Datastore Clusters
        for cluster in storage_data.get('clusters', []):
            cl_item = {
                "name": cluster['name'],
                "mo_id": cluster['mo_id'],
                "capacity": cluster['capacity'],
                "free_space": cluster['free_space'],
                "datastores": []
            }
            
            for ds_id in cluster.get('datastores', []):
                ds = ds_map.get(ds_id)
                if ds:
                    ds_in_clusters.add(ds_id)
                    cl_item['datastores'].append({
                        "name": ds['name'],
                        "mo_id": ds_id,
                        "capacity": ds['capacity'],
                        "free_space": ds['free_space'],
                        "type": ds['type'],
                        "is_local": ds['is_local'],
                        "hosts": sorted([host_names.get(h_id, h_id) for h_id in ds.get('hosts', [])])
                    })
            
            cl_item['datastores'].sort(key=lambda x: x['name'].lower())
            vc_structure['clusters'].append(cl_item)

        # 2. Process Standalone Datastores
        for ds_id, ds in ds_map.items():
            if ds_id not in ds_in_clusters:
                vc_structure['standalone_datastores'].append({
                    "name": ds['name'],
                    "mo_id": ds_id,
                    "capacity": ds['capacity'],
                    "free_space": ds['free_space'],
                    "type": ds['type'],
                    "is_local": ds['is_local'],
                    "hosts": sorted([host_names.get(h_id, h_id) for h_id in ds.get('hosts', [])])
                })

        vc_structure['clusters'].sort(key=lambda x: x['name'].lower())
        vc_structure['standalone_datastores'].sort(key=lambda x: x['name'].lower())
        vcenter_data.append(vc_structure)

    vcenter_data.sort(key=lambda x: x['name'].lower())

    from main import templates
    return templates.TemplateResponse("partials/inventory_storage.html", {
        "request": request,
        "vcenters": vcenter_data
    })
