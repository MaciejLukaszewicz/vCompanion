import os
import json
import logging
import base64
import threading
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app.core.config import settings

# Try to import pyVmomi for type checking
try:
    from pyVmomi import vim
except ImportError:
    vim = None

logger = logging.getLogger(__name__)

class VMwareJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle VMware-specific objects like vim.NumericRange."""
    def default(self, obj):
        # pyVmomi objects
        if vim and hasattr(obj, '__module__') and obj.__module__.startswith('pyVmomi'):
            if isinstance(obj, vim.NumericRange):
                if obj.start == obj.end: return str(obj.start)
                return f"{obj.start}-{obj.end}"
            return str(obj)
        # Standard datetime
        if isinstance(obj, datetime):
            return obj.isoformat()
        # Fallback to string for unknown objects instead of failing
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

class CacheService:
    def __init__(self):
        project_root = Path(__file__).parent.parent.parent
        self.data_dir = project_root / "data"
        self.data_dir.mkdir(exist_ok=True)
        self._data = {"vcenters": {}, "vms": {}, "hosts": {}, "alerts": {}, "networks": {}, "storage": {}, "clusters": {}}
        self.salt_path = self.data_dir / "salt.bin"
        if not self.salt_path.exists():
            self.salt = os.urandom(16)
            self.salt_path.write_bytes(self.salt)
        else:
            self.salt = self.salt_path.read_bytes()
        self._fernet = None
        self._is_unlocked = False
        self._lock = threading.Lock()

    @property
    def enabled_vc_ids(self) -> set:
        """Helper to get set of IDs for currently enabled vCenters."""
        return {vc.id for vc in settings.vcenters if vc.enabled}

    def derive_key(self, password: str) -> bool:
        with self._lock:
            try:
                kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=self.salt, iterations=100000)
                key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
                self._fernet = Fernet(key)
                self._is_unlocked = True
                self._load_from_disk()
                return True
            except: return False

    def is_unlocked(self) -> bool: return self._is_unlocked
    
    def lock(self):
        with self._lock:
            self._fernet = None
            self._is_unlocked = False
            self._data = {"vcenters": {}, "vms": {}, "hosts": {}, "alerts": {}, "networks": {}, "storage": {}, "clusters": {}}

    def _get_file_path(self, type_name: str) -> Path: return self.data_dir / f"{type_name}.enc"

    def _save_to_disk(self, key: str = None):
        """Saves cache to disk. If key is provided, only that category is saved (optimized)."""
        if not self._is_unlocked or not self._fernet: return
        
        keys_to_save = [key] if key else list(self._data.keys())
        
        for k in keys_to_save:
            try:
                # Capture current state of the specific category to avoid modification during encryption
                data_to_serialize = self._data[k]
                content = json.dumps(data_to_serialize, cls=VMwareJSONEncoder).encode()
                encrypted = self._fernet.encrypt(content)
                self._get_file_path(k).write_bytes(encrypted)
            except Exception as e: 
                logger.error(f"Error saving {k} to disk: {e}")

    def _load_from_disk(self):
        """Assumes lock is already held by the caller (derive_key)."""
        for key in self._data:
            path = self._get_file_path(key)
            if path.exists():
                try:
                    encrypted = path.read_bytes()
                    decrypted = self._fernet.decrypt(encrypted)
                    loaded = json.loads(decrypted.decode())
                    if isinstance(loaded, dict): 
                        self._data[key].update(loaded)
                    elif isinstance(loaded, list):
                        self._data[key] = loaded
                except Exception as e:
                    logger.error(f"Error loading {key} from disk: {e}")

    def update_vcenter_status(self, vc_id: str, name: str, status: str, error: str = None, metadata: dict = None):
        with self._lock:
            if not self._is_unlocked: return
            data = {
                "id": vc_id, 
                "name": name, 
                "last_refresh": datetime.now().isoformat(), 
                "status": status, 
                "error_message": error
            }
            if metadata:
                data.update(metadata)
            self._data["vcenters"][vc_id] = data
            self._save_to_disk("vcenters")

    def update_vcenter_metadata(self, vc_id: str, metadata: dict):
        """Surgically update metadata fields for a vCenter in the cache."""
        with self._lock:
            if not self._is_unlocked: return
            if vc_id in self._data["vcenters"]:
                self._data["vcenters"][vc_id].update(metadata)
                self._save_to_disk("vcenters")

    def get_vcenter_status(self, vc_id: str = None):
        with self._lock:
            if vc_id: return self._data["vcenters"].get(vc_id)
            enabled_ids = self.enabled_vc_ids
            return [v for vid, v in self._data["vcenters"].items() if vid in enabled_ids]

    def save_vms(self, vcenter_id: str, vms: list):
        with self._lock:
            if not self._is_unlocked: return
            self._data["vms"][vcenter_id] = vms
            self._save_to_disk("vms")

    def save_hosts(self, vcenter_id: str, hosts: list):
        with self._lock:
            if not self._is_unlocked: return
            self._data["hosts"][vcenter_id] = hosts
            self._save_to_disk("hosts")

    def save_alerts(self, vcenter_id: str, alerts: list):
        with self._lock:
            if not self._is_unlocked: return
            self._data["alerts"][vcenter_id] = alerts
            self._save_to_disk("alerts")

    def save_networks(self, vcenter_id: str, networks: dict):
        with self._lock:
            if not self._is_unlocked: return
            self._data["networks"][vcenter_id] = networks
            self._save_to_disk("networks")

    def save_storage(self, vcenter_id: str, storage: dict):
        with self._lock:
            if not self._is_unlocked: return
            self._data["storage"][vcenter_id] = storage
            self._save_to_disk("storage")

    def save_clusters(self, vcenter_id: str, clusters: list):
        with self._lock:
            if not self._is_unlocked: return
            self._data["clusters"][vcenter_id] = clusters
            self._save_to_disk("clusters")

    def get_all_vms(self):
        with self._lock:
            all_vms = []
            enabled_ids = self.enabled_vc_ids
            for vc_id, vms in self._data["vms"].items():
                if vc_id in enabled_ids:
                    all_vms.extend(vms)
            return all_vms

    def get_all_hosts(self):
        with self._lock:
            all_hosts = []
            enabled_ids = self.enabled_vc_ids
            for vc_id, hosts in self._data["hosts"].items():
                if vc_id in enabled_ids:
                    all_hosts.extend(hosts)
            return all_hosts

    def get_all_alerts(self):
        with self._lock:
            all_alerts = []
            enabled_ids = self.enabled_vc_ids
            for vc_id, alerts in self._data["alerts"].items():
                if vc_id in enabled_ids:
                    all_alerts.extend(alerts)
            return all_alerts

    def get_all_clusters(self):
        with self._lock:
            all_clusters = []
            enabled_ids = self.enabled_vc_ids
            for vc_id, clusters in self._data["clusters"].items():
                if vc_id in enabled_ids:
                    all_clusters.extend(clusters)
            return all_clusters

    def get_all_networks(self):
        with self._lock:
            enabled_ids = self.enabled_vc_ids
            return {vc_id: nets for vc_id, nets in self._data["networks"].items() if vc_id in enabled_ids}

    def get_all_storage(self):
        with self._lock:
            enabled_ids = self.enabled_vc_ids
            return {vc_id: storage for vc_id, storage in self._data["storage"].items() if vc_id in enabled_ids}

    def get_cached_stats(self):
        # We need to gather data under a single lock to ensure consistency
        with self._lock:
            vms = []
            hosts = []
            alerts = []
            enabled_ids = self.enabled_vc_ids
            
            for vc_id, v_list in self._data["vms"].items():
                if vc_id in enabled_ids: vms.extend(v_list)
            for vc_id, h_list in self._data["hosts"].items():
                if vc_id in enabled_ids: hosts.extend(h_list)
            for vc_id, a_list in self._data["alerts"].items():
                if vc_id in enabled_ids: alerts.extend(a_list)
                
            total_vms = len(vms)
            total_hosts = len(hosts)
            total_maintenance = sum(1 for h in hosts if h.get('in_maintenance'))
            powered_on = sum(1 for vm in vms if vm.get('power_state') == 'poweredOn')
            total_snapshots = sum(vm.get('snapshot_count', 0) for vm in vms)
            
            total_critical = sum(1 for a in alerts if a.get('severity') == 'critical')
            total_warning = sum(1 for a in alerts if a.get('severity') == 'warning')
            
            if total_vms == 0 and total_hosts == 0 and total_critical == 0 and total_warning == 0:
                return {"total_vms": "N/A", "has_data": False, "raw_alerts": []}
            
            per_vcenter = {}
            for vc_id, status in self._data["vcenters"].items():
                if vc_id in enabled_ids:
                    per_vcenter[vc_id] = {
                        "name": status.get('name'), 
                        "connected": status.get('status') == 'READY', 
                        "vms": 0, "vms_on": 0, "hosts": 0, "hosts_maint": 0, "snapshots": 0,
                        "critical": 0, "warning": 0
                    }
            
            for vm in vms:
                vc_id = vm.get('vcenter_id')
                if vc_id in per_vcenter:
                    per_vcenter[vc_id]["vms"] += 1
                    if vm.get('power_state') == 'poweredOn': per_vcenter[vc_id]["vms_on"] += 1
                    per_vcenter[vc_id]["snapshots"] += vm.get('snapshot_count', 0)
            
            for host in hosts:
                vc_id = host.get('vcenter_id')
                if vc_id in per_vcenter: 
                    per_vcenter[vc_id]["hosts"] += 1
                    if host.get('in_maintenance'): per_vcenter[vc_id]["hosts_maint"] += 1
                
            for alert in alerts:
                vc_id = alert.get('vcenter_id')
                if vc_id in per_vcenter:
                    if alert.get('severity') == 'critical': per_vcenter[vc_id]["critical"] += 1
                    else: per_vcenter[vc_id]["warning"] += 1
                
            return {
                "total_vms": total_vms,
                "powered_on_vms": powered_on,
                "snapshot_count": total_snapshots,
                "host_count": total_hosts,
                "maintenance_hosts": total_maintenance,
                "critical_alerts": total_critical,
                "warning_alerts": total_warning,
                "per_vcenter": per_vcenter,
                "has_data": True,
                "raw_alerts": alerts
            }

cache_service = CacheService()
