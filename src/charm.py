#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm definition and helpers."""

import logging

from log import log_event_handler
from ops import main, pebble
from ops.charm import CharmBase
from ops.model import ActiveStatus, MaintenanceStatus
from ops.pebble import CheckStatus
from state import State

logger = logging.getLogger(__name__)

WEB_UI_PORT = 8080


class AirbyteK8SOperatorCharm(CharmBase):
    """Charm the application."""

    def __init__(self, *args):
        super().__init__(*args)
        self._state = State(self.app, lambda: self.model.get_relation("peer"))

        self.name = "airbyte-webapp"
        self.framework.observe(self.on[self.name].pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.restart_action, self._on_restart)

    @log_event_handler(logger)
    def _on_pebble_ready(self, event):
        """Handle pebble-ready event."""
        self._update(event)

    @log_event_handler(logger)
    def _on_update_status(self, event):
        """Handle `update-status` events.

        Args:
            event: The `update-status` event triggered at intervals.
        """
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
        self.unit.status = ActiveStatus()

        event.set_results({"result": "UI successfully restarted"})

    @log_event_handler(logger)
    def _update(self, event):
        """Update the Airbyte UI configuration and replan its execution.

        Args:
            event: The event triggered when the relation changed.
        """
        # TODO (kelkawi-a): validate presence of Airbyte server relation
        # TODO (kelkawi-a): update this to get server application name through charm relation
        context = {
            "API_URL": "/api/v1/",
            "AIRBYTE_EDITION": "community",
            "INTERNAL_API_HOST": "airbyte-k8s:8001",
            "CONNECTOR_BUILDER_API_HOST": "airbyte-k8s:80",
            "KEYCLOAK_INTERNAL_HOST": "localhost",
        }

        self.model.unit.set_ports(8080)
        container = self.unit.get_container(self.name)
        if not container.can_connect():
            event.defer()
            return

        pebble_layer = {
            "summary": "airbyte layer",
            "services": {
                self.name: {
                    "summary": "airbyte webapp",
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
    main.main(AirbyteK8SOperatorCharm)  # type: ignore
