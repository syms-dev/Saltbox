"""Put the built web app inside the wheel, when it has been built.

``npm run build`` in ``web/`` writes ``web/dist``. A wheel built after that carries
it as ``saltbox_ui/web_dist``, so an installed daemon serves the web app without
Node on the server. Without a build the wheel is still valid: the daemon then says
the web app is not built. Editable installs use the checkout's ``web/dist`` directly.
"""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebAppHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        dist = Path(self.root) / "web" / "dist"
        if version == "editable" or not (dist / "index.html").is_file():
            return
        build_data["force_include"][str(dist)] = "saltbox_ui/web_dist"
