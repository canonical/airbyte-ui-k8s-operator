# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm integration tests."""

import logging
import socket
import unittest.mock

import pytest
import requests
from helpers import APP_NAME_AIRBYTE_UI, gen_patch_getaddrinfo, get_unit_url
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestDeployment:
    """Integration tests for Airbyte UI charm."""

    async def test_basic_client(self, ops_test: OpsTest):
        """Perform GET request on the Airbyte UI host."""
        url = await get_unit_url(ops_test, APP_NAME_AIRBYTE_UI, 0, 8080)
        logger.info("curling app address: %s", url)

        response = requests.get(url, timeout=300)
        assert response.status_code == 200

    async def test_ingress(self, ops_test: OpsTest):
        """Set external-hostname and test connectivity through ingress."""
        new_hostname = "airbyte-web"
        application = ops_test.model.applications[APP_NAME_AIRBYTE_UI]
        await application.set_config({"external-hostname": new_hostname})

        async with ops_test.fast_forward():
            await ops_test.model.wait_for_idle(
                apps=[APP_NAME_AIRBYTE_UI, "nginx-ingress-integrator"],
                status="active",
                raise_on_blocked=False,
                idle_period=30,
                timeout=1200,
            )

            with unittest.mock.patch.multiple(socket, getaddrinfo=gen_patch_getaddrinfo(new_hostname, "127.0.0.1")):
                response = requests.get(f"https://{new_hostname}", timeout=5, verify=False)  # nosec
                assert (
                    response.status_code == 200
                    and 'content="Airbyte is the turnkey open-source data integration platform that syncs data from applications, APIs and databases to warehouses."'
                    in response.text
                )

    async def test_restart_action(self, ops_test: OpsTest):
        """Test charm restart action."""
        action = await ops_test.model.applications[APP_NAME_AIRBYTE_UI].units[0].run_action("restart")
        await action.wait()

        async with ops_test.fast_forward():
            await ops_test.model.wait_for_idle(
                apps=[APP_NAME_AIRBYTE_UI],
                status="active",
                raise_on_blocked=False,
                timeout=600,
            )

            assert ops_test.model.applications[APP_NAME_AIRBYTE_UI].units[0].workload_status == "active"
