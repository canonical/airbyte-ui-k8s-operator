# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Airbyte server:ui relation."""

import logging

from log import log_event_handler
from ops import framework

logger = logging.getLogger(__name__)


class AirbyteServer(framework.Object):
    """Client for server:ui relation."""

    def __init__(self, charm):
        """Construct.

        Args:
            charm: The charm to attach the hooks to.
        """
        super().__init__(charm, "airbyte-server")
        self.charm = charm
        charm.framework.observe(
            charm.on.airbyte_server_relation_joined, self._on_airbyte_server_relation_changed
        )
        charm.framework.observe(
            charm.on.airbyte_server_relation_changed, self._on_airbyte_server_relation_changed
        )
        charm.framework.observe(
            charm.on.airbyte_server_relation_broken, self._on_airbyte_server_relation_broken
        )

    @log_event_handler(logger)
    def _on_airbyte_server_relation_changed(self, event):
        """Handle server:ui relation change event.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm.unit.is_leader():
            return

        if not self.charm._state.is_ready():
            event.defer()
            return

        self.charm._state.airbyte_server = {
            "name": event.relation.data[event.app].get("server_name"),
            "status": event.relation.data[event.app].get("server_status"),
        }
        self.charm._update(event)

    @log_event_handler(logger)
    def _on_airbyte_server_relation_broken(self, event):
        """Handle server:ui relation broken event.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm.unit.is_leader():
            return

        if not self.charm._state.is_ready():
            event.defer()
            return

        self.charm._state.airbyte_server = None
        self.charm._update(event)
