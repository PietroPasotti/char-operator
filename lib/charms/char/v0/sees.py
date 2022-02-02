"""Library for the sees relation.

This library contains the Requires and Provides classes for handling
the sees interface.

Import `SeesRequires` in your charm, with two required options:
    - "self" (the charm itself)
    - config_dict

`config_dict` accepts the following keys:
    - service-hostname (required)
    - service-name (required)
    - service-port (required)

As an example, add the following to `src/charm.py`:
```
from charms.char.v0.sees import SeesRequires

# In your charm's `__init__` method.
self.sees = SeesRequires(self, {"service-hostname": self.config[
"external_hostname"],
                                      "service-name": self.app.name,
                                      "service-port": 8080})

# In your charm's `config-changed` handler.
self.sees.update_config({"service-hostname": self.config["external_hostname"]})
```
And then add the following to `metadata.yaml`:
```
requires:
  sees:
    interface: sees
```
You _must_ register the SeesRequires class as part of the `__init__` method
rather than, for instance, a config-changed event handler. This is because
doing so won't get the current relation changed event, because it wasn't
registered to handle the event (because it wasn't created in `__init__` when
the event was fired).
"""

import logging

from ops.charm import CharmEvents
from ops.framework import EventBase, EventSource, Object
from ops.model import BlockedStatus

# The unique Charmhub library identifier, never change it
LIBID = "foobarbaz12389034upvnq890234ui28fvndwv"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 0

logger = logging.getLogger(__name__)

REQUIRED_SEES_RELATION_FIELDS = {
    "service-hostname",
}

OPTIONAL_SEES_RELATION_FIELDS = {
    "service-port",
}


class NowYouSeeEvent(EventBase):
    pass


class SeesCharmEvents(CharmEvents):
    """Custom charm events."""

    now_you_see = EventSource(NowYouSeeEvent)


class SeesRequires(Object):
    """This class defines the functionality for the 'requires'
    side of the 'sees' relation.

    Hook events observed:
        - relation-changed
    """

    def __init__(self, charm, config_dict):
        super().__init__(charm, "sees")

        self.framework.observe(charm.on["sees"].relation_changed, self._on_relation_changed)
        self.config_dict = config_dict

    def _config_dict_errors(self, update_only=False):
        """Check our config dict for errors."""
        blocked_message = "Error in sees relation, check `juju debug-log`"
        unknown = [
            x for x in self.config_dict
            if x not in REQUIRED_SEES_RELATION_FIELDS | OPTIONAL_SEES_RELATION_FIELDS
        ]
        if unknown:
            logger.error(
                "Sees relation error: unknown key(s) in "
                "config dictionary found: %s",
                ", ".join(unknown),
            )
            self.model.unit.status = BlockedStatus(blocked_message)
            return True
        if not update_only:
            missing = [x for x in REQUIRED_SEES_RELATION_FIELDS if x not in self.config_dict]
            if missing:
                logger.error(
                    "Sees relation error: missing required key(s) in "
                    "config dictionary: %s",
                    ", ".join(missing),
                )
                self.model.unit.status = BlockedStatus(blocked_message)
                return True
        return False

    def _on_relation_changed(self, event):
        """Handle the relation-changed event."""
        # `self.unit` isn't available here, so use `self.model.unit`.
        if self.model.unit.is_leader():
            if self._config_dict_errors():
                return
            for key in self.config_dict:
                # can event.relation.data[self.model.app] be lifted to outer
                # scope?
                event.relation.data[self.model.app][key] = str(self.config_dict[key])

    def update_config(self, config_dict):
        """Allow for updates to relation."""
        if self.model.unit.is_leader():
            self.config_dict = config_dict
            if self._config_dict_errors(update_only=True):
                return
            relation = self.model.get_relation("sees")
            if relation:
                for key in self.config_dict:
                    relation.data[self.model.app][key] = str(self.config_dict[key])


class SeesProvides(Object):
    """This class defines the functionality for the 'provides' side of the
    'sees' relation.

    Hook events observed:
        - relation-changed
    """

    def __init__(self, charm):
        super().__init__(charm, "sees")
        # Observe the relation-changed hook event and bind
        # self._on_relation_changed() to handle the event.
        self.framework.observe(charm.on["sees"].relation_changed,
                               self._on_relation_changed)
        self.charm = charm

    def _on_relation_changed(self, event):
        """Handle a change to the sees relation.

        Confirm we have the fields we expect to receive."""
        # `self.unit` isn't available here, so use `self.model.unit`.
        if not self.model.unit.is_leader():
            return

        sees_data = {
            field: event.relation.data[event.app].get(field)
            for field in REQUIRED_SEES_RELATION_FIELDS | OPTIONAL_SEES_RELATION_FIELDS
        }

        missing_fields = sorted(
            [
                field
                for field in REQUIRED_SEES_RELATION_FIELDS
                if sees_data.get(field) is None
            ]
        )

        if missing_fields:
            logger.error(
                "Missing required data fields for sees relation: {}".format(
                    ", ".join(missing_fields)
                )
            )
            self.model.unit.status = BlockedStatus(
                "Missing fields for sees: {}".format(", ".join(missing_fields))
            )

        # Create an event that our charm can use to decide it's okay to
        # configure the sees.
        self.charm.on.sees_available.emit()
