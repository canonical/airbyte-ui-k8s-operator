# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing


"""Charm unit tests."""

# pylint:disable=protected-access

from unittest import TestCase, mock

from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import CheckStatus
from ops.testing import Harness

from charm import AirbyteUIK8sOperatorCharm
from literals import AIRBYTE_VERSION
from src.charm import CONNECTOR_BUILDER_API_PORT, INTERNAL_API_PORT, WEB_UI_PORT

APP_NAME = "airbyte-webapp"
mock_incomplete_pebble_plan = {"services": {"airbyte-webapp": {"override": "replace"}}}


class TestCharm(TestCase):
    """Unit tests for charm.

    Attrs:
        maxDiff: Specifies max difference shown by failed tests.
    """

    maxDiff = None

    def setUp(self):
        """Create setup for the unit tests."""
        self.harness = Harness(AirbyteUIK8sOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_can_connect(APP_NAME, True)
        self.harness.set_leader(True)
        self.harness.set_model_name("airbyte-model")
        self.harness.begin()

    def test_initial_plan(self):
        """The initial pebble plan is empty."""
        initial_plan = self.harness.get_container_pebble_plan(APP_NAME).to_dict()
        self.assertEqual(initial_plan, {})

    def test_blocked_by_peer_relation_not_ready(self):
        """The charm is blocked without a peer relation."""
        harness = self.harness

        # Simulate pebble readiness.
        container = harness.model.unit.get_container(APP_NAME)
        harness.charm.on.airbyte_webapp_pebble_ready.emit(container)

        # No plans are set yet.
        got_plan = harness.get_container_pebble_plan(APP_NAME).to_dict()
        self.assertEqual(got_plan, {})

        # The BlockStatus is set with a message.
        self.assertEqual(harness.model.unit.status, BlockedStatus("peer relation not ready"))

    def test_ingress(self):
        """The charm relates correctly to the nginx ingress charm and can be configured."""
        harness = self.harness

        simulate_lifecycle(harness)

        nginx_route_relation_id = harness.add_relation("nginx-route", "ingress")
        harness.charm._require_nginx_route()

        assert harness.get_relation_data(nginx_route_relation_id, harness.charm.app) == {
            "service-namespace": harness.charm.model.name,
            "service-hostname": harness.charm.app.name,
            "service-name": harness.charm.app.name,
            "service-port": str(WEB_UI_PORT),
            "tls-secret-name": "airbyte-tls",
            "backend-protocol": "HTTP",
        }

    def test_ingress_update_hostname(self):
        """The charm relates correctly to the nginx ingress charm and can be configured."""
        harness = self.harness

        simulate_lifecycle(harness)

        nginx_route_relation_id = harness.add_relation("nginx-route", "ingress")

        new_hostname = "new-airbyte-ui-k8s"
        harness.update_config({"external-hostname": new_hostname})
        harness.charm._require_nginx_route()

        assert harness.get_relation_data(nginx_route_relation_id, harness.charm.app) == {
            "service-namespace": harness.charm.model.name,
            "service-hostname": new_hostname,
            "service-name": harness.charm.app.name,
            "service-port": str(WEB_UI_PORT),
            "tls-secret-name": "airbyte-tls",
            "backend-protocol": "HTTP",
        }

    def test_ingress_update_tls(self):
        """The charm relates correctly to the nginx ingress charm and can be configured."""
        harness = self.harness

        simulate_lifecycle(harness)

        nginx_route_relation_id = harness.add_relation("nginx-route", "ingress")

        new_tls = "new-tls"
        harness.update_config({"tls-secret-name": new_tls})
        harness.charm._require_nginx_route()

        assert harness.get_relation_data(nginx_route_relation_id, harness.charm.app) == {
            "service-namespace": harness.charm.model.name,
            "service-hostname": harness.charm.app.name,
            "service-name": harness.charm.app.name,
            "service-port": str(WEB_UI_PORT),
            "tls-secret-name": new_tls,
            "backend-protocol": "HTTP",
        }

    def test_ready(self):
        """The pebble plan is correctly generated when the charm is ready."""
        harness = self.harness

        simulate_lifecycle(harness)

        # The plan is generated after pebble is ready.
        want_plan = {
            "services": {
                APP_NAME: {
                    "summary": APP_NAME,
                    "command": "/usr/bin/pnpm -C airbyte-platform/airbyte-webapp start oss-k8s",
                    "startup": "enabled",
                    "override": "replace",
                    "environment": {
                        "AIRBYTE_VERSION": AIRBYTE_VERSION,
                        "API_URL": "/api/v1/",
                        "AIRBYTE_EDITION": "community",
                        "AIRBYTE_SERVER_HOST": "airbyte-k8s:8001",
                        "CONNECTOR_BUILDER_API_URL": "/connector-builder-api",
                        "INTERNAL_API_HOST": f"airbyte-k8s:{INTERNAL_API_PORT}",
                        "CONNECTOR_BUILDER_API_HOST": f"airbyte-k8s:{CONNECTOR_BUILDER_API_PORT}",
                        "KEYCLOAK_INTERNAL_HOST": "localhost",
                        "PORT": 8080,
                    },
                    "on-check-failure": {"up": "ignore"},
                },
                "nginx": {
                    "summary": "NGINX service to serve Airbyte WebApp",
                    "command": "nginx -g 'daemon off;'",
                    "startup": "enabled",
                    "override": "replace",
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

        got_plan = harness.get_container_pebble_plan(APP_NAME).to_dict()
        self.assertEqual(got_plan, want_plan)

        # The service was started.
        service = harness.model.unit.get_container(APP_NAME).get_service(APP_NAME)
        self.assertTrue(service.is_running())

    def test_update_status_up(self):
        """The charm updates the unit status to active based on UP status."""
        harness = self.harness

        simulate_lifecycle(harness)

        container = harness.model.unit.get_container(APP_NAME)
        container.get_check = mock.Mock(status="up")
        container.get_check.return_value.status = CheckStatus.UP
        harness.charm.on.update_status.emit()

        self.assertEqual(harness.model.unit.status, ActiveStatus())

    def test_update_status_down(self):
        """The charm updates the unit status to maintenance based on DOWN status."""
        harness = self.harness

        simulate_lifecycle(harness)

        container = harness.model.unit.get_container(APP_NAME)
        container.get_check = mock.Mock(status="up")
        container.get_check.return_value.status = CheckStatus.DOWN
        harness.charm.on.update_status.emit()

        self.assertEqual(harness.model.unit.status, MaintenanceStatus("Status check: DOWN"))

    def test_incomplete_pebble_plan(self):
        """The charm re-applies the pebble plan if incomplete."""
        harness = self.harness
        simulate_lifecycle(harness)

        container = harness.model.unit.get_container(APP_NAME)
        container.add_layer(APP_NAME, mock_incomplete_pebble_plan, combine=True)
        harness.charm.on.update_status.emit()

        self.assertEqual(
            harness.model.unit.status,
            MaintenanceStatus("replanning application"),
        )
        plan = harness.get_container_pebble_plan(APP_NAME).to_dict()
        assert plan != mock_incomplete_pebble_plan

    @mock.patch("charm.AirbyteUIK8sOperatorCharm._validate_pebble_plan", return_value=True)
    def test_missing_pebble_plan(self, mock_validate_pebble_plan):
        """The charm re-applies the pebble plan if missing."""
        harness = self.harness
        simulate_lifecycle(harness)

        mock_validate_pebble_plan.return_value = False
        harness.charm.on.update_status.emit()
        self.assertEqual(
            harness.model.unit.status,
            MaintenanceStatus("replanning application"),
        )
        plan = harness.get_container_pebble_plan(APP_NAME).to_dict()
        assert plan is not None


def simulate_lifecycle(harness):
    """Simulate a healthy charm life-cycle.

    Args:
        harness: ops.testing.Harness object used to simulate charm lifecycle.
    """
    # Simulate pebble readiness.
    container = harness.model.unit.get_container(APP_NAME)
    harness.charm.on.airbyte_webapp_pebble_ready.emit(container)

    # Simulate peer relation readiness.
    harness.add_relation("peer", "airbyte")

    # Add the airbyte relation.
    harness.add_relation("airbyte-server", "airbyte-k8s")

    # Simulate server readiness.
    app = type("App", (), {"name": "airbyte-ui-k8s"})()
    relation = type(
        "Relation",
        (),
        {
            "data": {app: {"server_status": "ready", "server_name": "airbyte-k8s"}},
            "name": "ui",
            "id": 42,
        },
    )()
    unit = type("Unit", (), {"app": app, "name": "airbyte-ui-k8s/0"})()
    event = type("Event", (), {"app": app, "relation": relation, "unit": unit})()
    harness.charm.airbyte_server._on_airbyte_server_relation_changed(event)


def make_ui_changed_event(rel_name):
    """Create and return a mock relation changed event.

    The event is generated by the relation with the given name.

    Args:
        rel_name: Relationship name.

    Returns:
        Event dict.
    """
    return type(
        "Event",
        (),
        {
            "data": {"status": "ready", "name": "airbyte-k8s"},
            "relation": type("Relation", (), {"name": rel_name}),
        },
    )
