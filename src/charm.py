#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

import json
import logging
from itertools import chain
from typing import Optional, List
import kubernetes.client
import requests

from ops.charm import CharmBase

from ops.main import main
from ops.model import (
    ActiveStatus, WaitingStatus, Relation, MaintenanceStatus
)
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class CharCharm(CharmBase):
    """Charm the service."""
    _container_name = _layer_name = _service_name = "char"
    _peer_relation_name = "replicas"
    _port = 8080

    def __init__(self, *args):
        super().__init__(*args)

        self.container = self.unit.get_container(self._container_name)

        # Core lifecycle events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.char_pebble_ready,
                               self._on_pebble_ready)
        self.framework.observe(self.on.start, self._on_start)
        # self.framework.observe(self.on.update_status, self._on_update_status)
        # self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        # Peer relation events
        self.framework.observe(
            self.on[self._peer_relation_name].relation_joined,
            self._on_peer_relation_joined
        )
        self.framework.observe(
            self.on[self._peer_relation_name].relation_changed,
            self._on_peer_relation_changed
        )

        # Action events
        self.framework.observe(self.on.war_action, self._on_war_action)
        self.framework.observe(self.on.respawn_action, self._on_respawn_action)
        self.framework.observe(self.on.glob_status_action,
                               self._on_glob_status_action)

    @property
    def enemies(self) -> List[str]:
        return self._get_peer_addresses()

    def _update(self, event):
        """Update the state"""

        container = self.container
        # Create a new config layer
        layer = self._char_layer()

        if container.can_connect():
            # Get the current config
            services = container.get_plan().to_dict().get("services", {})
            # Check if there are any changes to services
            if services != layer.services:
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

        enemies = ';'.join(self.enemies)
        logging.info(f"enemies: {enemies}")

        env = {
            "ENEMIES": enemies,
            "UVICORN_PORT": self.config["port"],
            "NAME": self.config["name"],
            "LOGLEVEL": "INFO"  # could expose to config
        }
        logging.info(str(env))

        return Layer({
            "summary": "char layer",
            "description": "pebble config layer for char",
            "services": {
                "char": {
                    "override": "replace",
                    "summary": "char service",
                    "command": "./main.sh",
                    "startup": "enabled",
                    "environment": env,
                }
            },
        })

    # source: https://github.com/canonical/alertmanager-k8s-operator
    def _restart_service(self) -> bool:
        """Helper function for restarting the underlying service.
        Returns:
            True if restart succeeded; False otherwise.
        """
        logger.info("Restarting service %s", self._service_name)

        if not self.container.can_connect():
            logger.error("Cannot (re)start service: container is not ready.")
            return False

        # Check if service exists, to avoid ModelError from being raised when the service does
        # not exist,
        if not self.container.get_plan().services.get(self._service_name):
            logger.error(
                "Cannot (re)start service: service does not (yet) exist.")
            return False

        self.container.restart(self._service_name)

        # Update "launched with peers" flag.
        # The service should be restarted when peers joined if this is False.
        # plan = self.container.get_plan()
        # service = plan.services.get(self._service_name)
        # self._stored.launched_with_peers = "--cluster.peer" in service.command

        return True

    def _update_layer(self, restart: bool) -> bool:
        """Update service layer to reflect changes in peers (replicas).
        Args:
          restart: a flag indicating if the service should be restarted if a change was detected.
        Returns:
          True if anything changed; False otherwise
        """
        overlay = self._char_layer()
        plan = self.container.get_plan()

        if self._service_name not in plan.services or overlay.services != plan.services:
            self.container.add_layer(self._layer_name, overlay, combine=True)

            if restart:
                self._restart_service()

            return True

        return False

    @property
    def peer_relation(self) -> Relation:
        """Helper function for obtaining the peer relation object.
        Returns: peer relation object
        (NOTE: would return None if called too early, e.g. during install).
        """
        return self.model.get_relation(self._peer_relation_name)

    @property
    def private_address(self) -> Optional[str]:
        """Get the unit's ip address.
        Technically, receiving a "joined" event guarantees an IP address is available. If this is
        called beforehand, a None would be returned.
        When operating a single unit, no "joined" events are visible so obtaining an address is a
        matter of timing in that case.
        This function is still needed in Juju 2.9.5 because the "private-address" field in the
        data bag is being populated by the app IP instead of the unit IP.
        Also in Juju 2.9.5, ip address may be None even after RelationJoinedEvent, for which
        "ops.model.RelationDataError: relation data values must be strings" would be emitted.
        Returns:
          None if no IP is available (called before unit "joined"); unit's ip address otherwise
        """
        # if bind_address := check_output(["unit-get", "private-address"]).decode().strip()
        if bind_address := self.model.get_binding(self._peer_relation_name
                                                  ).network.bind_address:
            bind_address = str(bind_address)
        return bind_address

    def _common_exit_hook(self) -> None:
        """Event processing hook that is common to all events to ensure idempotency."""
        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus(
                "Waiting for pod startup to complete")
            return

        # Wait for IP address. IP address is needed for forming char clusters
        # and for related apps' config.
        if not self.private_address:
            self.unit.status = MaintenanceStatus("Waiting for IP address")
            return

        # In the case of a single unit deployment, no 'RelationJoined' event is emitted, so
        # setting IP here.
        # Store private address in unit's peer relation data bucket. This is still needed because
        # the "private-address" field in the data bag is being populated incorrectly.
        # Also, ip address may still be None even after RelationJoinedEvent, for which
        # "ops.model.RelationDataError: relation data values must be strings" would be emitted.
        if self.peer_relation:
            self.peer_relation.data[self.unit][
                "private_address"] = self.private_address

        # Update pebble layer
        layer_changed = self._update_layer(restart=False)

        service_running = (
                              service := self.container.get_service(
                                  self._service_name)
                          ) and service.is_running()

        if peer_relation := self.peer_relation:
            num_peers = len(peer_relation.units)

            if layer_changed and (
                    not service_running or num_peers > 0
            ):
                self._restart_service()
        self.unit.status = ActiveStatus()

    def _on_pebble_ready(self, _):
        """Event handler for PebbleReadyEvent."""
        self._common_exit_hook()

    def _on_config_changed(self, _):
        """Event handler for ConfigChangedEvent."""
        self._common_exit_hook()

    def _on_start(self, _):
        """Event handler for StartEvent.
        With Juju 2.9.5 encountered a scenario in which pebble_ready and config_changed fired,
        but IP address was not available and the status was stuck on "Waiting for IP address".
        Adding this hook reduce the likelihood of that scenario.
        """
        self._common_exit_hook()

    def _on_peer_relation_joined(self, _):
        """Event handler for replica's RelationChangedEvent."""
        self._common_exit_hook()

    def _on_peer_relation_changed(self, _):
        """Event handler for replica's RelationChangedEvent.
        `relation_changed` is needed in addition to `relation_joined` because when a second unit
        joins, the first unit must be restarted and provided with the second unit's IP address.
        when the first unit sees "joined", it is not guaranteed that the second unit already has
        an IP address.
        """
        self._common_exit_hook()

    def _get_peer_addresses(self) -> List[str]:
        """Create a list of HA addresses of all peer units (all units excluding current).
        The returned addresses include the HA port number but do not include scheme (http).
        If a unit does not have an address, it will be omitted from the list.
        """
        addresses = []
        if pr := self.peer_relation:
            addresses = [
                f"{address}:{self._port}"
                for unit in pr.units
                # pr.units only holds peers (self.unit is not included)
                if (address := pr.data[unit].get("private_address"))
            ]

        return addresses

    # ACTIONS
    def _on_war_action(self, _):
        """ Let the bloodbath begin. Throws a pebble at some char, causing it to
        lash out to all other chars in sight, which will retaliate, etc...
        https://juju.is/docs/sdk/actions
        """
        url = "http://localhost:8080/attack/?damage=1"
        try:
            requests.post(url)
        except Exception as e:
            logger.error(f"failed to contact the local char server; check "
                         f"your connectivity! {e}")

    def _on_respawn_action(self, _):
        """ Revives a dead char.
        """
        self._restart_service()

    def _on_glob_status_action(self, _):
        """ reports the status of all chars in the cluster
        """
        statuses = {}

        def get_name_and_hp(url):
            resp = requests.get(url + '/status')
            jsn = resp.json()
            return jsn['name'], jsn['hp']

        for host in chain(['localhost'], self.enemies):
            name, hp = get_name_and_hp(f"http://{host}:8080")
            statuses[name] = hp

        logging.info(f"SITREP:"
                     f"{json.dumps(statuses, indent=2)}")


if __name__ == "__main__":
    main(CharCharm)
