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
    def __init__(self, configs: list[VCenterConfig]):
        self.configs = configs
        self.connections = {cfg.id: VCenterConnection(cfg) for cfg in configs}
        self.cache = cache_service
        self.global_refresh_interval = settings.app_settings.refresh_interval_seconds
        self._stop_event = threading.Event()
        self._worker_thread = None
        self._last_refresh_trigger = {cfg.id: 0 for cfg in configs}
        logger.info(f"VCenterManager initialized with {len(self.connections)} vCenters")

    def start_worker(self):
        if not self.cache.is_unlocked():
            logger.warning("Cannot start worker: Cache is locked")
            return
        if self._worker_thread and self._worker_thread.is_alive(): return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Background refresh worker started.")

    def stop_worker(self):
        self._stop_event.set()
        if self._worker_thread:
            try:
                self._worker_thread.join(timeout=2)
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
        logger.info(f"[{conn.config.name}] Triggering background refresh...")
        t = threading.Thread(target=self._refresh_task, args=(vc_id, conn), daemon=True)
        t.start()

    def refresh_all(self):
        """Triggers refresh for all connected vCenters."""
        logger.info("Refresh All manually triggered")
        for vc_id, conn in self.connections.items():
            if conn.is_alive():
                self.trigger_refresh(vc_id)

    def _refresh_task(self, vc_id, conn):
        try:
            status = self.cache.get_vcenter_status(vc_id)
            if status and status.get('status') == 'REFRESHING':
                last_refresh = status.get('last_refresh')
                if last_refresh:
                    last_time = datetime.fromisoformat(last_refresh)
                    if (datetime.now() - last_time).total_seconds() < 300:
                        return

            self.cache.update_vcenter_status(vc_id, conn.config.name, 'REFRESHING')
            logger.info(f"===> [{conn.config.name}] Starting REFRESH (VMs, Snapshots, Hosts)")
            
            # Fetch VMs and Snapshots
            s_vm = time.time()
            vms = conn.get_vms_speed()
            logger.info(f"===> [{conn.config.name}] VMs & Snapshots fetched: {len(vms)} in {time.time()-s_vm:.2f}s")
            self.cache.save_vms(vc_id, vms)
            
            # Fetch Hosts
            s_host = time.time()
            hosts = conn.get_hosts_speed()
            logger.info(f"===> [{conn.config.name}] Hosts fetched: {len(hosts)} in {time.time()-s_host:.2f}s")
            self.cache.save_hosts(vc_id, hosts)
            
            self.cache.update_vcenter_status(vc_id, conn.config.name, 'READY')
            logger.info(f"===> [{conn.config.name}] REFRESH SUCCESSFUL")
            
        except Exception as e:
            logger.error(f"Refresh task failed for {vc_id}: {e}")
            self.cache.update_vcenter_status(vc_id, conn.config.name, 'ERROR', str(e))

    def connect_all(self, user, password, selected_ids=None):
        if not self.cache.is_unlocked():
            if not self.cache.derive_key(password):
                return {}
        self.start_worker()
        target_ids = selected_ids if (selected_ids and len(selected_ids) > 0) else list(self.connections.keys())
        results = {}
        for vid in target_ids:
            if vid in self.connections:
                success = self.connections[vid].connect(user, password)
                results[vid] = success
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
            cache_status = self.cache.get_vcenter_status(vc_id) or {}
            interval = conn.config.refresh_interval or self.global_refresh_interval
            last_trigger = self._last_refresh_trigger.get(vc_id, 0)
            seconds_until = max(0, int(interval - (now - last_trigger))) if last_trigger > 0 else interval
            
            seconds_since = None
            if cache_status.get('last_refresh'):
                try:
                    last = datetime.fromisoformat(cache_status['last_refresh'])
                    seconds_since = int((datetime.now() - last).total_seconds())
                except: pass

            status.append({
                "id": vc_id, 
                "name": conn.config.name, 
                "host": conn.config.host,
                "connected": conn.is_alive(), 
                "refresh_status": cache_status.get('status', 'READY'),
                "seconds_since": seconds_since,
                "seconds_until": seconds_until,
                "unlocked": self.cache.is_unlocked()
            })
        return status

    def get_stats(self):
        if not self.cache.is_unlocked(): return {"total_vms": "Locked", "has_data": False}
        return self.cache.get_cached_stats()

class VCenterConnection:
    def __init__(self, config: VCenterConfig):
        self.config = config
        self.si = None
        self.content = None

    def is_alive(self):
        if not self.si: return False
        try:
            self.si.CurrentTime()
            return True
        except: return False

    def connect(self, user, password):
        try:
            ctx = None if self.config.verify_ssl else ssl._create_unverified_context()
            self.si = SmartConnect(host=self.config.host, user=user, pwd=password, port=self.config.port, sslContext=ctx)
            self.content = self.si.RetrieveContent()
            return True
        except Exception as e:
            logger.error(f"Connect failed for {self.config.host}: {e}")
            return False

    def disconnect(self):
        if self.si: 
            try: Disconnect(self.si)
            except: pass
            self.si = None
            self.content = None

    def get_vms_speed(self):
        """Optimized fetching using PropertyCollector including snapshots."""
        if not self.content: return []
        try:
            container = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.VirtualMachine], True)
            
            # Request name, power state AND snapshot property
            property_spec = vim.PropertySpec(type=vim.VirtualMachine, pathSet=["name", "runtime.powerState", "layoutEx.snapshot"])
            
            object_spec = vim.ObjectSpec(obj=container, skip=True)
            traversal_spec = vim.TraversalSpec(name="traverseEntities", path="view", skip=False, type=vim.ContainerView)
            object_spec.selectSet = [traversal_spec]
            filter_spec = vim.PropertyFilterSpec(propSet=[property_spec], objectSet=[object_spec])
            
            collector = self.content.propertyCollector
            props = collector.RetrieveContents([filter_spec])
            
            vms = []
            for obj in props:
                vm_data = {"vcenter_id": self.config.id, "snapshot_count": 0}
                for prop in obj.propSet:
                    if prop.name == "name": 
                        vm_data["name"] = prop.val
                    elif prop.name == "runtime.powerState": 
                        vm_data["power_state"] = prop.val
                    elif prop.name == "layoutEx.snapshot":
                        # layoutEx.snapshot is a list of snapshot layout info
                        if prop.val:
                            vm_data["snapshot_count"] = len(prop.val)
                vms.append(vm_data)
            container.Destroy()
            return vms
        except Exception as e:
            logger.error(f"PropertyCollector failed for VMs with snapshots: {e}")
            # Fallback to even simpler if logic fails
            return []

    def get_hosts_speed(self):
        if not self.content: return []
        try:
            container = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.HostSystem], True)
            property_spec = vim.PropertySpec(type=vim.HostSystem, pathSet=["name"])
            object_spec = vim.ObjectSpec(obj=container, skip=True)
            traversal_spec = vim.TraversalSpec(name="traverseHosts", path="view", skip=False, type=vim.ContainerView)
            object_spec.selectSet = [traversal_spec]
            filter_spec = vim.PropertyFilterSpec(propSet=[property_spec], objectSet=[object_spec])
            collector = self.content.propertyCollector
            props = collector.RetrieveContents([filter_spec])
            hosts = []
            for obj in props:
                name = ""
                for prop in obj.propSet:
                    if prop.name == "name": name = prop.val
                hosts.append({"name": name, "vcenter_id": self.config.id})
            container.Destroy()
            return hosts
        except Exception as e:
            logger.error(f"PropertyCollector failed for Hosts: {e}")
            return []
