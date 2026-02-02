import os
import json
import logging
import base64
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

class CacheService:
    """Manages encrypted JSON cache for vCenter data."""
    def __init__(self):
        # Create data directory in project root
        project_root = Path(__file__).parent.parent.parent
        self.data_dir = project_root / "data"
        self.data_dir.mkdir(exist_ok=True)
        
        # In-memory data store
        self._data = {
            "vcenters": {},
            "vms": {},
            "hosts": {},
        }
        
        # Salt for key derivation (constant for this installation)
        self.salt_path = self.data_dir / "salt.bin"
        if not self.salt_path.exists():
            self.salt = os.urandom(16)
            self.salt_path.write_bytes(self.salt)
        else:
            self.salt = self.salt_path.read_bytes()
            
        self._fernet = None
        self._is_unlocked = False

    def derive_key(self, password: str) -> bool:
        """Derive encryption key from password and unlock the cache."""
        try:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self.salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            self._fernet = Fernet(key)
            self._is_unlocked = True
            
            # Try to load existing cache
            self._load_from_disk()
            logger.info("Cache successfully unlocked and loaded.")
            return True
        except Exception as e:
            logger.error(f"Failed to unlock cache: {str(e)}")
            self._is_unlocked = False
            return False

    def is_unlocked(self) -> bool:
        return self._is_unlocked

    def lock(self):
        """Clear the key from memory."""
        self._fernet = None
        self._is_unlocked = False
        self._data = {"vcenters": {}, "vms": {}, "hosts": {}}
        logger.info("Cache locked and cleared from memory.")

    def _get_file_path(self, type_name: str) -> Path:
        return self.data_dir / f"{type_name}.enc"

    def _save_to_disk(self):
        """Encrypt and save current memory state to disk."""
        if not self._is_unlocked:
            return

        for key in self._data:
            try:
                content = json.dumps(self._data[key]).encode()
                encrypted = self._fernet.encrypt(content)
                self._get_file_path(key).write_bytes(encrypted)
            except Exception as e:
                logger.error(f"Error saving {key} to disk: {str(e)}")

    def _load_from_disk(self):
        """Load and decrypt data from disk into memory."""
        if not self._is_unlocked:
            return

        for key in self._data:
            path = self._get_file_path(key)
            if path.exists():
                try:
                    encrypted = path.read_bytes()
                    decrypted = self._fernet.decrypt(encrypted)
                    self._data[key] = json.loads(decrypted.decode())
                except Exception as e:
                    logger.warning(f"Could not decrypt {key} (maybe wrong password?): {str(e)}")
                    # If decryption fails, we keep the empty dict for that key

    # --- API mimicking DatabaseService for easier migration ---

    def update_vcenter_status(self, vc_id: str, name: str, status: str, error: str = None):
        if not self._is_unlocked: return
        
        self._data["vcenters"][vc_id] = {
            "id": vc_id,
            "name": name,
            "last_refresh": datetime.now().isoformat(),
            "status": status,
            "error_message": error
        }
        self._save_to_disk()

    def get_vcenter_status(self, vc_id: str = None):
        if vc_id:
            return self._data["vcenters"].get(vc_id)
        return list(self._data["vcenters"].values())

    def save_vms(self, vcenter_id: str, vms: list):
        if not self._is_unlocked: return
        self._data["vms"][vcenter_id] = vms
        self._save_to_disk()

    def save_hosts(self, vcenter_id: str, hosts: list):
        if not self._is_unlocked: return
        self._data["hosts"][vcenter_id] = hosts
        self._save_to_disk()

    def get_all_vms(self):
        all_vms = []
        for vcenter_vms in self._data["vms"].values():
            all_vms.extend(vcenter_vms)
        return all_vms

    def get_all_hosts(self):
        all_hosts = []
        for vcenter_hosts in self._data["hosts"].values():
            all_hosts.extend(vcenter_hosts)
        return all_hosts

    def get_cached_stats(self):
        vms = self.get_all_vms()
        hosts = self.get_all_hosts()
        
        if not vms and not hosts:
            return {
                "total_vms": "N/A",
                "powered_on_vms": 0,
                "snapshot_count": "N/A",
                "host_count": "N/A",
                "os_distribution": {},
                "per_vcenter": {},
                "has_data": False
            }
            
        powered_on = sum(1 for vm in vms if vm.get('power_state') == 'poweredOn')
        snapshots_count = sum(vm.get('snapshot_count', 0) for vm in vms)
        
        # OS dist
        os_counts = {}
        for vm in vms:
            guest_os = vm.get('guest_os', 'Unknown')
            if 'Windows' in guest_os or 'windows' in guest_os:
                os_counts['Windows'] = os_counts.get('Windows', 0) + 1
            elif 'Linux' in guest_os or 'linux' in guest_os or 'Ubuntu' in guest_os or 'CentOS' in guest_os:
                os_counts['Linux'] = os_counts.get('Linux', 0) + 1
            else:
                os_counts['Other'] = os_counts.get('Other', 0) + 1
                
        # Per vCenter breakdown
        per_vcenter = {}
        for vc_id, status in self._data["vcenters"].items():
            per_vcenter[vc_id] = {
                "name": status.get('name'),
                "connected": status.get('status') == 'READY',
                "vms": 0,
                "vms_on": 0,
                "snapshots": 0,
                "hosts": 0
            }

        for vm in vms:
            vc_id = vm.get('vcenter_id')
            if vc_id in per_vcenter:
                per_vcenter[vc_id]["vms"] += 1
                if vm.get('power_state') == 'poweredOn':
                    per_vcenter[vc_id]["vms_on"] += 1
                per_vcenter[vc_id]["snapshots"] += vm.get('snapshot_count', 0)

        for host in hosts:
            vc_id = host.get('vcenter_id')
            if vc_id in per_vcenter:
                per_vcenter[vc_id]["hosts"] += 1

        return {
            "total_vms": len(vms),
            "powered_on_vms": powered_on,
            "snapshot_count": snapshots_count,
            "host_count": len(hosts),
            "os_distribution": os_counts,
            "per_vcenter": per_vcenter,
            "has_data": True
        }

cache_service = CacheService()
