import ssl
import socket
import logging
import threading
import time
import concurrent.futures
from datetime import datetime, timedelta
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from app.core.config import VCenterConfig, settings
from app.services.cache_service import cache_service

logger = logging.getLogger(__name__)

class VCenterManager:
    def __init__(self, configs: list[VCenterConfig]):
        # Filter only enabled vCenters
        self.configs = [cfg for cfg in configs if cfg.enabled]
        self.connections = {cfg.id: VCenterConnection(cfg) for cfg in self.configs}
        self.cache = cache_service
        self.global_refresh_interval = settings.app_settings.refresh_interval_seconds
        self._stop_event = threading.Event()
        self._worker_thread = None
        self._last_refresh_trigger = {cfg.id: 0 for cfg in self.configs}
        logger.info(f"VCenterManager initialized with {len(self.connections)} enabled vCenters (out of {len(configs)} total)")

    def start_worker(self):
        if not self.cache.is_unlocked(): return
        if self._worker_thread and self._worker_thread.is_alive(): return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Background refresh worker started.")

    def stop_worker(self):
        self._stop_event.set()
        if self._worker_thread:
            try: self._worker_thread.join(timeout=2)
            except: pass
        logger.info("Background refresh worker stopped.")

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                if not self.cache.is_unlocked(): break
                now = time.time()
                for vc_id, conn in self.connections.items():
                    interval = conn.config.refresh_interval or self.global_refresh_interval
                    if now - self._last_refresh_trigger[vc_id] >= interval:
                        if conn.is_alive():
                            self.trigger_refresh(vc_id)
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
            for _ in range(10):
                if self._stop_event.is_set(): break
                time.sleep(0.1)

    def trigger_refresh(self, vc_id):
        if not self.cache.is_unlocked() or vc_id not in self.connections: return
        conn = self.connections[vc_id]
        self._last_refresh_trigger[vc_id] = time.time()
        threading.Thread(target=self._refresh_task, args=(vc_id, conn), daemon=True).start()

    def refresh_all(self):
        for vc_id, conn in self.connections.items():
            if conn.is_alive(): self.trigger_refresh(vc_id)

    def _refresh_task(self, vc_id, conn):
        try:
            status = self.cache.get_vcenter_status(vc_id)
            if status and status.get('status') == 'REFRESHING':
                lt = status.get('last_refresh')
                if lt and (datetime.now() - datetime.fromisoformat(lt)).total_seconds() < 300: return

            self.cache.update_vcenter_status(vc_id, conn.config.name, 'REFRESHING')
            logger.info(f"===> [{conn.config.name}] Starting REFRESH")
            
            # 1. Fetch Hosts (needed for VM host resolving)
            hosts = conn.get_hosts_speed()
            self.cache.save_hosts(vc_id, hosts)
            
            # 2. Fetch VMs & Snapshots (detailed)
            vms = conn.get_vms_speed(hosts)
            self.cache.save_vms(vc_id, vms)

            # 3. Fetch Alerts
            alerts = conn.get_alerts_speed()
            self.cache.save_alerts(vc_id, alerts)

            # 4. Fetch Networks
            networks = conn.get_networks_speed()
            self.cache.save_networks(vc_id, networks)

            # 5. Fetch Clusters
            clusters = conn.get_clusters()
            self.cache.save_clusters(vc_id, clusters)

            # 6. Fetch Storage
            storage = conn.get_storage_speed()
            self.cache.save_storage(vc_id, storage)

            # 7. Fetch About info (version, build, etc.)
            about = conn.content.about
            
            metadata = {
                "version": about.version,
                "build": about.build,
                "full_name": about.fullName,
                "api_type": about.apiType,
                "fqdn": conn.config.host,
                "ssh_enabled": None
            }
            
            self.cache.update_vcenter_status(vc_id, conn.config.name, 'READY', metadata=metadata)
            logger.info(f"===> [{conn.config.name}] REFRESH SUCCESSFUL (v{about.version})")
            
        except Exception as e:
            logger.error(f"Refresh task failed for {vc_id}: {e}")
            self.cache.update_vcenter_status(vc_id, conn.config.name, 'ERROR', str(e))

    def connect_all(self, user, password, selected_ids=None):
        """
        Connect to selected vCenters.
        Returns: dict with vc_id as key and dict with connection result details as value
        Example: {'vc1': {'success': True}, 'vc2': {'success': False, 'error_type': 'timeout', 'error_msg': '...'}}
        """
        if not self.cache.is_unlocked():
            if not self.cache.derive_key(password): return {}
        self.start_worker()
        target_ids = selected_ids if (selected_ids and len(selected_ids) > 0) else list(self.connections.keys())
        results = {}
        for vid in target_ids:
            if vid in self.connections:
                success, error_type, error_msg = self.connections[vid].connect(user, password)
                results[vid] = {
                    'success': success,
                    'error_type': error_type,
                    'error_msg': error_msg
                }
                if success: 
                    self.trigger_refresh(vid)
        return results

    def disconnect_all(self):
        self.stop_worker()
        self.cache.lock()
        for conn in self.connections.values(): conn.disconnect()

    def get_connection_status(self):
        status = []
        now = time.time()
        for vc_id, conn in self.connections.items():
            cs = self.cache.get_vcenter_status(vc_id) or {}
            last_t = self._last_refresh_trigger.get(vc_id, 0)
            
            # Calculate seconds since last refresh finished
            seconds_since = None
            if cs.get('last_refresh'):
                try:
                    lr_dt = datetime.fromisoformat(cs.get('last_refresh'))
                    # Ensure timezone-aware comparison if needed, but local isoformat usually fine
                    seconds_since = (datetime.now() - lr_dt).total_seconds()
                except: pass

            # Prepare status object with base fields
            vc_status = {
                "id": vc_id, "name": conn.config.name, "host": conn.config.host,
                "connected": conn.is_alive(), 
                "refresh_status": cs.get('status', 'READY'),
                "error_type": conn.last_error_type if not conn.is_alive() else None,
                "seconds_since": seconds_since,
                "seconds_until": max(0, int((conn.config.refresh_interval or self.global_refresh_interval) - (now - last_t))) if last_t > 0 else 0,
                "unlocked": self.cache.is_unlocked()
            }
            
            # Merge fields from cache (version, build, last_refresh, ssh_enabled, etc.)
            for k, v in cs.items():
                if k not in vc_status:
                    vc_status[k] = v
            
            status.append(vc_status)
        return status

    def get_stats(self):
        if not self.cache.is_unlocked(): return {"total_vms": "Locked", "has_data": False}
        return self.cache.get_cached_stats()

    def get_all_recent_events(self, minutes=30):
        all_events = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.connections)) as executor:
            futures = {executor.submit(conn.get_recent_events, minutes): vc_id 
                       for vc_id, conn in self.connections.items() if conn.is_alive()}
            for future in concurrent.futures.as_completed(futures):
                vc_id = futures[future]
                try:
                    events = future.result(timeout=30)
                    all_events.extend(events)
                except Exception as e:
                    logger.error(f"Error fetching events from {vc_id}: {e}")
        all_events.sort(key=lambda x: x['time'], reverse=True)
        return all_events

    def get_all_recent_tasks(self, minutes=30):
        all_tasks = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.connections)) as executor:
            futures = {executor.submit(conn.get_recent_tasks, minutes): vc_id 
                       for vc_id, conn in self.connections.items() if conn.is_alive()}
            for future in concurrent.futures.as_completed(futures):
                vc_id = futures[future]
                try:
                    tasks = future.result(timeout=30)
                    all_tasks.extend(tasks)
                except Exception as e:
                    logger.error(f"Error fetching tasks from {vc_id}: {e}")
        all_tasks.sort(key=lambda x: x['start_time'] if x['start_time'] else "", reverse=True)
        return all_tasks

    def toggle_host_service(self, vc_id, host_mo_id, service_key, start=True):
        """Delegates service toggle to the correct vCenter connection and triggers a refresh."""
        if vc_id not in self.connections: return False
        conn = self.connections[vc_id]
        if not conn.is_alive(): return False
        
        success = conn.toggle_host_service(host_mo_id, service_key, start)
        if success:
            # Trigger background refresh to update the cache status
            self.trigger_refresh(vc_id)
        return success

    def toggle_vcenter_service(self, vc_id, service_key, start=True):
        """Delegates vCenter appliance service toggle and triggers refresh."""
        if vc_id not in self.connections: return False
        conn = self.connections[vc_id]
        
        success = conn.toggle_vcenter_service(service_key, start)
        if success:
            if service_key == 'ssh':
                self.cache.update_vcenter_metadata(vc_id, {"ssh_enabled": start})
            # Trigger background refresh
            self.trigger_refresh(vc_id)
        return success

    def remove_snapshot(self, vc_id: str, vm_mo_id: str, snapshot_name: str, trigger_refresh: bool = True):
        """Proxies snapshot removal to specific vCenter. Returns task ID."""
        if vc_id not in self.connections: return None
        conn = self.connections[vc_id]
        if not conn.is_alive(): return None
        task_id = conn.remove_snapshot(vm_mo_id, snapshot_name)
        if task_id and trigger_refresh:
            self.trigger_refresh(vc_id)
        return task_id

    def check_task_status(self, vc_id: str, task_id: str) -> dict:
        """Proxies task status check to specific vCenter."""
        if vc_id not in self.connections: return {"state": "error", "error": "vCenter not found"}
        conn = self.connections[vc_id]
        if not conn.is_alive(): return {"state": "error", "error": "vCenter not connected"}
        return conn.check_task_status(task_id)

    def create_snapshot(self, vc_id: str, vm_mo_id: str, name: str, description: str = "", trigger_refresh: bool = True) -> str | None:
        """Proxies snapshot creation to specific vCenter. Returns task ID."""
        if vc_id not in self.connections: return None
        conn = self.connections[vc_id]
        if not conn.is_alive(): return None
        task_id = conn.create_snapshot(vm_mo_id, name, description)
        if task_id and trigger_refresh:
            self.trigger_refresh(vc_id)
        return task_id

    def login_vcenter_appliance(self, vc_id, user, password):
        """Authenticates with the VCSA REST API for a specific vCenter."""
        if vc_id not in self.connections: return "vc_not_found"
        result = self.connections[vc_id].login_appliance(user, password)
        # Sync error state to cache for UI indicators
        self.cache.update_vcenter_metadata(vc_id, {"appliance_error": None if result == "success" else result})
        return result

    def get_vcenter_appliance_ssh_status(self, vc_id):
        """Gets SSH status from VCSA REST API and updates cache."""
        if vc_id not in self.connections: return None
        status = self.connections[vc_id].get_appliance_ssh_status()
        
        # get_appliance_ssh_status returns None if error, but we should know why.
        # Connection carries last_appliance_error
        conn = self.connections[vc_id]
        if status is not None:
             self.cache.update_vcenter_metadata(vc_id, {"ssh_enabled": status, "appliance_error": None})
        else:
             self.cache.update_vcenter_metadata(vc_id, {"appliance_error": getattr(conn, 'last_appliance_error', 'unknown')})
             
        return status

class VCenterConnection:
    def __init__(self, config: VCenterConfig):
        self.config = config
        self.si = None
        self.content = None
        self.appliance_token = None
        self.last_appliance_error = None
        self.last_error_type = None  # Added to track vCenter connection error type

    def is_alive(self):
        if not self.si: return False
        try:
            self.si.CurrentTime()
            return True
        except: return False

    def _appliance_rest_call(self, method, endpoint, data=None):
        """Helper for VCSA REST API calls (Appliance API)"""
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        port = getattr(self, 'appliance_port', 443)
        # We try the sticky prefix first, but legacy/modern can be mixed for services vs session
        prefix_primary = getattr(self, 'appliance_prefix', '/api')
        prefix_secondary = '/rest' if prefix_primary == '/api' else '/api'
        
        verify = self.config.verify_ssl
        headers = {
            "vmware-api-session-id": self.appliance_token,
            "Content-Type": "application/json"
        }

        for prefix in [prefix_primary, prefix_secondary]:
            url = f"https://{self.config.host}:{port}{prefix}{endpoint}"
            try:
                if method.lower() == 'get':
                    response = requests.get(url, headers=headers, verify=verify, timeout=5)
                elif method.lower() == 'put':
                    response = requests.put(url, headers=headers, json=data, verify=verify, timeout=5)
                elif method.lower() == 'post':
                    response = requests.post(url, headers=headers, json=data, verify=verify, timeout=5)
                
                # Success codes often differ (200, 201, 204)
                if response.status_code in [200, 201, 204]:
                    self.last_appliance_error = None
                    return response
                
                # If error, log it for debugging
                logger.debug(f"[{self.config.name}] VCSA REST {method} on {url} returned {response.status_code}: {response.text}")

                # Retry on 404 (wrong path), 500/405 (wrong payload/path combo for this prefix)
                if response.status_code in [404, 405, 500]:
                    continue
                
                # If 401, token might be truly dead or prefix mismatch
                if response.status_code == 401:
                    self.last_appliance_error = "auth_error"
                    if prefix == prefix_secondary: # Both failed
                        logger.warning(f"[{self.config.name}] VCSA REST 401 on both paths. Session expired.")
                        self.appliance_token = None
                    continue
                
                self.last_appliance_error = f"http_{response.status_code}"
                return response # Return other errors (e.g. 400, 403)
            except Exception as e:
                logger.debug(f"[{self.config.name}] VCSA REST {method} fail on {url}: {e}")
                self.last_appliance_error = "network_error"
                continue
                
        return None

    def login_appliance(self, user, password):
        """Authenticates to the VCSA REST API. Tries multiple ports and endpoints."""
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        logger.info(f"[{self.config.name}] Initiating VCSA appliance login for user: {user}")
        
        verify = self.config.verify_ssl
        ports = [443, 5480]
        endpoints = ["/api/session", "/rest/com/vmware/cis/session"]
        
        any_401 = False
        any_network_error = False
        
        for port in ports:
            for endpoint in endpoints:
                url = f"https://{self.config.host}:{port}{endpoint}"
                try:
                    logger.debug(f"[{self.config.name}] Trying appliance login at {url}")
                    response = requests.post(url, auth=(user, password), verify=verify, timeout=5)
                    
                    if response.status_code in [200, 201]:
                        # Success!
                        content_type = response.headers.get('Content-Type', '')
                        if 'application/json' in content_type:
                            data = response.json()
                            token = data['value'] if isinstance(data, dict) and 'value' in data else data
                        else:
                            token = response.text.strip('"')
                        
                        self.appliance_token = token
                        self.appliance_port = port
                        self.appliance_prefix = "/api" if endpoint.startswith("/api") else "/rest"
                        self.last_appliance_error = None
                        logger.info(f"[{self.config.name}] VCSA appliance login successful for user: {user} (via port {port}, {endpoint})")
                        return "success"
                    
                    if response.status_code == 401:
                        any_401 = True
                        logger.debug(f"[{self.config.name}] 401 Unauthorized at {url}")
                    else:
                        logger.debug(f"[{self.config.name}] Status {response.status_code} at {url}")

                except Exception as e:
                    any_network_error = True
                    logger.debug(f"[{self.config.name}] Connection failed to {url}: {e}")

        # If we reached here, determine the best error type to report
        if any_401:
            self.last_appliance_error = "auth_error"
            logger.error(f"[{self.config.name}] VCSA appliance login failed: Invalid credentials for user {user}")
            return "auth_error"
        
        if any_network_error:
            self.last_appliance_error = "network_error"
            logger.error(f"[{self.config.name}] VCSA appliance login failed: Network/Communication error to ports [443, 5480]")
            return "network_error"

        self.last_appliance_error = "unknown_error"
        return "unknown_error"

    def get_appliance_ssh_status(self):
        """Returns True if SSH is enabled, False if disabled, None if error."""
        if not self.appliance_token: return None
        resp = self._appliance_rest_call('get', '/appliance/access/ssh')
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                # Handle potential {"value": boolean} wrapper
                if isinstance(data, dict) and 'value' in data:
                    return data['value']
                return data
            except Exception as e:
                logger.error(f"Failed to parse SSH status response: {e}")
                return None
        return None

    def toggle_appliance_ssh(self, start=True):
        """Enable or disable SSH on VCSA."""
        if not self.appliance_token: return False
        
        # Most VCSA versions (especially 7/8) expect a JSON object for SSH toggle
        payload = {"enabled": start}
        resp = self._appliance_rest_call('put', '/appliance/access/ssh', data=payload)
        
        # PUT returns 204 No Content on success in modern API, or 200 in legacy
        success = resp is not None and (resp.status_code in [200, 204])
        if success:
            logger.info(f"[{self.config.name}] VCSA SSH service {'enabled' if start else 'disabled'} successfully.")
        else:
            err_msg = resp.text if resp else "No response"
            logger.error(f"[{self.config.name}] Failed to toggle VCSA SSH: {err_msg}")
            
        return success

    def toggle_vcenter_service(self, service_key, start=True):
        """
        Attempts to toggle a service on the VCSA.
        """
        if service_key == 'ssh':
            return self.toggle_appliance_ssh(start)
        
        logger.warning(f"Toggle vCenter service {service_key} requested - not implemented for non-ssh via REST yet.")
        return False

    def connect(self, user, password):
        """
        Attempt to connect to vCenter.
        Returns: tuple (success: bool, error_type: str|None, error_msg: str|None)
        error_type can be: 'auth', 'network', 'timeout', 'ssl', 'unknown'
        """
        try:
            ctx = None if self.config.verify_ssl else ssl._create_unverified_context()
            self.si = SmartConnect(host=self.config.host, user=user, pwd=password, port=self.config.port, sslContext=ctx)
            self.content = self.si.RetrieveContent()
            logger.info(f"[{self.config.name}] Successfully connected")
            self.last_error_type = None
            return (True, None, None)
        except vim.fault.InvalidLogin as e:
            # Wrong username or password
            logger.warning(f"[{self.config.name}] Authentication failed: Invalid credentials")
            self.last_error_type = 'auth'
            return (False, 'auth', 'Invalid username or password')
        except (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError) as e:
            # Connection refused - vCenter might be down or unreachable
            logger.error(f"[{self.config.name}] Connection refused: {str(e)}")
            self.last_error_type = 'network'
            return (False, 'network', f'Connection refused - vCenter may be down or unreachable')
        except (TimeoutError, socket.timeout) as e:
            # Timeout - network issue or VPN disconnected
            logger.error(f"[{self.config.name}] Connection timeout: {str(e)}")
            self.last_error_type = 'timeout'
            return (False, 'timeout', 'Connection timeout - check network connectivity or VPN')
        except ssl.SSLError as e:
            # SSL certificate error
            logger.error(f"[{self.config.name}] SSL error: {str(e)}")
            self.last_error_type = 'ssl'
            return (False, 'ssl', f'SSL certificate error: {str(e)}')
        except OSError as e:
            # Generic network errors (DNS, unreachable host, etc.)
            if 'timed out' in str(e).lower():
                logger.error(f"[{self.config.name}] Network timeout: {str(e)}")
                self.last_error_type = 'timeout'
                return (False, 'timeout', 'Network timeout - check VPN or network connectivity')
            elif 'no route to host' in str(e).lower() or 'unreachable' in str(e).lower():
                logger.error(f"[{self.config.name}] Host unreachable: {str(e)}")
                self.last_error_type = 'network'
                return (False, 'network', 'Host unreachable - check network or VPN connection')
            else:
                logger.error(f"[{self.config.name}] Network error: {str(e)}")
                self.last_error_type = 'network'
                return (False, 'network', f'Network error: {str(e)}')
        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(f"[{self.config.name}] Unexpected error during connection: {str(e)}")
            self.last_error_type = 'unknown'
            return (False, 'unknown', f'Unexpected error: {str(e)}')

    def disconnect(self):
        if self.si: 
            try: Disconnect(self.si)
            except: pass
            self.si = None
            self.content = None

    def get_vms_speed(self, cached_hosts=None):
        """Fetches detailed VM info for inventory."""
        if not self.content: return []
        
        def get_snaps(snap_tree):
            res = []
            for s in snap_tree:
                res.append({
                    "name": s.name,
                    "description": s.description,
                    "created": s.createTime.isoformat() if s.createTime else None
                })
                if s.childSnapshotList:
                    res.extend(get_snaps(s.childSnapshotList))
            return res

        try:
            host_map = {}
            if cached_hosts:
                for h in cached_hosts:
                    if 'mo_id' in h: host_map[h['mo_id']] = h['name']

            view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.VirtualMachine], True)
            
            paths = [
                "name", "runtime.powerState", "runtime.host", 
                "guest.ipAddress", "summary.config.numVirtualDisks", 
                "guest.net", "snapshot",
                "config.hardware.numCPU", "config.hardware.memoryMB",
                "config.hardware.device",
                "summary.storage.committed", "summary.storage.uncommitted",
                "summary.config.annotation",
                "summary.quickStats.overallCpuUsage", "summary.quickStats.guestMemoryUsage",
                "summary.quickStats.hostMemoryUsage", "runtime.maxCpuUsage"
            ]
            
            spec = vim.PropertyFilterSpec(
                propSet=[vim.PropertySpec(type=vim.VirtualMachine, pathSet=paths)],
                objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
            )
            props = self.content.propertyCollector.RetrieveContents([spec])
            view.Destroy()
            
            vms = []
            for obj in props:
                vm_id = obj.obj._moId
                d = {
                    "id": vm_id, 
                    "vcenter_id": self.config.id, 
                    "vcenter_name": self.config.name,
                    "snapshot_count": 0,
                    "snapshots": [],
                    "networks": [],
                    "ip": None,
                    "disks": 0,
                    "host": "Unknown",
                    "vcpu": 0,
                    "vram_mb": 0,
                    "storage_committed": 0,
                    "storage_uncommitted": 0,
                    "notes": "",
                    "cpu_usage": 0,
                    "max_cpu_mhz": 0,
                    "mem_usage_guest": 0,
                    "mem_usage_host": 0
                }
                
                for p in obj.propSet:
                    if p.name == "name": d["name"] = p.val
                    elif p.name == "runtime.powerState": d["power_state"] = p.val
                    elif p.name == "guest.ipAddress": d["ip"] = p.val
                    elif p.name == "summary.config.numVirtualDisks": d["disks"] = p.val
                    elif p.name == "runtime.host":
                        host_mor = p.val
                        d["host_id"] = host_mor._moId
                        d["host"] = host_map.get(host_mor._moId, f"Host:{host_mor._moId}")
                    elif p.name == "config.hardware.numCPU": d["vcpu"] = p.val
                    elif p.name == "config.hardware.memoryMB": d["vram_mb"] = p.val
                    elif p.name == "config.hardware.device":
                        nics = []
                        disks = []
                        for dev in p.val:
                            # 1. Network Interfaces
                            if isinstance(dev, vim.vm.device.VirtualEthernetCard):
                                backing_info = {"type": "unknown"}
                                b = dev.backing
                                if isinstance(b, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo):
                                    backing_info = {"type": "standard", "network_name": b.deviceName}
                                elif isinstance(b, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo):
                                    backing_info = {
                                        "type": "distributed", 
                                        "portgroup_key": b.port.portgroupKey,
                                        "switch_uuid": b.port.switchUuid
                                    }
                                
                                nics.append({
                                    "label": dev.deviceInfo.label,
                                    "mac": dev.macAddress,
                                    "connected": dev.connectable.connected if dev.connectable else False,
                                    "backing": backing_info
                                })
                            
                            # 2. Virtual Disks
                            elif isinstance(dev, vim.vm.device.VirtualDisk):
                                ds_name = "Unknown"
                                ds_mo_id = None
                                if hasattr(dev.backing, 'datastore'):
                                    ds_name = dev.backing.datastore.name if hasattr(dev.backing.datastore, 'name') else "Datastore"
                                    ds_mo_id = dev.backing.datastore._moId
                                
                                disks.append({
                                    "label": dev.deviceInfo.label,
                                    "capacity_gb": round(dev.capacityInBytes / (1024**3), 2),
                                    "datastore_name": ds_name,
                                    "datastore_id": ds_mo_id,
                                    "file": getattr(dev.backing, 'fileName', 'N/A')
                                })
                        
                        d["nic_devices"] = nics
                        d["disk_devices"] = disks
                    elif p.name == "summary.storage.committed": d["storage_committed"] = p.val
                    elif p.name == "summary.storage.uncommitted": d["storage_uncommitted"] = p.val
                    elif p.name == "summary.config.annotation": d["notes"] = p.val
                    elif p.name == "guest.net" and p.val:
                        pgs = set()
                        for nic in p.val:
                            if nic.network: pgs.add(nic.network)
                        d["networks"] = list(pgs)
                    elif p.name == "snapshot" and p.val:
                        d["snapshots"] = get_snaps(p.val.rootSnapshotList)
                        d["snapshot_count"] = len(d["snapshots"])
                    elif p.name == "summary.quickStats.overallCpuUsage": d["cpu_usage"] = p.val or 0
                    elif p.name == "summary.quickStats.guestMemoryUsage": d["mem_usage_guest"] = p.val or 0
                    elif p.name == "summary.quickStats.hostMemoryUsage": d["mem_usage_host"] = p.val or 0
                    elif p.name == "runtime.maxCpuUsage": d["max_cpu_mhz"] = p.val or 0
                
                vms.append(d)
            return vms
        except Exception as e:
            logger.error(f"Error fetching detailed VMs: {e}")
            return []

    def get_hosts_speed(self):
        if not self.content: return []
        try:
            view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.HostSystem], True)
            
            paths = [
                "name", "config.product.version", "config.product.build", 
                "runtime.bootTime", "runtime.powerState", "runtime.inMaintenanceMode",
                "summary.hardware.numCpuCores", "summary.hardware.cpuMhz", "summary.hardware.memorySize",
                "summary.quickStats.overallCpuUsage", "summary.quickStats.overallMemoryUsage",
                "config.network.vnic", "config.network.pnic", 
                "config.network.vswitch", "config.network.proxySwitch",
                "config.virtualNicManagerInfo.netConfig",
                "datastore", "config.service.service"
            ]
            
            spec = vim.PropertyFilterSpec(
                propSet=[vim.PropertySpec(type=vim.HostSystem, pathSet=paths)],
                objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
            )
            props = self.content.propertyCollector.RetrieveContents([spec])
            view.Destroy()
            
            hosts = []
            for obj in props:
                # First, collect all properties into a dictionary for easier access
                p_dict = {p.name: p.val for p in obj.propSet}
                
                d = {
                    "vcenter_id": self.config.id,
                    "vcenter_name": self.config.name,
                    "mo_id": obj.obj._moId,
                    "name": p_dict.get("name", "Unknown"),
                    "ip": "Unknown",
                    "all_ips": [],
                    "version": p_dict.get("config.product.version", "N/A"),
                    "build": p_dict.get("config.product.build", "N/A"),
                    "boot_time": p_dict.get("runtime.bootTime").isoformat() if p_dict.get("runtime.bootTime") else None,
                    "power_state": p_dict.get("runtime.powerState", "Unknown"),
                    "in_maintenance": p_dict.get("runtime.inMaintenanceMode", False),
                    "ssh_enabled": False,
                    "cpu_cores": p_dict.get("summary.hardware.numCpuCores", 0),
                    "cpu_mhz": p_dict.get("summary.hardware.cpuMhz", 0),
                    "memory_total_mb": int(p_dict.get("summary.hardware.memorySize", 0) / (1024*1024)),
                    "cpu_usage_mhz": p_dict.get("summary.quickStats.overallCpuUsage", 0),
                    "memory_usage_mb": p_dict.get("summary.quickStats.overallMemoryUsage", 0),
                    "pnics": [],
                    "datastores": []
                }
                
                # Extract SSH status
                services = p_dict.get("config.service.service", [])
                for svc in services:
                    if svc.key == 'TSM-SSH':
                        d["ssh_enabled"] = svc.running
                        break
                
                # Map services to vNICs
                vnic_to_services = {}
                net_configs = p_dict.get("config.virtualNicManagerInfo.netConfig", [])
                for nc in net_configs:
                    service_labels = {
                        "management": "Management",
                        "vmotion": "vMotion",
                        "vsan": "vSAN",
                        "faultToleranceLogging": "FT",
                        "vSphereReplication": "Replication",
                        "vSphereReplicationNFC": "Replication NFC"
                    }
                    srv_name = service_labels.get(nc.nicType, nc.nicType)
                    for vnic_device in (nc.selectedVnic or []):
                        if vnic_device not in vnic_to_services: vnic_to_services[vnic_device] = []
                        vnic_to_services[vnic_device].append(srv_name)

                # Map pNICs to switches
                pnic_to_switch = {}
                vswitches = p_dict.get("config.network.vswitch", [])
                for vss in vswitches:
                    for pnic_id in (vss.pnic or []):
                        pnic_to_switch[pnic_id] = vss.name
                
                proxy_switches = p_dict.get("config.network.proxySwitch", [])
                for dvs in proxy_switches:
                    for pnic_key in (dvs.pnic or []):
                        pnic_to_switch[pnic_key] = dvs.dvsName
                
                pnic_list = p_dict.get("config.network.pnic", [])
                for pnic in pnic_list:
                    sw_name = pnic_to_switch.get(pnic.key) or pnic_to_switch.get(pnic.device, "Unassigned")
                    d["pnics"].append({
                        "device": pnic.device,
                        "switch": sw_name
                    })
                
                # Process vNICs/IPs
                vnics = p_dict.get("config.network.vnic", [])
                for vnic in vnics:
                    ip = vnic.spec.ip.ipAddress if vnic.spec and vnic.spec.ip else "N/A"
                    services = vnic_to_services.get(vnic.device, [])
                    d["all_ips"].append({
                        "device": vnic.device,
                        "ip": ip,
                        "portgroup": vnic.portgroup or "DVS",
                        "services": services
                    })
                    if vnic.device == 'vmk0': d["ip"] = ip
                
                if not d["ip"] and d["all_ips"]:
                    d["ip"] = d["all_ips"][0]["ip"]
                
                # Datastores
                ds_list = p_dict.get("datastore", [])
                d["datastores"] = [ds.name if hasattr(ds, 'name') else ds._moId for ds in ds_list]

                hosts.append(d)
                
            return hosts
        except Exception as e:
            logger.error(f"Error fetching hosts: {e}")
            return []

    def toggle_host_service(self, host_mo_id, service_key, start=True):
        """Starts or stops a service on a specific host."""
        if not self.content: return False
        try:
            host = vim.HostSystem(host_mo_id, stub=self.content.sessionManager._stub)
            service_system = host.configManager.serviceSystem
            if start:
                service_system.StartService(id=service_key)
            else:
                service_system.StopService(id=service_key)
            return True
        except Exception as e:
            logger.error(f"Error toggling service {service_key} on host {host_mo_id}: {e}")
            return False

    def get_clusters(self):
        """Fetch compute clusters with aggregated resource stats."""
        if not self.content: return []
        try:
            view = self.content.viewManager.CreateContainerView(
                self.content.rootFolder, [vim.ClusterComputeResource], True
            )
            
            paths = [
                "name", "host", "datastore",
                "summary.numHosts", "summary.numCpuCores", "summary.totalCpu",
                "summary.totalMemory", "summary.effectiveCpu", "summary.effectiveMemory"
            ]
            
            spec = vim.PropertyFilterSpec(
                propSet=[vim.PropertySpec(type=vim.ClusterComputeResource, pathSet=paths)],
                objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[
                    vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)
                ])]
            )
            props = self.content.propertyCollector.RetrieveContents([spec])
            view.Destroy()
            
            clusters = []
            for obj in props:
                p_dict = {p.name: p.val for p in obj.propSet}
                
                # Get host MORs for this cluster
                host_mors = p_dict.get("host", [])
                
                # Get datastore MORs
                ds_mors = p_dict.get("datastore", [])
                
                # Fetch quick stats for hosts in this cluster
                cpu_usage_total = 0
                mem_usage_total = 0
                
                if host_mors:
                    host_spec = vim.PropertyFilterSpec(
                        propSet=[vim.PropertySpec(type=vim.HostSystem, pathSet=[
                            "summary.quickStats.overallCpuUsage",
                            "summary.quickStats.overallMemoryUsage"
                        ])],
                        objectSet=[vim.ObjectSpec(obj=h) for h in host_mors]
                    )
                    try:
                        host_props = self.content.propertyCollector.RetrieveContents([host_spec])
                        for h_obj in host_props:
                            h_dict = {p.name: p.val for p in h_obj.propSet}
                            cpu_usage_total += h_dict.get("summary.quickStats.overallCpuUsage", 0)
                            mem_usage_total += h_dict.get("summary.quickStats.overallMemoryUsage", 0)
                    except: pass
                
                # Calculate datastore capacity
                ds_capacity_total = 0
                ds_free_total = 0
                
                if ds_mors:
                    ds_spec = vim.PropertyFilterSpec(
                        propSet=[vim.PropertySpec(type=vim.Datastore, pathSet=[
                            "summary.capacity", "summary.freeSpace"
                        ])],
                        objectSet=[vim.ObjectSpec(obj=ds) for ds in ds_mors]
                    )
                    try:
                        ds_props = self.content.propertyCollector.RetrieveContents([ds_spec])
                        for ds_obj in ds_props:
                            ds_dict = {p.name: p.val for p in ds_obj.propSet}
                            ds_capacity_total += ds_dict.get("summary.capacity", 0)
                            ds_free_total += ds_dict.get("summary.freeSpace", 0)
                    except: pass
                
                cluster = {
                    "vcenter_id": self.config.id,
                    "vcenter_name": self.config.name,
                    "name": p_dict.get("name", "Unknown"),
                    "num_hosts": p_dict.get("summary.numHosts", 0),
                    "num_cpu_cores": p_dict.get("summary.numCpuCores", 0),
                    "total_cpu_mhz": p_dict.get("summary.totalCpu", 0),
                    "effective_cpu_mhz": p_dict.get("summary.effectiveCpu", 0),
                    "cpu_usage_mhz": cpu_usage_total,
                    "total_memory_mb": int(p_dict.get("summary.totalMemory", 0) / (1024*1024)),
                    "effective_memory_mb": int(p_dict.get("summary.effectiveMemory", 0)),
                    "memory_usage_mb": mem_usage_total,
                    "storage_capacity_gb": int(ds_capacity_total / (1024**3)),
                    "storage_free_gb": int(ds_free_total / (1024**3)),
                    "storage_used_gb": int((ds_capacity_total - ds_free_total) / (1024**3))
                }
                
                clusters.append(cluster)
            
            return clusters
        except Exception as e:
            logger.error(f"Error fetching clusters: {e}")
            return []

    def get_recent_events(self, minutes=30):
        if not self.content: return []
        logger.info(f"[{self.config.name}] Fetching events for last {minutes}m...")
        start_t = time.time()
        try:
            time_limit = datetime.now() - timedelta(minutes=minutes)
            filter_spec = vim.event.EventFilterSpec(time=vim.event.EventFilterSpec.ByTime(beginTime=time_limit))
            events = self.content.eventManager.QueryEvents(filter_spec)
            result = []
            for e in events:
                severity = "warning" if isinstance(e, (vim.event.AlarmStatusChangedEvent, vim.event.AlarmActionTriggeredEvent)) else "info"
                result.append({
                    "vcenter_id": self.config.id, "vcenter_name": self.config.name,
                    "type": e.__class__.__name__.replace("Event", ""),
                    "message": e.fullFormattedMessage, "user": e.userName or "System",
                    "time": e.createdTime.isoformat(), "severity": severity
                })
            logger.info(f"[{self.config.name}] Fetched {len(result)} events in {time.time()-start_t:.2f}s")
            return result
        except Exception as e:
            logger.error(f"[{self.config.name}] Error fetching events: {e}")
            return []

    def get_recent_tasks(self, minutes=30):
        if not self.content: return []
        logger.info(f"[{self.config.name}] Fetching tasks for last {minutes}m...")
        start_t = time.time()
        try:
            time_limit = datetime.now() - timedelta(minutes=minutes)
            time_filter = vim.TaskFilterSpec.ByTime(beginTime=time_limit, timeType="startedTime")
            filter_spec = vim.TaskFilterSpec(time=time_filter)
            collector = self.content.taskManager.CreateCollectorForTasks(filter_spec)
            try:
                tasks_list = collector.ReadNextTasks(999)
            finally:
                if hasattr(collector, 'DestroyCollector'): collector.DestroyCollector()
                elif hasattr(collector, 'Destroy'): collector.Destroy()
            
            result = []
            for t in tasks_list:
                status = t.state
                progress = t.progress if t.progress is not None else (100 if status == 'success' else 0)
                result.append({
                    "vcenter_id": self.config.id, "vcenter_name": self.config.name,
                    "name": t.descriptionId or "Task", "entity_name": t.entityName or "Unknown",
                    "user": t.reason.userName if hasattr(t.reason, 'userName') else "System",
                    "start_time": t.startTime.isoformat() if t.startTime else None,
                    "completion_time": t.completeTime.isoformat() if t.completeTime else None,
                    "status": status, "progress": progress, 
                    "error": getattr(t.error, 'localizedMessage', getattr(t.error, 'msg', str(t.error))) if t.error else None
                })
            logger.info(f"[{self.config.name}] Fetched {len(result)} tasks in {time.time()-start_t:.2f}s")
            return result
        except Exception as e:
            logger.error(f"[{self.config.name}] Error fetching tasks: {e}")
            return []

    def get_alerts_speed(self):
        if not self.content: return []
        try:
            # Optimized to catch ALL managed entities in one go
            # Reverting to ManagedEntity for maximum coverage and including rootFolder
            view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.ManagedEntity], True)
            
            spec = vim.PropertyFilterSpec(
                propSet=[
                    vim.PropertySpec(type=vim.ManagedEntity, pathSet=["name", "triggeredAlarmState"])
                ],
                objectSet=[
                    vim.ObjectSpec(obj=self.content.rootFolder, skip=False),
                    vim.ObjectSpec(obj=view, skip=True, selectSet=[
                        vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)
                    ])
                ]
            )
            props = self.content.propertyCollector.RetrieveContents([spec])
            view.Destroy()
            
            logger.info(f"[{self.config.name}] PropertyCollector returned {len(props) if props else 0} objects for alerts")

            raw_alerts = []
            alarm_mors = set()
            for obj in props:
                name, triggered = "", []
                for p in obj.propSet:
                    if p.name == "name": name = p.val
                    elif p.name == "triggeredAlarmState": triggered = p.val
                
                if not triggered: continue
                logger.debug(f"[{self.config.name}] Data for {name}: {len(triggered)} triggered states")
                
                class_name = obj.obj.__class__.__name__
                if class_name.startswith('vim.'): class_name = class_name[4:]
                
                for state in triggered:
                    # Log all states for debugging
                    logger.debug(f"[{self.config.name}] Alarm status: {state.overallStatus} on {name}")
                    
                    # Capture critical (red), warning (yellow), and gray (often health/hardware)
                    if state.overallStatus in ['yellow', 'red', 'gray']:
                        alarm_mors.add(state.alarm)
                        raw_alerts.append({
                            "entity_name": name,
                            "class_name": class_name,
                            "alarm_mor": state.alarm,
                            "status": state.overallStatus,
                            "time": state.time.isoformat() if hasattr(state, 'time') and state.time else datetime.now().isoformat()
                        })

            # Bulk fetch alarm names (MUCH faster than individual calls)
            alarm_names = {}
            if alarm_mors:
                alarm_spec = vim.PropertyFilterSpec(
                    propSet=[vim.PropertySpec(type=vim.Alarm, pathSet=["info.name"])],
                    objectSet=[vim.ObjectSpec(obj=mor) for mor in alarm_mors]
                )
                try:
                    alarm_props = self.content.propertyCollector.RetrieveContents([alarm_spec])
                    for obj in alarm_props:
                        for p in obj.propSet:
                            if p.name == "info.name":
                                alarm_names[obj.obj] = p.val
                except: pass

            type_map = {
                "VirtualMachine": "VM", "HostSystem": "Host", "Folder": "Folder", 
                "ClusterComputeResource": "Cluster", "ComputeResource": "Cluster", 
                "Datacenter": "Datacenter", "Datastore": "Datastore", 
                "ResourcePool": "Resource Pool", "DistributedVirtualSwitch": "DVS",
                "DistributedVirtualPortgroup": "Portgroup", "Network": "Network"
            }

            alerts = []
            for ra in raw_alerts:
                entity_type = type_map.get(ra["class_name"], ra["class_name"])
                severity = "critical" if ra["status"] == 'red' else "warning"
                alerts.append({
                    "vcenter_id": self.config.id, "vcenter_name": self.config.name,
                    "entity_name": ra["entity_name"], "entity_type": entity_type, 
                    "alarm_name": alarm_names.get(ra["alarm_mor"], f"Alarm:{ra['alarm_mor']._moId}"),
                    "severity": severity,
                    "status": ra["status"], "time": ra["time"]
                })
            return alerts
        except Exception as e:
            logger.error(f"[{self.config.name}] Error in get_alerts_speed: {e}")
            return []

    def get_networks_speed(self):
        if not self.content: return {}
        try:
            # 1. Fetch DVS
            dvs_data = []
            try:
                view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.DistributedVirtualSwitch], True)
                props = self.content.propertyCollector.RetrieveContents([
                    vim.PropertyFilterSpec(
                        propSet=[vim.PropertySpec(type=vim.DistributedVirtualSwitch, pathSet=["name", "portgroup"])],
                        objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
                    )
                ])
                view.Destroy()
                for obj in props:
                    p_dict = {p.name: p.val for p in obj.propSet}
                    dvs_data.append({
                        "mo_id": obj.obj._moId,
                        "name": p_dict.get("name"),
                        "portgroups": [pg._moId for pg in p_dict.get("portgroup", [])]
                    })
            except: pass

            # 2. Fetch DVPortgroups (Broad approach)
            dvpg_data = {}
            try:
                view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.DistributedVirtualPortgroup], True)
                props = self.content.propertyCollector.RetrieveContents([
                    vim.PropertyFilterSpec(
                        propSet=[vim.PropertySpec(type=vim.DistributedVirtualPortgroup, pathSet=["name", "config", "vm"])],
                        objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
                    )
                ])
                view.Destroy()
                for obj in props:
                    p_dict = {p.name: p.val for p in obj.propSet}
                    config = p_dict.get("config")
                    
                    vlan_val = 0
                    is_uplink = False
                    if config:
                        is_uplink = getattr(config, 'uplink', False)
                        # Try to get VLAN from defaultPortConfig
                        try:
                            vlan_config = config.defaultPortConfig.vlan
                            if hasattr(vlan_config, 'vlanId'):
                                vlan_val = vlan_config.vlanId
                            elif hasattr(vlan_config, 'vlan'): # Range/Trunk (list of NumericRange)
                                try:
                                    ranges = []
                                    for r in vlan_config.vlan:
                                        if r.start == r.end: ranges.append(str(r.start))
                                        else: ranges.append(f"{r.start}-{r.end}")
                                    vlan_val = ",".join(ranges) if ranges else "Trunk"
                                except:
                                    vlan_val = "Trunk"
                        except: pass

                    dvpg_data[obj.obj._moId] = {
                        "name": p_dict.get("name"),
                        "vlan": vlan_val,
                        "vms": [vm._moId for vm in p_dict.get("vm", [])],
                        "is_uplink": is_uplink
                    }
            except: pass

            # 3. Fetch Host Networking
            host_nets = []
            try:
                view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.HostSystem], True)
                props = self.content.propertyCollector.RetrieveContents([
                    vim.PropertyFilterSpec(
                        propSet=[vim.PropertySpec(type=vim.HostSystem, pathSet=[
                            "name", "config.network.vswitch", "config.network.portgroup", 
                            "config.network.vnic", "config.network.pnic", "config.network.proxySwitch"
                        ])],
                        objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
                    )
                ])
                view.Destroy()
                for obj in props:
                    p_dict = {p.name: p.val for p in obj.propSet}
                    
                    # Map pNIC keys to device names and MACs for this host
                    pnic_map = {p.key: {"device": p.device, "mac": p.mac} for p in p_dict.get("config.network.pnic", [])}
                    
                    switches = []
                    for vss in p_dict.get("config.network.vswitch", []):
                        switches.append({
                            "name": vss.name,
                            "type": "standard",
                            "uplinks": [pnic_map.get(u) for u in (vss.pnic or []) if u in pnic_map],
                            "portgroups": vss.portgroup or []
                        })
                    
                    for ps in p_dict.get("config.network.proxySwitch", []):
                        switches.append({
                            "name": ps.dvsName,
                            "type": "distributed",
                            "uplinks": [pnic_map.get(pnic) for pnic in (ps.pnic or []) if pnic in pnic_map],
                            "dvs_uuid": ps.dvsUuid
                        })

                    portgroups = []
                    for pg in p_dict.get("config.network.portgroup", []):
                        portgroups.append({
                            "name": pg.spec.name,
                            "vlan": pg.spec.vlanId,
                            "vswitch": pg.spec.vswitchName
                        })

                    vmkernels = []
                    for vnic in p_dict.get("config.network.vnic", []):
                        vmkernels.append({
                            "device": vnic.device,
                            "ip": vnic.spec.ip.ipAddress if vnic.spec and vnic.spec.ip else "N/A",
                            "portgroup": vnic.portgroup,
                            "dvs_port": vnic.spec.distributedVirtualPort.portgroupKey if vnic.spec and vnic.spec.distributedVirtualPort else None
                        })

                    host_nets.append({
                        "mo_id": obj.obj._moId,
                        "name": p_dict.get("name"),
                        "switches": switches,
                        "portgroups": portgroups,
                        "vmkernels": vmkernels,
                        "pnics": [{"device": p.device, "key": p.key} for p in p_dict.get("config.network.pnic", [])]
                    })
            except: pass

            return {
                "vcenter_id": self.config.id,
                "distributed_switches": dvs_data,
                "distributed_portgroups": dvpg_data,
                "hosts": host_nets
            }
        except Exception as e:
            logger.error(f"[{self.config.name}] Error fetching networks: {e}")
            return {}
    def get_storage_speed(self):
        if not self.content: return {}
        try:
            # 1. Fetch Datastore Clusters (StoragePods)
            ds_clusters = []
            try:
                view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.StoragePod], True)
                props = self.content.propertyCollector.RetrieveContents([
                    vim.PropertyFilterSpec(
                        propSet=[vim.PropertySpec(type=vim.StoragePod, pathSet=["name", "childEntity", "summary"])],
                        objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
                    )
                ])
                view.Destroy()
                for obj in props:
                    p_dict = {p.name: p.val for p in obj.propSet}
                    summary = p_dict.get("summary")
                    ds_clusters.append({
                        "mo_id": obj.obj._moId,
                        "name": p_dict.get("name"),
                        "capacity": summary.capacity if summary else 0,
                        "free_space": summary.freeSpace if summary else 0,
                        "datastores": [ds._moId for ds in p_dict.get("childEntity", []) if isinstance(ds, vim.Datastore)]
                    })
            except: pass

            # 2. Fetch All Datastores
            datastores = {}
            try:
                view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.Datastore], True)
                props = self.content.propertyCollector.RetrieveContents([
                    vim.PropertyFilterSpec(
                        propSet=[vim.PropertySpec(type=vim.Datastore, pathSet=["name", "summary", "host", "info"])],
                        objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
                    )
                ])
                view.Destroy()
                for obj in props:
                    p_dict = {p.name: p.val for p in obj.propSet}
                    summary = p_dict.get("summary")
                    
                    # Local vs Shared
                    is_local = False
                    if summary and hasattr(summary, 'datastore'):
                        # Check host mounts
                        mount_hosts = p_dict.get("host", [])
                        if len(mount_hosts) == 1:
                            is_local = True # Heuristic, often true for local
                    
                    # More reliable check if possible via info
                    info = p_dict.get("info")
                    extents = []
                    ds_extra = {}
                    if info:
                        if isinstance(info, vim.VmfsDatastoreInfo):
                            extents = [e.diskName for e in info.vmfs.extent]
                        elif isinstance(info, vim.host.NasDatastoreInfo):
                            ds_extra["nfs_server"] = info.nas.remoteHost
                            ds_extra["nfs_path"] = info.nas.remotePath
                        elif isinstance(info, vim.host.VsanDatastoreInfo):
                            ds_extra["is_vsan"] = True
                    
                    datastores[obj.obj._moId] = {
                        "name": p_dict.get("name"),
                        "capacity": summary.capacity if summary else 0,
                        "free_space": summary.freeSpace if summary else 0,
                        "type": summary.type if summary else "Unknown",
                        "accessible": summary.accessible if summary else False,
                        "hosts": [h.key._moId for h in p_dict.get("host", []) if hasattr(h, 'key')],
                        "is_local": is_local,
                        "extents": extents,
                        "extra": ds_extra
                    }
            except: pass

            # 3. Fetch Hosts to get names and HBA/Topology for mapping
            host_map = {}
            host_hbas = {} # mo_id -> hba info and disk mapping
            try:
                view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.HostSystem], True)
                props = self.content.propertyCollector.RetrieveContents([
                    vim.PropertyFilterSpec(
                        propSet=[vim.PropertySpec(type=vim.HostSystem, pathSet=["name", "config.storageDevice"])],
                        objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
                    )
                ])
                view.Destroy()
                for obj in props:
                    p_dict = {p.name: p.val for p in obj.propSet}
                    host_id = obj.obj._moId
                    host_map[host_id] = p_dict.get("name")
                    
                    # Initialize empty entry so we don't get 'falsy' dict later if it has at least keys
                    host_hbas[host_id] = {"hbas": {}, "disk_to_hba": {}}
                    
                    # Process HBAs
                    storage_dev = p_dict.get("config.storageDevice")
                    if storage_dev:
                        # ... process ...
                        # (repeating logic for replacement)
                        hbas = {}
                        for hba in storage_dev.hostBusAdapter:
                            hba_info = {"device": hba.device, "type": "unknown", "id": "N/A"}
                            
                            # Safe type checking
                            hba_type_str = str(type(hba)).lower()
                            
                            if isinstance(hba, vim.host.FibreChannelHba):
                                hba_info["type"] = "fc"
                                if hasattr(hba, 'portWorldWideName'):
                                    wwn = hex(hba.portWorldWideName).replace("0x", "").rstrip("l").zfill(16)
                                    hba_info["id"] = ":".join(wwn[i:i+2] for i in range(0, 16, 2))
                            elif isinstance(hba, vim.host.InternetScsiHba):
                                hba_info["type"] = "iscsi"
                                hba_info["id"] = getattr(hba, 'iScsiName', 'N/A')
                            elif "sashba" in hba_type_str or "parallelscsihba" in hba_type_str:
                                hba_info["type"] = "sas/scsi"
                            elif "blockhba" in hba_type_str:
                                hba_info["type"] = "local/block"
                                
                            hbas[hba.key] = hba_info
                        
                        disk_to_hbas = {}
                        if storage_dev.scsiTopology and storage_dev.scsiLun:
                            lun_map = {l.key: l.canonicalName for l in storage_dev.scsiLun if hasattr(l, 'canonicalName')}
                            
                            for adapter in storage_dev.scsiTopology.adapter:
                                for target in (adapter.target or []):
                                    for lun in (target.lun or []):
                                        c_name = lun_map.get(lun.scsiLun)
                                        if c_name:
                                            # Normalize c_name (strip prefixes if any)
                                            norm_name = c_name.split("/")[-1] 
                                            if norm_name not in disk_to_hbas: disk_to_hbas[norm_name] = []
                                            if adapter.adapter not in disk_to_hbas[norm_name]: 
                                                disk_to_hbas[norm_name].append(adapter.adapter)
                        
                        host_hbas[host_id] = {
                            "hbas": hbas,
                            "disk_to_hba": disk_to_hbas
                        }
                logger.info(f"[{self.config.name}] Processed storage data for {len(host_hbas)} hosts")
            except Exception as e:
                logger.error(f"Error fetching host storage data: {e}")

            # 4. Enhance Datastore info with extents (canonical names)
            for ds_id, ds in datastores.items():
                try:
                    # We might need to refetch or look into 'info' if we had it
                    # But for now, let's assume we can get extents if info was Vmfs
                    # In get_storage_speed step 2, we fetched 'info'
                    pass
                except: pass

            return {
                "vcenter_id": self.config.id,
                "clusters": ds_clusters,
                "datastores": datastores,
                "host_names": host_map,
                "host_storage": host_hbas
            }
        except Exception as e:
            logger.error(f"[{self.config.name}] Error fetching storage: {e}")
            return {}

    def remove_snapshot(self, vm_mo_id: str, snapshot_name: str) -> bool:
        """Removes a snapshot by its name from a given VM."""
        if not self.content: return False
        try:
            # Locate the VM
            vm = vim.VirtualMachine(vm_mo_id, stub=self.content.sessionManager._stub)
            if not vm or not vm.snapshot or not vm.snapshot.rootSnapshotList:
                logger.error(f"[{self.config.name}] Target VM {vm_mo_id} lacking snapshots.")
                return False
                
            # Recursive search for the snapshot object
            def find_snap(snap_list, name):
                for s in snap_list:
                    if s.name == name:
                        return s.snapshot
                    if s.childSnapshotList:
                        child_res = find_snap(s.childSnapshotList, name)
                        if child_res: return child_res
                return None
                
            snap_obj = find_snap(vm.snapshot.rootSnapshotList, snapshot_name)
            if not snap_obj:
                logger.error(f"[{self.config.name}] Snapshot '{snapshot_name}' not found on VM {vm_mo_id}.")
                return False
                
            # Request deletion (removeChildren=False to only remove THIS snapshot)
            task = snap_obj.RemoveSnapshot_Task(removeChildren=False)
            logger.info(f"[{self.config.name}] Dispatched RemoveSnapshot_Task for VM {vm_mo_id}, Snapshot: {snapshot_name}, Task ID: {task._moId}")
            return task._moId
        except Exception as e:
            logger.error(f"[{self.config.name}] Failed to remove snapshot: {e}")
            return None

    def check_task_status(self, task_id: str) -> dict:
        """Checks the status of a scheduled task."""
        if not self.content: return {"state": "error", "error": "Not connected"}
        try:
            task = vim.Task(task_id, stub=self.content.sessionManager._stub)
            state = getattr(task.info, 'state', getattr(task.info, 'state', None))
            # PyVmomi encapsulates states into vim.TaskInfo.State (e.g. 'queued', 'running', 'success', 'error')
            if hasattr(state, 'val'): state = state.val # Unwrap if it's enum
            elif isinstance(state, type) or callable(state): state = str(state) # Edge cases
            else: state = str(state)

            res = {
                "state": state,
                "progress": getattr(task.info, 'progress', 0)
            }
            if state == 'error':
                task_error = task.info.error
                if task_error:
                     res["error"] = getattr(task_error, 'localizedMessage', getattr(task_error, 'msg', str(task_error)))
                else:
                     res["error"] = "Unknown error during task execution"
            return res
        except Exception as e:
            logger.error(f"[{self.config.name}] Failed to get task status for {task_id}: {e}")
            return {"state": "error", "error": str(e)}

    def create_snapshot(self, vm_mo_id: str, name: str, description: str = "") -> str | None:
        """Creates a snapshot on a given VM. Returns task ID or None on failure."""
        if not self.content: return None
        try:
            vm = vim.VirtualMachine(vm_mo_id, stub=self.content.sessionManager._stub)
            if not vm:
                logger.error(f"[{self.config.name}] VM {vm_mo_id} not found.")
                return None
            task = vm.CreateSnapshot_Task(
                name=name,
                description=description,
                memory=False,
                quiesce=False
            )
            logger.info(f"[{self.config.name}] Dispatched CreateSnapshot_Task for VM {vm_mo_id}, name='{name}', task={task._moId}")
            return task._moId
        except Exception as e:
            logger.error(f"[{self.config.name}] Failed to create snapshot: {e}")
            return None

