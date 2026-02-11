import os
import json
import logging
import base64
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

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
        self._data = {"vcenters": {}, "vms": {}, "hosts": {}, "alerts": {}, "networks": {}, "storage": {}}
        self.salt_path = self.data_dir / "salt.bin"
        if not self.salt_path.exists():
            self.salt = os.urandom(16)
            self.salt_path.write_bytes(self.salt)
        else:
            self.salt = self.salt_path.read_bytes()
        self._fernet = None
        self._is_unlocked = False

    def derive_key(self, password: str) -> bool:
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
        self._fernet = None
        self._is_unlocked = False
        self._data = {"vcenters": {}, "vms": {}, "hosts": {}, "alerts": {}, "networks": {}, "storage": {}}

    def _get_file_path(self, type_name: str) -> Path: return self.data_dir / f"{type_name}.enc"

    def _save_to_disk(self):
        if not self._is_unlocked: return
        for key in self._data:
            try:
                # Use custom encoder to handle vim.NumericRange and other complex types
                content = json.dumps(self._data[key], cls=VMwareJSONEncoder).encode()
                encrypted = self._fernet.encrypt(content)
                self._get_file_path(key).write_bytes(encrypted)
            except Exception as e: 
                logger.error(f"Error saving {key}: {e}")

    def _load_from_disk(self):
        if not self._is_unlocked: return
        for key in self._data:
            path = self._get_file_path(key)
            if path.exists():
                try:
                    encrypted = path.read_bytes()
                    decrypted = self._fernet.decrypt(encrypted)
                    loaded = json.loads(decrypted.decode())
                    if isinstance(loaded, dict): self._data[key].update(loaded)
                except: pass

    def update_vcenter_status(self, vc_id: str, name: str, status: str, error: str = None, metadata: dict = None):
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
        self._save_to_disk()

    def get_vcenter_status(self, vc_id: str = None):
        if vc_id: return self._data["vcenters"].get(vc_id)
        return list(self._data["vcenters"].values())

    def save_vms(self, vcenter_id: str, vms: list):
        if not self._is_unlocked: return
        self._data["vms"][vcenter_id] = vms
        self._save_to_disk()

    def save_hosts(self, vcenter_id: str, hosts: list):
        if not self._is_unlocked: return
        self._data["hosts"][vcenter_id] = hosts
        self._save_to_disk()

    def save_alerts(self, vcenter_id: str, alerts: list):
        if not self._is_unlocked: return
        self._data["alerts"][vcenter_id] = alerts
        self._save_to_disk()

    def save_networks(self, vcenter_id: str, networks: dict):
        if not self._is_unlocked: return
        self._data["networks"][vcenter_id] = networks
        self._save_to_disk()

    def save_storage(self, vcenter_id: str, storage: dict):
        if not self._is_unlocked: return
        self._data["storage"][vcenter_id] = storage
        self._save_to_disk()

    def get_all_vms(self):
        all_vms = []
        for vms in self._data["vms"].values(): all_vms.extend(vms)
        return all_vms

    def get_all_hosts(self):
        all_hosts = []
        for hosts in self._data["hosts"].values(): all_hosts.extend(hosts)
        return all_hosts

    def get_all_alerts(self):
        all_alerts = []
        for alerts in self._data["alerts"].values(): all_alerts.extend(alerts)
        return all_alerts

    def get_all_networks(self):
        return self._data["networks"]

    def get_all_storage(self):
        return self._data.get("storage", {})

    def get_cached_stats(self):
        vms = self.get_all_vms()
        hosts = self.get_all_hosts()
        alerts = self.get_all_alerts()
        
        # Calculate totals from the full lists of fetched data
        total_vms = len(vms)
        total_hosts = len(hosts)
        powered_on = sum(1 for vm in vms if vm.get('power_state') == 'poweredOn')
        total_snapshots = sum(vm.get('snapshot_count', 0) for vm in vms)
        
        # FIX: Sum alerts directly from the master list to avoid issues with empty per-vcenter data
        total_critical = sum(1 for a in alerts if a.get('severity') == 'critical')
        total_warning = sum(1 for a in alerts if a.get('severity') == 'warning')
        
        if total_vms == 0 and total_hosts == 0 and total_critical == 0 and total_warning == 0:
            return {"total_vms": "N/A", "has_data": False, "raw_alerts": []}
        
        per_vcenter = {}
        for vc_id, status in self._data["vcenters"].items():
            per_vcenter[vc_id] = {
                "name": status.get('name'), 
                "connected": status.get('status') == 'READY', 
                "vms": 0, "vms_on": 0, "hosts": 0, "snapshots": 0,
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
            if vc_id in per_vcenter: per_vcenter[vc_id]["hosts"] += 1
            
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
            "critical_alerts": total_critical,
            "warning_alerts": total_warning,
            "per_vcenter": per_vcenter,
            "has_data": True,
            "raw_alerts": alerts
        }

cache_service = CacheService()
