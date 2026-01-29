import ssl
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from app.core.config import VCenterConfig
import logging

logger = logging.getLogger(__name__)


class VCenterManager:
    """Manages multiple vCenter connections."""
    def __init__(self, configs: list[VCenterConfig]):
        self.connections = {cfg.id: VCenterConnection(cfg) for cfg in configs}

    def connect_all(self, user, password):
        results = {}
        for vc_id, conn in self.connections.items():
            results[vc_id] = conn.connect(user, password)
        return results

    def disconnect_all(self):
        for conn in self.connections.values():
            conn.disconnect()

    def get_all_info(self):
        return {vc_id: conn.get_info() for vc_id, conn in self.connections.items() if conn.service_instance}

    def get_all_vms(self):
        """Get VMs from all connected vCenters."""
        all_vms = []
        for conn in self.connections.values():
            if conn.service_instance:
                all_vms.extend(conn.get_vms())
        return all_vms

    def get_all_hosts(self):
        """Get hosts from all connected vCenters."""
        all_hosts = []
        for conn in self.connections.values():
            if conn.service_instance:
                all_hosts.extend(conn.get_hosts())
        return all_hosts

    def get_all_datastores(self):
        """Get datastores from all connected vCenters."""
        all_datastores = []
        for conn in self.connections.values():
            if conn.service_instance:
                all_datastores.extend(conn.get_datastores())
        return all_datastores

    def get_all_snapshots(self):
        """Get all VMs with snapshots from all vCenters."""
        all_snapshots = []
        for conn in self.connections.values():
            if conn.service_instance:
                all_snapshots.extend(conn.get_snapshots())
        return all_snapshots

    def get_stats(self):
        """Get aggregated statistics across all vCenters."""
        vms = self.get_all_vms()
        snapshots = self.get_all_snapshots()
        hosts = self.get_all_hosts()
        
        # Count VMs by power state
        powered_on = sum(1 for vm in vms if vm.get('power_state') == 'poweredOn')
        
        # Count by OS
        os_counts = {}
        for vm in vms:
            guest_os = vm.get('guest_os', 'Unknown')
            if 'Windows' in guest_os or 'windows' in guest_os:
                os_counts['Windows'] = os_counts.get('Windows', 0) + 1
            elif 'Linux' in guest_os or 'linux' in guest_os or 'Ubuntu' in guest_os or 'CentOS' in guest_os:
                os_counts['Linux'] = os_counts.get('Linux', 0) + 1
            else:
                os_counts['Other'] = os_counts.get('Other', 0) + 1
        
        return {
            "total_vms": len(vms),
            "powered_on_vms": powered_on,
            "snapshot_count": len(snapshots),
            "host_count": len(hosts),
            "os_distribution": os_counts
        }

class VCenterConnection:
    def __init__(self, config: VCenterConfig):
        self.config = config
        self.service_instance = None
        self.content = None

    def connect(self, user, password):
        """Connects to the vCenter server."""
        try:
            # Handle SSL certificate verification
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
            logger.info(f"Successfully connected to vCenter: {self.config.name} ({self.config.host})")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to vCenter {self.config.id}: {str(e)}")
            return False

    def disconnect(self):
        """Disconnects from the vCenter server."""
        if self.service_instance:
            Disconnect(self.service_instance)
            self.service_instance = None
            self.content = None
            logger.info(f"Disconnected from vCenter: {self.config.name}")

    def get_info(self):
        """Returns basic information about the vCenter."""
        if not self.content:
            return None
        
        info = self.content.about
        return {
            "name": self.config.name,
            "version": info.version,
            "build": info.build,
            "api_type": info.apiType,
            "vendor": info.vendor
        }

    def get_vms(self):
        """Retrieve all VMs with detailed information."""
        if not self.content:
            logger.error(f"Not connected to vCenter: {self.config.name}")
            return []
        
        try:
            container = self.content.rootFolder
            view_type = [vim.VirtualMachine]
            recursive = True
            
            container_view = self.content.viewManager.CreateContainerView(
                container, view_type, recursive
            )
            
            vms = []
            for vm in container_view.view:
                try:
                    # Get snapshot info
                    snapshot_count = 0
                    if vm.snapshot:
                        snapshot_count = len(vm.snapshot.rootSnapshotList)
                    
                    # Get guest OS info
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
                except Exception as e:
                    logger.warning(f"Error processing VM {vm.name}: {str(e)}")
                    continue
            
            container_view.Destroy()
            logger.info(f"Retrieved {len(vms)} VMs from {self.config.name}")
            return vms
            
        except Exception as e:
            logger.error(f"Error retrieving VMs from {self.config.name}: {str(e)}")
            return []

    def get_hosts(self):
        """Retrieve all ESXi hosts."""
        if not self.content:
            return []
        
        try:
            container = self.content.rootFolder
            view_type = [vim.HostSystem]
            recursive = True
            
            container_view = self.content.viewManager.CreateContainerView(
                container, view_type, recursive
            )
            
            hosts = []
            for host in container_view.view:
                try:
                    host_info = {
                        "name": host.name,
                        "connection_state": host.runtime.connectionState,
                        "power_state": host.runtime.powerState,
                        "cpu_cores": host.hardware.cpuInfo.numCpuCores,
                        "memory_gb": round(host.hardware.memorySize / (1024**3), 2),
                        "vcenter_id": self.config.id,
                        "vcenter_name": self.config.name
                    }
                    hosts.append(host_info)
                except Exception as e:
                    logger.warning(f"Error processing host: {str(e)}")
                    continue
            
            container_view.Destroy()
            return hosts
            
        except Exception as e:
            logger.error(f"Error retrieving hosts from {self.config.name}: {str(e)}")
            return []

    def get_datastores(self):
        """Retrieve all datastores."""
        if not self.content:
            return []
        
        try:
            container = self.content.rootFolder
            view_type = [vim.Datastore]
            recursive = True
            
            container_view = self.content.viewManager.CreateContainerView(
                container, view_type, recursive
            )
            
            datastores = []
            for ds in container_view.view:
                try:
                    capacity_gb = round(ds.summary.capacity / (1024**3), 2)
                    free_gb = round(ds.summary.freeSpace / (1024**3), 2)
                    used_gb = capacity_gb - free_gb
                    used_percent = round((used_gb / capacity_gb * 100), 1) if capacity_gb > 0 else 0
                    
                    ds_info = {
                        "name": ds.name,
                        "type": ds.summary.type,
                        "capacity_gb": capacity_gb,
                        "free_gb": free_gb,
                        "used_gb": used_gb,
                        "used_percent": used_percent,
                        "accessible": ds.summary.accessible,
                        "vcenter_id": self.config.id,
                        "vcenter_name": self.config.name
                    }
                    datastores.append(ds_info)
                except Exception as e:
                    logger.warning(f"Error processing datastore: {str(e)}")
                    continue
            
            container_view.Destroy()
            return datastores
            
        except Exception as e:
            logger.error(f"Error retrieving datastores from {self.config.name}: {str(e)}")
            return []

    def get_snapshots(self):
        """Get all VMs with active snapshots."""
        if not self.content:
            return []
        
        vms = self.get_vms()
        return [vm for vm in vms if vm.get('snapshot_count', 0) > 0]

