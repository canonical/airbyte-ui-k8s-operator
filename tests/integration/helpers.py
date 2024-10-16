# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# flake8: noqa

"""Charm integration test helpers."""

import logging
import socket
from datetime import timedelta
from pathlib import Path

import yaml
from pytest_operator.plugin import OpsTest
from temporal_client.activities import say_hello
from temporal_client.workflows import SayHello
from temporalio.client import Client
from temporalio.worker import Worker

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME_AIRBYTE_UI = METADATA["name"]
APP_NAME_AIRBYTE_SERVER = "airbyte-k8s"
APP_NAME_TEMPORAL_SERVER = "temporal-k8s"
APP_NAME_TEMPORAL_ADMIN = "temporal-admin-k8s"
APP_NAME_TEMPORAL_UI = "temporal-ui-k8s"


def gen_patch_getaddrinfo(host: str, resolve_to: str):  # noqa
    """Generate patched getaddrinfo function.

    This function is used to generate a patched getaddrinfo function that will resolve to the
    resolve_to address without having to actually register a host.

    Args:
        host: intended hostname of a given application.
        resolve_to: destination address for host to resolve to.
    Returns:
        A patching function for getaddrinfo.
    """
    original_getaddrinfo = socket.getaddrinfo

    def patched_getaddrinfo(*args):
        """Patch getaddrinfo to point to desired ip address.

        Args:
            args: original arguments to getaddrinfo when creating network connection.
        Returns:
            Patched getaddrinfo function.
        """
        if args[0] == host:
            return original_getaddrinfo(resolve_to, *args[1:])
        return original_getaddrinfo(*args)

    return patched_getaddrinfo


async def run_sample_workflow(ops_test: OpsTest):
    """Connect a client and runs a basic Temporal workflow.

    Args:
        ops_test: PyTest object.
    """
    url = await get_application_url(ops_test, application=APP_NAME_TEMPORAL_SERVER, port=7233)
    logger.info("running workflow on app address: %s", url)

    client = await Client.connect(url)

    # Run a worker for the workflow
    async with Worker(client, task_queue="my-task-queue", workflows=[SayHello], activities=[say_hello]):
        name = "Jean-luc"
        result = await client.execute_workflow(
            SayHello.run, name, id="my-workflow-id", task_queue="my-task-queue", run_timeout=timedelta(seconds=20)
        )
        logger.info(f"result: {result}")
        assert result == f"Hello, {name}!"


async def create_default_namespace(ops_test: OpsTest):
    """Creates default namespace on Temporal server using tctl.

    Args:
        ops_test: PyTest object.
    """
    # Register default namespace from admin charm.
    action = (
        await ops_test.model.applications[APP_NAME_TEMPORAL_ADMIN]
        .units[0]
        .run_action("tctl", args="--ns default namespace register -rd 3")
    )
    result = (await action.wait()).results
    logger.info(f"tctl result: {result}")
    assert "result" in result and result["result"] == "command succeeded"


async def get_application_url(ops_test: OpsTest, application, port):
    """Return application URL from the model.

    Args:
        ops_test: PyTest object.
        application: Name of the application.
        port: Port number of the URL.

    Returns:
        Application URL of the form {address}:{port}
    """
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][application].public_address
    return f"{address}:{port}"


async def get_unit_url(ops_test: OpsTest, application, unit, port, protocol="http"):
    """Return unit URL from the model.

    Args:
        ops_test: PyTest object.
        application: Name of the application.
        unit: Number of the unit.
        port: Port number of the URL.
        protocol: Transfer protocol (default: http).

    Returns:
        Unit URL of the form {protocol}://{address}:{port}
    """
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][application]["units"][f"{application}/{unit}"]["address"]
    return f"{protocol}://{address}:{port}"


async def perform_temporal_integrations(ops_test: OpsTest):
    """Integrate Temporal charm with postgresql, admin and ui charms.

    Args:
        ops_test: PyTest object.
    """
    await ops_test.model.integrate(f"{APP_NAME_TEMPORAL_SERVER}:db", "postgresql-k8s:database")
    await ops_test.model.integrate(f"{APP_NAME_TEMPORAL_SERVER}:visibility", "postgresql-k8s:database")
    await ops_test.model.integrate(f"{APP_NAME_TEMPORAL_SERVER}:admin", f"{APP_NAME_TEMPORAL_ADMIN}:admin")
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME_TEMPORAL_SERVER], status="active", raise_on_blocked=False, timeout=180
    )

    assert ops_test.model.applications[APP_NAME_TEMPORAL_SERVER].units[0].workload_status == "active"


async def perform_airbyte_integrations(ops_test: OpsTest):
    """Perform Airbyte charm integrations.

    Args:
        ops_test: PyTest object.
    """
    await ops_test.model.integrate(APP_NAME_AIRBYTE_SERVER, "postgresql-k8s")
    await ops_test.model.integrate(APP_NAME_AIRBYTE_SERVER, "minio")
    await ops_test.model.integrate(APP_NAME_AIRBYTE_SERVER, APP_NAME_AIRBYTE_UI)
    await ops_test.model.integrate(APP_NAME_AIRBYTE_UI, "nginx-ingress-integrator")

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME_AIRBYTE_SERVER, APP_NAME_AIRBYTE_UI, "nginx-ingress-integrator"],
        status="active",
        raise_on_blocked=False,
        timeout=240,
    )

    assert ops_test.model.applications[APP_NAME_AIRBYTE_SERVER].units[0].workload_status == "active"
    assert ops_test.model.applications[APP_NAME_AIRBYTE_UI].units[0].workload_status == "active"

    await run_sample_workflow(ops_test)
