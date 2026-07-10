# Veeam Backup Server Plugin for vCompanion

This plugin adds support for Veeam Backup Server through its REST API.

## Purpose
- Integrate Veeam Backup Server status and backup metadata into vCompanion
- Provide a dedicated plugin page in the sidebar
- Provide a plugin settings page for Veeam connection configuration
- Keep Veeam-specific configuration separate from core vCenter settings

## Plugin layout
The plugin should follow this structure:

```
plugins/veeam/
  manifest.json
  config.json
  plugin.py
  client.py
  routes.py
  models.py
  templates/
    veeam_dashboard.html
    veeam_settings.html
  static/
    css/
    js/
```

## Plugin responsibilities
- `manifest.json` defines registration metadata and load behavior
- `config.json` stores Veeam-specific connection settings
- `plugin.py` bootstraps the plugin, registers routes and navigation
- `client.py` contains the REST API client for Veeam Backup Server
- `routes.py` exposes API endpoints for the plugin
- `models.py` defines data models for Veeam objects
- `templates/` contains plugin HTML partials and pages
- `static/` contains plugin-specific frontend assets

## Integration points
- Plugin manager loads the plugin from `plugins/veeam/`
- Plugin may expose a sidebar item under the main app navigation
- Plugin may expose a Settings page under the Settings section
- Plugin may use the central app's `cache_service` for encrypted plugin data storage

## Veeam-specific config example
`plugins/veeam/config.json` should include connection settings such as:

```json
{
  "host": "veeam.example.local",
  "port": 9398,
  "username": "backup-admin",
  "verify_ssl": false
}
```

## Development notes
- The plugin must not interfere with core vCenter routes or behavior
- If the plugin fails, the host app should still work correctly
- The plugin should only be loaded if its `manifest.json` is valid and enabled

## Next steps
1. Implement plugin bootstrap and manifest loader in the host app
2. Add Veeam REST client and secure plugin data caching
3. Add routes and UI templates for Veeam status and settings

## Security requirements
- Plugins MUST NOT read or traverse other application folders (including other plugins) by design.
- Plugins MUST NOT access encrypted cache files on disk directly; they must use `PluginContext.cache` to `set`, `get`, `delete` and `keys` scoped to their plugin id.
- Store any sensitive plugin credentials only via the `PluginContext.cache` API so data is encrypted and isolated per-plugin.
- Manifest permissions control allowed operations; avoid requesting more permissions than necessary.

Example usage in `plugin.py`:
```python
def startup(self, context):
    # use the provided cache API, not direct file IO
    context.cache.set('veeam_last_sync', {'ts': '2026-07-10T12:00:00Z'})
    # register routes via context
    router = APIRouter(prefix='/api/plugins/veeam')
    context.register_router(router)
```

If you need stronger isolation (recommended for untrusted plugins), run the plugin logic outside the main process and communicate via a controlled IPC or HTTP bridge.
