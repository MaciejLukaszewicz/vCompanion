import ssl
import logging
import asyncio
import threading
import time
from datetime import datetime
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from app.core.config import VCenterConfig, settings
from app.services.cache_service import cache_service

logger = logging.getLogger(__name__)

class VCenterManager:
    """Manages multiple vCenter connections and background cache updates."""
    def __init__(self, configs: list[VCenterConfig]):
        self.connections = {cfg.id: VCenterConnection(cfg) for cfg in configs}
        self.cache = cache_service
        self.refresh_interval = settings.app_settings.refresh_interval_seconds
        self._stop_event = threading.Event()
        self._worker_thread = None
        
        # NOTE: Background worker starts ONLY after cache is unlocked (in connect_all)

    def start_worker(self):
        """Starts the background refresh worker thread."""
        if not self.cache.is_unlocked():
            logger.warning("Attempted to start worker without unlocked cache.")
            return

        if self._worker_thread and self._worker_thread.is_alive():
            return
            
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Background refresh worker started.")

    def stop_worker(self):
        """Stops the background refresh worker thread."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("Background refresh worker stopped.")

    def _worker_loop(self):
        """Main loop for background refreshing."""
        while not self._stop_event.is_set():
            # If cache gets locked somehow, stop working
            if not self.cache.is_unlocked():
                logger.info("Cache locked, stopping background worker.")
                break

            # Trigger refresh for all connected vCenters
            for vc_id, conn in self.connections.items():
                if conn.is_alive():
                    self.trigger_refresh(vc_id)
            
            # Sleep for the interval
            for _ in range(self.refresh_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def trigger_refresh(self, vc_id):
        """Manually trigger a refresh for a specific vCenter."""
        if not self.cache.is_unlocked():
            return

        if vc_id not in self.connections:
            return
            
        conn = self.connections[vc_id]
        threading.Thread(target=self._refresh_task, args=(vc_id, conn), daemon=True).start()

    def _refresh_task(self, vc_id, conn):
        """The actual refresh task that calls vCenter and updates cache."""
        try:
            status = self.cache.get_vcenter_status(vc_id)
            if status and status.get('status') == 'REFRESHING':
                return
                
            self.cache.update_vcenter_status(vc_id, conn.config.name, 'REFRESHING')
            logger.info(f"Starting background refresh for {conn.config.name}")
            
            vms = conn.get_vms()
            if vms or conn.is_alive():
                self.cache.save_vms(vc_id, vms)
                hosts = conn.get_hosts()
                self.cache.save_hosts(vc_id, hosts)
                self.cache.update_vcenter_status(vc_id, conn.config.name, 'READY')
                logger.info(f"Successfully refreshed data for {conn.config.name}")
            else:
                self.cache.update_vcenter_status(vc_id, conn.config.name, 'ERROR', "Failed to retrieve data")
                
        except Exception as e:
            logger.error(f"Error during refresh task for {vc_id}: {str(e)}")
            self.cache.update_vcenter_status(vc_id, conn.config.name, 'ERROR', str(e))

    def connect_all(self, user, password, selected_vcenter_ids=None):
        """Connect to selected vCenters, unlock cache and start worker."""
        # 1. First, try to unlock the cache with the provided password
        if not self.cache.is_unlocked():
            if not self.cache.derive_key(password):
                logger.error("Failed to unlock cache with provided password.")
                return {vid: False for vid in (selected_vcenter_ids or self.connections.keys())}

        # 2. Start background worker if not already running
        self.start_worker()

        results = {}
        vcenters_to_connect = selected_vcenter_ids if selected_vcenter_ids else self.connections.keys()
        
        for vc_id in vcenters_to_connect:
            if vc_id in self.connections:
                results[vc_id] = self.connections[vc_id].connect(user, password)
                if results[vc_id]:
                    self.trigger_refresh(vc_id)
            else:
                results[vc_id] = False
        
        return results

    def disconnect_all(self):
        """Disconnect all vCenters, stop worker and lock cache."""
        self.stop_worker()
        self.cache.lock() # This clears the key and data from RAM
        for conn in self.connections.values():
            conn.disconnect()

    def get_connection_status(self):
        """Get connection and refresh status for all vCenters."""
        cache_statuses = {s['id']: s for s in self.cache.get_vcenter_status()}
        status = []
        
        for vc_id, conn in self.connections.items():
            cache_status = cache_statuses.get(vc_id, {})
            
            seconds_since = None
            if cache_status.get('last_refresh'):
                try:
                    last = datetime.fromisoformat(cache_status['last_refresh'])
                    seconds_since = int((datetime.now() - last).total_seconds())
                except:
                    pass
            
            seconds_until = max(0, self.refresh_interval - (seconds_since or 0))

            status.append({
                "id": vc_id,
                "name": conn.config.name,
                "host": conn.config.host,
                "connected": conn.is_alive(),
                "refresh_status": cache_status.get('status', 'READY'),
                "last_refresh": cache_status.get('last_refresh'),
                "seconds_since": seconds_since,
                "seconds_until": seconds_until,
                "error": cache_status.get('error_message'),
                "unlocked": self.cache.is_unlocked()
            })
        return status

    def get_stats(self):
        """Get statistics from cache if unlocked."""
        if not self.cache.is_unlocked():
            return {
                "total_vms": "Locked",
                "powered_on_vms": 0,
                "snapshot_count": "Locked",
                "host_count": "Locked",
                "os_distribution": {},
                "per_vcenter": {},
                "has_data": False,
                "locked": True
            }

        stats = self.cache.get_cached_stats()
        # Update connection status in per_vcenter from real-time info
        for vc_id, conn in self.connections.items():
            if vc_id in stats['per_vcenter']:
                stats['per_vcenter'][vc_id]['connected'] = conn.is_alive()
        return stats

class VCenterConnection:
    def __init__(self, config: VCenterConfig):
        self.config = config
        self.service_instance = None
        self.content = None

    def is_alive(self):
        if not self.service_instance:
            return False
        try:
            self.service_instance.CurrentTime()
            return True
        except:
            self.service_instance = None
            self.content = None
            return False

    def connect(self, user, password):
        try:
            context = None
            if not self.config.verify_ssl:
                context = ssl._create_unverified_context()

            self.service_instance = SmartConnect(
                host=self.config.host,
                user=user,
                pwd=password,
                port=self.config.port,
                sslContext=context
            )
            self.content = self.service_instance.RetrieveContent()
            logger.info(f"Successfully connected to vCenter: {self.config.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to vCenter {self.config.id}: {str(e)}")
            return False

    def disconnect(self):
        if self.service_instance:
            Disconnect(self.service_instance)
            self.service_instance = None
            self.content = None

    def get_vms(self):
        if not self.content: return []
        try:
            container = self.content.rootFolder
            view_type = [vim.VirtualMachine]
            container_view = self.content.viewManager.CreateContainerView(container, view_type, True)
            
            vms = []
            for vm in container_view.view:
                try:
                    snapshot_count = 0
                    if vm.snapshot:
                        snapshot_count = len(vm.snapshot.rootSnapshotList)
                    guest_os = vm.config.guestFullName if vm.config else "Unknown"
                    vm_info = {
                        "name": vm.name,
                        "power_state": vm.runtime.powerState,
                        "guest_os": guest_os,
                        "cpu_count": vm.config.hardware.numCPU if vm.config else 0,
                        "memory_mb": vm.config.hardware.memoryMB if vm.config else 0,
                        "snapshot_count": snapshot_count,
                        "ip_address": vm.guest.ipAddress if vm.guest else None,
                        "vcenter_id": self.config.id,
                        "vcenter_name": self.config.name
                    }
                    vms.append(vm_info)
                except: continue
            container_view.Destroy()
            return vms
        except: return []

    def get_hosts(self):
        if not self.content: return []
        try:
            container = self.content.rootFolder
            view_type = [vim.HostSystem]
            container_view = self.content.viewManager.CreateContainerView(container, view_type, True)
            hosts = []
            for host in container_view.view:
                try:
                    hosts.append({
                        "name": host.name,
                        "status": host.runtime.connectionState,
                        "vcenter_id": self.config.id
                    })
                except: continue
            container_view.Destroy()
            return hosts
        except: return []
