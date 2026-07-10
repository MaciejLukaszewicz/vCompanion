"""Plugin subsystem for vCompanion.

This package contains the plugin base classes and manager which load plugins
from the top-level `plugins/` folder and expose a controlled PluginContext
to each plugin.
"""

from .manager import PluginManager

__all__ = ["PluginManager"]
