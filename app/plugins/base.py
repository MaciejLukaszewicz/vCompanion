from pathlib import Path
from typing import Any

class PluginBase:
    """Base class for plugins.

    Plugins should subclass this and implement `startup(context)` and
    `shutdown(context)` as needed.
    """

    def __init__(self, manifest: dict, path: str | Path):
        self.manifest = manifest or {}
        self.path = Path(path)
        self.id = self.manifest.get("id")
        self.name = self.manifest.get("name", self.id)
        self.enabled = bool(self.manifest.get("enabled", True))
        self.permissions = list(self.manifest.get("permissions", []))

    async def startup(self, context: Any):
        """Called by PluginManager when the plugin should start."""
        return None

    async def shutdown(self, context: Any):
        """Called by PluginManager when the app is shutting down."""
        return None
