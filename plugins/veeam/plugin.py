from app.plugins.base import PluginBase
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pathlib import Path

class Plugin(PluginBase):
    def __init__(self, manifest, path):
        super().__init__(manifest, path)

    async def startup(self, context):
        # register templates and static
        try:
            context.register_templates('templates')
        except Exception:
            pass
        try:
            context.register_static('static')
        except Exception:
            pass

        # simple API router
        router = APIRouter()

        @router.get('/status')
        def status():
            return {"ok": True, "plugin": "veeam"}

        # Register router under safe namespace
        context.register_router(router, prefix='/api/plugins/veeam')

        # add sidebar entry and a page
        try:
            context.add_sidebar_item({
                "id": "veeam",
                "title": "Veeam",
                "icon": "server",
                "order": 90,
                "route": "/plugins/veeam"
            })
        except Exception:
            pass

        # Register a simple page that returns plugin template
        def page_handler(request):
            # Use the central templates loader; template must be in plugin templates
            return context.app.jinja_env.get_template('veeam_dashboard.html').render()

        # Instead of low-level register_page, we use a router endpoint to serve the page
        @router.get('/page', response_class=HTMLResponse)
        def page():
            tpl_path = Path(self.path) / 'templates' / 'veeam_dashboard.html'
            if tpl_path.exists():
                return HTMLResponse(tpl_path.read_text(), status_code=200)
            return HTMLResponse('<h3>Veeam plugin</h3>', status_code=200)

        # save a sample value to plugin cache
        try:
            context.cache.set('last_started', {'ts': '2026-07-10T00:00:00Z'})
        except Exception:
            pass

    async def shutdown(self, context):
        # optional cleanup
        return None

# factory for older style
def create_plugin(manifest, path):
    return Plugin(manifest, path)
