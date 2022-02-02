#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

import logging
from urllib import request, parse
import kubernetes.client

from ops.charm import (
    CharmBase,
    RelationDepartedEvent,
    RelationChangedEvent,
    RelationJoinedEvent,
    LeaderElectedEvent
)
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus, BlockedStatus

logger = logging.getLogger(__name__)


def _core_v1_api():
    """Use the v1 k8s API."""
    return kubernetes.client.CoreV1Api()


def _networking_v1_api():
    """Use the v1 beta1 networking API."""
    return kubernetes.client.NetworkingV1Api()


class CharCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(
            self.on.config_changed,
            self._on_config_changed)
        self.framework.observe(
            self.on.war_action,
            self._on_war_action)
        self.framework.observe(
            self.on.respawn_action,
            self._on_respawn_action)

        # Handle the case where Juju elects a new application leader
        self.framework.observe(
            self.on.leader_elected,
            self._on_leader_elected)
        # Handle the various relation events
        self.framework.observe(
            self.on.replicas_relation_joined,
            self._on_replicas_relation_joined)
        self.framework.observe(
            self.on.replicas_relation_departed,
            self._on_replicas_relation_departed)
        self.framework.observe(
            self.on.replicas_relation_changed,
            self._on_replicas_relation_changed)

        self._stored.set_default(leader_ip="")

        self._service_port = self.config["port"]

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handle the leader-elected event"""
        logging.debug("Leader %s setting some data!", self.unit.name)
        # Get the peer relation object
        peer_relation = self.model.get_relation("replicas")
        # Get the bind address from the juju model
        # Convert to string as relation data must always be a string
        ip = str(self.model.get_binding(peer_relation).network.bind_address)
        # Update some data to trigger a replicas_relation_changed event
        peer_relation.data[self.app].update({"leader-ip": ip})

    def _on_replicas_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handle relation-joined event for the replicas relation"""
        logger.debug("Hello from %s to %s", self.unit.name, event.unit.name)

        # Check if we're the leader
        if self.unit.is_leader():
            # Get the bind address from the juju model
            ip = str(self.model.get_binding(event.relation).network.bind_address)
            logging.debug("Leader %s setting some data!", self.unit.name)
            event.relation.data[self.app].update({"leader-ip": ip})

        # Update our unit data bucket in the relation
        event.relation.data[self.unit].update({"unit-data": self.unit.name})

    def _on_replicas_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Handle relation-departed event for the replicas relation"""
        logger.debug("Goodbye from %s to %s", self.unit.name, event.unit.name)

    def _on_replicas_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle relation-changed event for the replicas relation"""
        logging.debug("Unit %s can see the following data: %s", self.unit.name,
                      event.relation.data.keys())
        # Fetch an item from the application data bucket
        leader_ip_value = event.relation.data[self.app].get("leader-ip")
        # Store the latest copy locally in our state store
        if leader_ip_value and leader_ip_value != self._stored.leader_ip:
            self._stored.leader_ip = leader_ip_value

    def _on_config_changed(self, event):
        """Handle the config-changed event"""
        # Get the char container so we can configure/manipulate it
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
            self.unit.status = WaitingStatus(
                "waiting for Pebble in workload container")
            return

        self.unit.status = ActiveStatus()

    # Actual char stuff
    def _char_layer(self):
        """Returns a Pebble configration layer for Char"""
        env = {
            "ENEMIES": self.config["enemies"],
            "UVICORN_PORT": self.config["port"],
            "NAME": self.config["name"]
        }
        logging.error(str(env))

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
        url = "http://localhost:8080/attack"
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
