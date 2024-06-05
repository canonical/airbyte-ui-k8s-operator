#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm definition and helpers."""

import logging

from charms.nginx_ingress_integrator.v0.nginx_route import require_nginx_route
from ops import main, pebble
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import CheckStatus

from log import log_event_handler
from relations.airbyte_server import AirbyteServer
from state import State

logger = logging.getLogger(__name__)

WEB_UI_PORT = 8080
INTERNAL_API_PORT = 8001
CONNECTOR_BUILDER_API_PORT = 80


class AirbyteUIK8sOperatorCharm(CharmBase):
    """Airbyte UI charm.

    Attrs:
        _state: used to store data that is persisted across invocations.
        external_hostname: DNS listing used for external connections.
    """

    @property
    def external_hostname(self):
        """Return the DNS listing used for external connections."""
        return self.config["external-hostname"] or self.app.name

    def __init__(self, *args):
        """Construct.

        Args:
            args: Ignore.
        """
        super().__init__(*args)
        self._state = State(self.app, lambda: self.model.get_relation("peer"))

        self.name = "airbyte-webapp"
        self.framework.observe(self.on[self.name].pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.restart_action, self._on_restart)
        self.framework.observe(self.on.peer_relation_changed, self._on_peer_relation_changed)

        # Handle Airbyte server relation
        self.airbyte_server = AirbyteServer(self)

        # Handle Ingress.
        self._require_nginx_route()

    def _require_nginx_route(self):
        """Require nginx-route relation based on current configuration."""
        require_nginx_route(
            charm=self,
            service_hostname=self.external_hostname,
            service_name=self.app.name,
            service_port=WEB_UI_PORT,
            tls_secret_name=self.config["tls-secret-name"],
            backend_protocol="HTTP",
        )

    @log_event_handler(logger)
    def _on_pebble_ready(self, event):
        """Handle pebble ready event.

        Args:
            event: The event triggered when the relation changed.
        """
        self._update(event)

    @log_event_handler(logger)
    def _on_peer_relation_changed(self, event):
        """Handle peer relation changed event.

        Args:
            event: The event triggered when the relation changed.
        """
        self._update(event)

    @log_event_handler(logger)
    def _on_update_status(self, event):
        """Handle `update-status` events.

        Args:
            event: The `update-status` event triggered at intervals.
        """
        try:
            self._validate()
        except ValueError:
            return

        container = self.unit.get_container(self.name)
        valid_pebble_plan = self._validate_pebble_plan(container)
        if not valid_pebble_plan:
            self._update(event)
            return

        check = container.get_check("up")
        if check.status != CheckStatus.UP:
            self.unit.status = MaintenanceStatus("Status check: DOWN")
            return

        self.unit.status = ActiveStatus()

    def _validate_pebble_plan(self, container):
        """Validate pebble plan.

        Args:
            container: application container

        Returns:
            bool of pebble plan validity
        """
        try:
            plan = container.get_plan().to_dict()
            return bool(plan["services"][self.name]["on-check-failure"])
        except (KeyError, pebble.ConnectionError):
            return False

    def _on_restart(self, event):
        """Restart Airbyte ui action handler.

        Args:
            event:The event triggered by the restart action
        """
        container = self.unit.get_container(self.name)
        if not container.can_connect():
            event.defer()
            return

        self.unit.status = MaintenanceStatus("restarting application")
        container.restart(self.name)

        event.set_results({"result": "UI successfully restarted"})

    def _validate(self):
        """Validate that configuration and relations are valid and ready.

        Raises:
            ValueError: in case of invalid configuration.
        """
        if not self._state.is_ready():
            raise ValueError("peer relation not ready")

        if not self._state.airbyte_server:
            raise ValueError("airbyte-server relation: not available")

        if not self._state.airbyte_server["status"] == "ready":
            raise ValueError("airbyte-server relation: server is not ready")

    @log_event_handler(logger)
    def _update(self, event):
        """Update the Airbyte UI configuration and replan its execution.

        Args:
            event: The event triggered when the relation changed.
        """
        try:
            self._validate()
        except ValueError as err:
            self.unit.status = BlockedStatus(str(err))
            return

        server_svc = self._state.airbyte_server["name"]
        context = {
            "API_URL": "/api/v1/",
            "AIRBYTE_EDITION": "community",
            "AIRBYTE_SERVER_HOST": f"{server_svc}:{INTERNAL_API_PORT}",
            "INTERNAL_API_HOST": f"{server_svc}:{INTERNAL_API_PORT}",
            "CONNECTOR_BUILDER_API_HOST": f"{server_svc}:{CONNECTOR_BUILDER_API_PORT}",
            "CONNECTOR_BUILDER_API_URL": "/connector-builder-api",
            "KEYCLOAK_INTERNAL_HOST": "localhost",
        }

        self.model.unit.set_ports(WEB_UI_PORT)
        container = self.unit.get_container(self.name)
        if not container.can_connect():
            event.defer()
            return

        pebble_layer = {
            "summary": "airbyte layer",
            "services": {
                self.name: {
                    "summary": self.name,
                    "command": "./docker-entrypoint.sh nginx",
                    "startup": "enabled",
                    "override": "replace",
                    # Including config values here so that a change in the
                    # config forces replanning to restart the service.
                    "environment": context,
                    "on-check-failure": {"up": "ignore"},
                },
            },
            "checks": {
                "up": {
                    "override": "replace",
                    "period": "10s",
                    "http": {"url": f"http://localhost:{WEB_UI_PORT}"},
                }
            },
        }
        container.add_layer(self.name, pebble_layer, combine=True)
        container.replan()

        self.unit.status = MaintenanceStatus("replanning application")


if __name__ == "__main__":  # pragma: nocover
    main.main(AirbyteUIK8sOperatorCharm)  # type: ignore
