[![Charmhub Badge](https://charmhub.io/airbyte-ui-k8s/badge.svg)](https://charmhub.io/airbyte-ui-k8s)
[![Release Edge](https://github.com/canonical/airbyte-ui-k8s-operator/actions/workflows/publish_charm.yaml/badge.svg)](https://github.com/canonical/airbyte-ui-k8s-operator/actions/workflows/publish_charm.yaml)

# Airbyte UI K8s Operator

This is the Kubernetes Python Operator for the
[Airbyte web UI](https://airbyte.com/).

## Description

Airbyte is an open-source data integration platform designed to centralize and
streamline the process of extracting and loading data from various sources into
data warehouses, lakes, or other destinations.

This operator provides the Airbyte web UI, and consists of Python scripts which
wraps the versions distributed by
[Airbyte](https://hub.docker.com/r/airbyte/webapp).

## Usage

Please check the [Airbyte server operator](https://charmhub.io/airbyte-k8s) for
usage instructions.

## Contributing

This charm is still in active development. Please see the
[Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this
charm following best practice guidelines, and `CONTRIBUTING.md` for developer
guidance.

## License

The Charmed Airbyte UI K8s Operator is free software, distributed under the
Apache Software License, version 2.0. See [License](LICENSE) for more details.
