import ssl
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from app.core.config import VCenterConfig
import logging

logger = logging.getLogger(__name__)

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
