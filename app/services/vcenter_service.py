import ssl
import logging
import asyncio
import threading
import time
from datetime import datetime, timedelta
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
            
            self.cache.update_vcenter_status(vc_id, conn.config.name, 'READY')
            logger.info(f"===> [{conn.config.name}] REFRESH SUCCESSFUL")
            
        except Exception as e:
            logger.error(f"Refresh task failed for {vc_id}: {e}")
            self.cache.update_vcenter_status(vc_id, conn.config.name, 'ERROR', str(e))

    def connect_all(self, user, password, selected_ids=None):
        if not self.cache.is_unlocked():
            if not self.cache.derive_key(password): return {}
        self.start_worker()
        target_ids = selected_ids if (selected_ids and len(selected_ids) > 0) else list(self.connections.keys())
        results = {}
        for vid in target_ids:
            if vid in self.connections:
                success = self.connections[vid].connect(user, password)
                results[vid] = success
                if success: self.trigger_refresh(vid)
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
            status.append({
                "id": vc_id, "name": conn.config.name, "host": conn.config.host,
                "connected": conn.is_alive(), "refresh_status": cs.get('status', 'READY'),
                "seconds_until": max(0, int((conn.config.refresh_interval or self.global_refresh_interval) - (now - last_t))) if last_t > 0 else 0,
                "unlocked": self.cache.is_unlocked()
            })
        return status

    def get_stats(self):
        if not self.cache.is_unlocked(): return {"total_vms": "Locked", "has_data": False}
        return self.cache.get_cached_stats()

    def get_all_recent_events(self, minutes=30):
        all_events = []
        for vc_id, conn in self.connections.items():
            if conn.is_alive():
                events = conn.get_recent_events(minutes)
                all_events.extend(events)
        all_events.sort(key=lambda x: x['time'], reverse=True)
        return all_events

    def get_all_recent_tasks(self, minutes=30):
        all_tasks = []
        for vc_id, conn in self.connections.items():
            if conn.is_alive():
                tasks = conn.get_recent_tasks(minutes)
                all_tasks.extend(tasks)
        all_tasks.sort(key=lambda x: x['start_time'] if x['start_time'] else "", reverse=True)
        return all_tasks

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
        except: return False

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
                "summary.storage.committed", "summary.storage.uncommitted",
                "summary.config.annotation"
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
                    "notes": ""
                }
                
                for p in obj.propSet:
                    if p.name == "name": d["name"] = p.val
                    elif p.name == "runtime.powerState": d["power_state"] = p.val
                    elif p.name == "guest.ipAddress": d["ip"] = p.val
                    elif p.name == "summary.config.numVirtualDisks": d["disks"] = p.val
                    elif p.name == "runtime.host":
                        host_mor = p.val
                        d["host"] = host_map.get(host_mor._moId, f"Host:{host_mor._moId}")
                    elif p.name == "config.hardware.numCPU": d["vcpu"] = p.val
                    elif p.name == "config.hardware.memoryMB": d["vram_mb"] = p.val
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
                
                vms.append(d)
            return vms
        except Exception as e:
            logger.error(f"Error fetching detailed VMs: {e}")
            return []

    def get_hosts_speed(self):
        if not self.content: return []
        try:
            view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [vim.HostSystem], True)
            spec = vim.PropertyFilterSpec(
                propSet=[vim.PropertySpec(type=vim.HostSystem, pathSet=["name"])],
                objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
            )
            props = self.content.propertyCollector.RetrieveContents([spec])
            view.Destroy()
            
            hosts = []
            for obj in props:
                name = next((p.val for p in obj.propSet if p.name == "name"), "Unknown")
                hosts.append({
                    "name": name, 
                    "vcenter_id": self.config.id,
                    "mo_id": obj.obj._moId
                })
            return hosts
        except: return []

    def get_recent_events(self, minutes=30):
        if not self.content: return []
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
            return result
        except: return []

    def get_recent_tasks(self, minutes=30):
        if not self.content: return []
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
                    "status": status, "progress": progress, "error": t.error.localizedMessage if t.error else None
                })
            return result
        except: return []

    def get_alerts_speed(self):
        if not self.content: return []
        try:
            types = [vim.Datacenter, vim.ComputeResource, vim.ClusterComputeResource, vim.Folder, vim.HostSystem, vim.VirtualMachine]
            view = self.content.viewManager.CreateContainerView(self.content.rootFolder, types, True)
            spec = vim.PropertyFilterSpec(
                propSet=[vim.PropertySpec(type=vim.ManagedEntity, pathSet=["name", "triggeredAlarmState"])],
                objectSet=[vim.ObjectSpec(obj=view, skip=True, selectSet=[vim.TraversalSpec(name="t", path="view", skip=False, type=vim.ContainerView)])]
            )
            props = self.content.propertyCollector.RetrieveContents([spec])
            view.Destroy()
            alerts = []
            for obj in props:
                name, triggered = "", []
                for p in obj.propSet:
                    if p.name == "name": name = p.val
                    elif p.name == "triggeredAlarmState": triggered = p.val
                if not triggered: continue
                class_name = obj.obj.__class__.__name__
                if class_name.startswith('vim.'): class_name = class_name[4:]
                type_map = {"VirtualMachine": "VM", "HostSystem": "Host", "Folder": "Folder", "ClusterComputeResource": "Cluster", "ComputeResource": "Cluster", "Datacenter": "Datacenter"}
                entity_type = type_map.get(class_name, class_name)
                for state in triggered:
                    if state.overallStatus in ['yellow', 'red']:
                        alarm_name = "Unknown Alarm"
                        try:
                            if state.alarm and hasattr(state.alarm, 'info'): alarm_name = state.alarm.info.name
                            else: alarm_name = str(state.alarm).split(':')[-1].replace("'", "")
                        except: pass
                        alerts.append({
                            "vcenter_id": self.config.id, "vcenter_name": self.config.name,
                            "entity_name": name, "entity_type": entity_type, "alarm_name": alarm_name,
                            "severity": "critical" if state.overallStatus == 'red' else "warning",
                            "status": state.overallStatus, "time": state.time.isoformat() if state.time else datetime.now().isoformat()
                        })
            return alerts
        except: return []
