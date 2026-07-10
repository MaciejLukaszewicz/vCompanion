import importlib
import json
import logging
from pathlib import Path
from typing import Dict, Any

from fastapi.staticfiles import StaticFiles

from app.services.cache_service import cache_service

logger = logging.getLogger(__name__)


class PluginContext:
    def __init__(self, plugin, manager, app):
        self.plugin = plugin
        self.manager = manager
        self.app = app
        self.manifest = plugin.manifest
        self.logger = logging.getLogger(f"plugin.{plugin.id}")

    # Permission guard
    def _require(self, perm: str):
        if perm not in self.plugin.permissions:
            raise PermissionError(f"Plugin '{self.plugin.id}' lacks permission: {perm}")

    # Router registration
    def register_router(self, router, prefix: str | None = None):
        self._require("routes")
        try:
            if prefix:
                self.app.include_router(router, prefix=prefix)
            else:
                self.app.include_router(router)
            self.logger.info(f"Registered router for plugin {self.plugin.id} at prefix={prefix}")
        except Exception as e:
            self.logger.error(f"Failed to register router: {e}")

    # Templates registration
    def register_templates(self, rel_path: str):
        self._require("templates")
        try:
            import main
            plugin_base = Path(self.plugin.path).resolve()
            plugin_templates_path = (plugin_base / rel_path).resolve()
            # Ensure the requested templates path is inside the plugin folder
            try:
                plugin_templates_path.relative_to(plugin_base)
            except Exception:
                raise PermissionError(f"Templates path {plugin_templates_path} is outside plugin directory")

            loader = main.templates.env.loader
            if hasattr(loader, 'searchpath'):
                if str(plugin_templates_path) not in loader.searchpath:
                    loader.searchpath.append(str(plugin_templates_path))
            else:
                # fallback: no-op
                self.logger.warning("Unable to register templates: unsupported loader")
            self.logger.info(f"Registered templates from {plugin_templates_path}")
        except Exception as e:
            self.logger.error(f"Failed to register templates: {e}")

    # Static files registration under namespaced path
    def register_static(self, rel_path: str, mount_path: str | None = None):
        self._require("static")
        try:
            plugin_base = Path(self.plugin.path).resolve()
            static_dir = (plugin_base / rel_path).resolve()
            # Prevent mounting directories outside plugin folder
            try:
                static_dir.relative_to(plugin_base)
            except Exception:
                raise PermissionError(f"Static path {static_dir} is outside plugin directory")

            if not static_dir.exists():
                self.logger.warning(f"Static path does not exist: {static_dir}")
                return
            if not mount_path:
                mount_path = f"/plugins/{self.plugin.id}/static"
            if mount_path in self.manager._mounted_statics:
                return
            self.app.mount(mount_path, StaticFiles(directory=str(static_dir)), name=f"plugin_{self.plugin.id}_static")
            self.manager._mounted_statics.add(mount_path)
            self.logger.info(f"Mounted static for plugin {self.plugin.id} at {mount_path}")
        except Exception as e:
            self.logger.error(f"Failed to mount static files: {e}")

    # Sidebar / settings registration
    def add_sidebar_item(self, item: dict):
        self._require("sidebar")
        self.manager.sidebar_items.append(item)

    def add_settings_page(self, route: str, title: str, order: int = 100):
        self._require("settings")
        self.manager.settings_pages.append({"route": route, "title": title, "order": order})

    # Cache APIs
    class _CacheProxy:
        def __init__(self, plugin):
            self.plugin = plugin

        def set(self, key: str, value: Any):
            if "cache:write" not in self.plugin.permissions:
                raise PermissionError("Plugin lacks cache:write permission")
            return cache_service.save_plugin_data(self.plugin.id, key, value)

        def get(self, key: str, default=None):
            if "cache:read" not in self.plugin.permissions and "cache:write" not in self.plugin.permissions:
                # allow read if write is granted too
                raise PermissionError("Plugin lacks cache:read permission")
            return cache_service.get_plugin_data(self.plugin.id, key, default)

        def delete(self, key: str) -> bool:
            if "cache:write" not in self.plugin.permissions:
                raise PermissionError("Plugin lacks cache:write permission")
            return cache_service.delete_plugin_data(self.plugin.id, key)

        def keys(self) -> list:
            if "cache:read" not in self.plugin.permissions and "cache:write" not in self.plugin.permissions:
                raise PermissionError("Plugin lacks cache permissions")
            return cache_service.list_plugin_keys(self.plugin.id)

    @property
    def cache(self):
        # return a proxy bound to plugin so methods enforce per-op permissions
        return PluginContext._CacheProxy(self.plugin)


import inspect


class PluginManager:
    def __init__(self, app=None):
        self.app = app
        self.plugins: Dict[str, Any] = {}
        self.failed: Dict[str, str] = {}
        self.sidebar_items: list = []
        self.settings_pages: list = []
        self._mounted_statics: set = set()

    def _plugin_root(self) -> Path:
        # project root is two levels above this file (app/plugins/)
        return Path(__file__).resolve().parents[2] / "plugins"

    def scan_and_load(self):
        root = self._plugin_root()
        if not root.exists():
            return
        # Allowed permissions enforced by the host application
        ALLOWED_PERMISSIONS = {"routes","templates","static","sidebar","settings","pages","cache:read","cache:write"}
        for p in root.iterdir():
            if not p.is_dir():
                continue
            manifest_path = p / "manifest.json"
            if not manifest_path.exists():
                logger.debug(f"Skipping {p}: no manifest.json")
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
                pid = manifest.get("id")
                if not pid:
                    logger.warning(f"Plugin at {p} missing id in manifest")
                    continue
                # Validate manifest permissions
                perms = manifest.get("permissions", [])
                invalid = [x for x in perms if x not in ALLOWED_PERMISSIONS]
                if invalid:
                    logger.error(f"Plugin {pid} requests invalid permissions: {invalid}; skipping plugin")
                    self.failed[pid] = f"invalid permissions: {invalid}"
                    continue
                if not manifest.get("enabled", True):
                    logger.info(f"Plugin {pid} disabled in manifest; skipping")
                    continue
                module_path = manifest.get("module")
                if not module_path:
                    logger.warning(f"Plugin {pid} manifest missing module path")
                    continue
                try:
                    mod = importlib.import_module(module_path)
                    PluginClass = getattr(mod, "Plugin", None)
                    create_fn = getattr(mod, "create_plugin", None)
                    if PluginClass:
                        inst = PluginClass(manifest, p)
                    elif create_fn:
                        inst = create_fn(manifest, p)
                    else:
                        logger.warning(f"Plugin module {module_path} exposes no Plugin class or create_plugin()")
                        continue
                    self.plugins[pid] = inst
                    logger.info(f"Loaded plugin {pid} from {p}")
                except Exception as e:
                    logger.error(f"Failed to import plugin {pid}: {e}")
                    self.failed[pid] = str(e)
            except Exception as e:
                logger.error(f"Failed to parse manifest for plugin at {p}: {e}")

    async def startup(self, app):
        self.app = app
        # reset UI registries
        self.sidebar_items = []
        self.settings_pages = []
        self._mounted_statics = set()
        self.scan_and_load()
        # instantiate contexts and call startup
        for pid, plugin in list(self.plugins.items()):
            try:
                ctx = PluginContext(plugin, self, app)
                # call startup if implemented
                if hasattr(plugin, 'startup'):
                    res = plugin.startup(ctx)
                    if inspect.isawaitable(res):
                        await res
                logger.info(f"Started plugin {pid}")
            except Exception as e:
                logger.error(f"Plugin {pid} failed to start: {e}")
                self.failed[pid] = str(e)

    async def load_plugin(self, plugin_id: str):
        """Load and start a single plugin by id (reads manifest.json and imports module)."""
        root = self._plugin_root()
        p = root / plugin_id
        manifest_path = p / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest for plugin {plugin_id} not found")
        manifest = json.loads(manifest_path.read_text())
        if not manifest.get("enabled", True):
            # enable in manifest
            manifest["enabled"] = True
            manifest_path.write_text(json.dumps(manifest, indent=2))

        module_path = manifest.get("module")
        mod = importlib.import_module(module_path)
        PluginClass = getattr(mod, "Plugin", None)
        create_fn = getattr(mod, "create_plugin", None)
        if PluginClass:
            inst = PluginClass(manifest, p)
        elif create_fn:
            inst = create_fn(manifest, p)
        else:
            raise RuntimeError(f"Plugin module {module_path} missing Plugin class or factory")

        self.plugins[plugin_id] = inst
        # start it
        ctx = PluginContext(inst, self, self.app)
        if hasattr(inst, 'startup'):
            res = inst.startup(ctx)
            if inspect.isawaitable(res):
                await res
        logger.info(f"Loaded and started plugin {plugin_id}")

    async def unload_plugin(self, plugin_id: str):
        """Shutdown and remove a loaded plugin.
        This does not delete files; it simply stops the plugin and removes it from memory.
        """
        if plugin_id not in self.plugins:
            raise KeyError(f"Plugin {plugin_id} not loaded")
        inst = self.plugins[plugin_id]
        ctx = PluginContext(inst, self, self.app)
        if hasattr(inst, 'shutdown'):
            res = inst.shutdown(ctx)
            if inspect.isawaitable(res):
                await res
        # cleanup mounted statics and UI entries
        # remove sidebar items matching id
        self.sidebar_items = [s for s in self.sidebar_items if s.get('id') != plugin_id]
        self.settings_pages = [s for s in self.settings_pages if s.get('route') != f"/plugins/{plugin_id}"]
        # attempt to unmount static (FastAPI does not support unmounting; leave mounted but remove reference)
        self.plugins.pop(plugin_id, None)
        logger.info(f"Unloaded plugin {plugin_id}")

    async def shutdown(self):
        for pid, plugin in list(self.plugins.items()):
            try:
                ctx = PluginContext(plugin, self, self.app)
                if hasattr(plugin, 'shutdown'):
                    res = plugin.shutdown(ctx)
                    if inspect.isawaitable(res):
                        await res
                logger.info(f"Shutdown plugin {pid}")
            except Exception as e:
                logger.error(f"Plugin {pid} failed to shutdown cleanly: {e}")

    def get_sidebar_items(self):
        return list(self.sidebar_items)

    def get_settings_pages(self):
        return list(self.settings_pages)
