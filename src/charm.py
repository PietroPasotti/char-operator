#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

import logging
from urllib import request, parse

from charms.nginx_ingress_integrator.v0.ingress import IngressRequires
from ops.charm import CharmBase
# from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, Container, WaitingStatus

logger = logging.getLogger(__name__)


class CharCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.war_action, self._on_war_action)
        self.framework.observe(self.on.respawn_action, self._on_respawn_action)

        print('inited Char Charm!')

        self.ingress = IngressRequires(self, {
            "service-hostname": self.app.name,
            "service-name": self.app.name,
            "service-port": 8000
        })

    def _on_config_changed(self, event):
        """Handle the config-changed event"""
        # Get the gosherve container so we can configure/manipulate it
        container = self.unit.get_container("char")
        # Create a new config layer
        layer = self._char_layer()

        if container.can_connect():
            # Get the current config
            services = container.get_plan().to_dict().get("services", {})
            # Check if there are any changes to services
            if services != layer["services"]:
                # Changes were made, add the new layer
                container.add_layer("char", layer, combine=True)
                logging.info("Added updated layer 'char' to Pebble plan")
                # Restart it and report a new status to Juju
                container.restart("char")
                logging.info("Restarted char service")
            # All is well, set an ActiveStatus
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = WaitingStatus("waiting for Pebble in workload container")

    def _char_layer(self):
        """Returns a Pebble configration layer for Char"""
        env = {
            "ENEMIES": self.model.config["enemies"],
            "UVICORN_PORT": self.model.config["port"],
            "NAME": self.model.config["name"]
        }
        print(env)

        return {
            "summary": "char layer",
            "description": "pebble config layer for char",
            "services": {
                "char": {
                    "override": "replace",
                    "summary": "char server",
                    "command": "./main.sh",
                    "startup": "enabled",
                    "environment": env,
                }
            },
        }

    def _on_war_action(self, _):
        """ Let the bloodbath begin. Throws a pebble at some char, causing it to
        lash out to all other chars in sight, which will retaliate, etc...
        https://juju.is/docs/sdk/actions
        """
        url = f"http://localhost:{self.model.config['port']}/attack"
        data = parse.urlencode({'damage': 0}).encode()
        req = request.Request(url, data=data)
        request.urlopen(req)

    def _on_respawn_action(self, _):
        """ Revives a dead char.
        """
        container = self.unit.get_container('char')
        container.restart("char")


if __name__ == "__main__":
    main(CharCharm)
