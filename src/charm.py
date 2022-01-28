#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

import logging
from urllib import request, parse

from ops.charm import CharmBase
# from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, Container

logger = logging.getLogger(__name__)


class CharCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.char_pebble_ready, self._on_char_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.war_action, self._on_war_action)
        self.framework.observe(self.on.respawn_action, self._on_respawn_action)

    def _on_char_pebble_ready(self, event):
        """Define and start a workload using the Pebble API.

        TEMPLATE-TODO: change this example to suit your needs.
        You'll need to specify the right entrypoint and environment
        configuration for your specific workload. Tip: you can see the
        standard entrypoint of an existing container using docker inspect

        Learn more about Pebble layers at https://github.com/canonical/pebble
        """
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload
        # Define an initial Pebble layer configuration
        pebble_layer = {
            "summary": "char layer",
            "description": "pebble config layer for char",
            "services": {
                "char": {
                    "override": "replace",
                    "summary": "char",
                    "command": "./main.sh",
                    "startup": "enabled",
                    "environment": {
                        "enemies": self.model.config["enemies"],
                        "port": self.model.config["port"],
                        "name": self.model.config["name"]
                    },
                }
            },
        }
        # Add initial Pebble config layer using the Pebble API
        container.add_layer("httpbin", pebble_layer, combine=True)
        # Autostart any services that were defined with startup: enabled
        container.autostart()
        # Learn more about statuses in the SDK docs:
        # https://juju.is/docs/sdk/constructs#heading--statuses
        self.unit.status = ActiveStatus()

    def _on_config_changed(self, event):
        """
        Learn more about config at https://juju.is/docs/sdk/config
        """
        container: Container = event.workload
        if container.can_connect():
            layer = {
                "services": {
                    "char": {
                        "override": "replace",
                        "environment": {
                            "enemies": self.model.config["enemies"],
                            "port": self.model.config["port"],
                            "name": self.model.config["name"]
                        },
                    }
                },
            }

            container.add_layer('foo', layer, combine=True)
            container.restart("char")

    def _on_war_action(self, action):
        """ Let the bloodbath begin. Throws a pebble at some char, causing it to
            lash out to all other chars in sight, which will retaliate, etc...
            https://juju.is/docs/sdk/actions
            """
        url = f"http://localhost:{self.model.config['port']}/attack"
        data = parse.urlencode({'damage': 0}).encode()
        req = request.Request(url, data=data)
        request.urlopen(req)

    def _on_respawn_action(self):
        """ Revives a dead char.
        """
        container = self.unit.get_container('char')
        container.restart("char")


if __name__ == "__main__":
    main(CharCharm)
