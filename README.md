# Overview

The nova-cloud-controller charm deploys a suite of OpenStack Nova services:

* [nova-api][upstream-nova-api]
* [nova-conductor][upstream-nova-conductor]
* [nova-scheduler][upstream-nova-scheduler]

# Usage

## Configuration

This section covers common and/or important configuration options. See file
`config.yaml` for the full list of options, along with their descriptions and
default values. See the [Juju documentation][juju-docs-config-apps] for details
on configuring applications.

#### `cache-known-hosts`

Controls whether or not the charm will use the current cache for hostname/IP
resolution queries for nova-compute units. This occurs whenever information
that is passed over the `nova-compute:cloud-compute` relation changes (e.g. a
nova-compute unit is added). The default value is 'true'. See section [SSH host
lookup caching][anchor-ssh-caching] for details.

#### `console-proxy-ip`

Sets a client accessible proxy IP address that allows for VM console access. It
should route to the nova-cloud-controller unit when the application is not
under HA. When it is, the value of 'local' will point to the VIP.

Ensure that option `console-access-protocol` is set to a value other than
'None'.

VNC clients should be configured accordingly. In the case of a VIP, it will
need to be determined.

#### `console-access-protocol`

Specifies the protocol to use when accessing the console of a VM. Supported
values are: 'None', 'spice', 'xvpvnc', 'novnc', and 'vnc' (for both xvpvnc and
novnc). Type 'xvpvnc' is not supported with UCA release 'bionic-ussuri' or with
series 'focal' or later.

> **Caution**: VMs are configured with a specific protocol at creation time.
  Console access for existing VMs will therefore break if this value is changed
  to something different.

#### `network-manager`

Defines the network manager for the cloud. Supported values are:

* 'FlatDHCPManager' for nova-network (the default)
* 'FlatManager' - for nova-network
* 'Neutron' - for a full SDN solution

When using 'Neutron' the [neutron-gateway][neutron-gateway-charm] charm should
be used to provide L3 routing and DHCP Services.

#### PCI tracking in Placement

From the Antelope release, `pci-in-placement` enables Nova API, scheduler, and
conductor processes to schedule and claim PCI devices through Placement. PCI
aliases may request custom Placement resource classes.

Before enabling this option, configure `pci-device-spec` and enable
`pci-report-in-placement` on every relevant nova-compute application. Allow the
compute services to reconcile, then verify their PCI child resource providers
and inventories in Placement. Enabling controller-side scheduling before all
computes report their PCI inventories can prevent valid PCI requests from
scheduling.

#### `openstack-origin`

States the software sources. A common value is an OpenStack UCA release (e.g.
'cloud:bionic-ussuri' or 'cloud:focal-wallaby'). See [Ubuntu Cloud
Archive][wiki-uca]. The underlying host's existing apt sources will be used if
this option is not specified (this behaviour can be explicitly chosen by using
the value of 'distro').

## Deployment

These deployment instructions assume the following applications are present:
keystone, rabbitmq-server, neutron-api, nova-compute, and a cloud database.

File ``ncc.yaml`` contains an example configuration:

```yaml
   nova-cloud-controller:
     network-manager: Neutron
     openstack-origin: cloud:focal-wallaby
```

Nova cloud controller is often containerised. Here a single unit is deployed to
a new container on machine '3':

    juju deploy --to lxd:3 --config ncc.yaml nova-cloud-controller

> **Note**: The cloud's database is determined by the series: prior to focal
  [percona-cluster][percona-cluster-charm] is used, otherwise it is
  [mysql-innodb-cluster][mysql-innodb-cluster-charm]. In the example deployment
  below mysql-innodb-cluster is used.

Join nova-cloud-controller to the cloud database:

    juju deploy mysql-router ncc-mysql-router
    juju add-relation ncc-mysql-router:db-router mysql-innodb-cluster:db-router
    juju add-relation ncc-mysql-router:shared-db nova-cloud-controller:shared-db

Five additional relations can be added:

    juju add-relation nova-cloud-controller:identity-service keystone:identity-service
    juju add-relation nova-cloud-controller:amqp rabbitmq-server:amqp
    juju add-relation nova-cloud-controller:neutron-api neutron-api:neutron-api
    juju add-relation nova-cloud-controller:cloud-compute nova-compute:cloud-compute

### TLS

Enable TLS by adding a relation to an existing vault application:

    juju add-relation nova-cloud-controller:certificates vault:certificates

See [Managing TLS certificates][cdg-tls] in the
[OpenStack Charms Deployment Guide][cdg] for more information on TLS.

> **Note**: This charm also supports TLS configuration via charm options
  `ssl_cert`, `ssl_key`, and `ssl_ca`.

## Actions

This section covers Juju [actions][juju-docs-actions] supported by the charm.
Actions allow specific operations to be performed on a per-unit basis. To
display action descriptions run `juju actions --schema nova-cloud-controller`.
If the charm is not deployed then see file `actions.yaml`.

* `archive-data`
* `clear-unit-knownhost-cache`
* `openstack-upgrade`
* `pause`
* `resume`
* `security-checklist`
* `sync-compute-availability-zones`

## High availability

When more than one unit is deployed with the [hacluster][hacluster-charm]
application the charm will bring up an HA active/active cluster.

There are two mutually exclusive high availability options: using virtual IP(s)
or DNS. In both cases the hacluster subordinate charm is used to provide the
Corosync and Pacemaker backend HA functionality.

See [OpenStack high availability][cdg-ha-apps] in the [OpenStack Charms
Deployment Guide][cdg] for details.

## Spaces

This charm supports the use of Juju Network Spaces, allowing the charm to be
bound to network space configurations managed directly by Juju.  This is only
supported with Juju 2.0 and above.

API endpoints can be bound to distinct network spaces supporting the network
separation of public, internal and admin endpoints.

Access to the underlying MySQL instance can also be bound to a specific space
using the shared-db relation.

To use this feature, use the --bind option when deploying the charm:

    juju deploy nova-cloud-controller --bind \
       "public=public-space \
        internal=internal-space \
        admin=admin-space \
        shared-db=internal-space"

Alternatively, these can also be provided as part of a Juju native bundle
configuration:

```yaml
    nova-cloud-controller:
      charm: cs:xenial/nova-cloud-controller
      num_units: 1
      bindings:
        public: public-space
        admin: admin-space
        internal: internal-space
        shared-db: internal-space
```

> **Note**: Spaces must be configured in the underlying provider prior to
  attempting to use them.

> **Note**: Existing deployments using `os-*-network` configuration options
  will continue to function; these options are preferred over any network space
  binding provided if set.

## Charm-managed quotas

The charm can optionally set project quotas, which affect both new and existing
projects. These quotas are set with the following configuration options:

* `quota-cores`
* `quota-count-usage-from-placement`
* `quota-injected-files`
* `quota-injected-file-size`
* `quota-injected-path-size`
* `quota-instances`
* `quota-key-pairs`
* `quota-metadata-items`
* `quota-ram`
* `quota-server-groups`
* `quota-server-group-members`

Given that OpenStack quotas can be set in a variety of ways, the order of
precedence (from higher to lower) for the enforcing of quotas is:

1. quotas set by the operator manually
1. quotas set by the nova-cloud-controller charm
1. default quotas of the OpenStack service

For information on OpenStack quotas see [Manage quotas][upstream-nova-quotas]
in the Nova documentation.

## SSH host lookup caching

Caching SSH known hosts reduces 'cloud-compute' hook execution time. It does
this by reducing the number of lookups performed by the nova-cloud-controller
charm during SSH connection negotiations when distributing a new unit's SSH
keys among existing units of the same application group. These keys are needed
for VM migrations to succeed.

The cache is populated (or refreshed) when option `cache-known-hosts` is set to
'false', in which case DNS lookups are always performed. The cache is queried
by the charm when it is set to 'true', where a lookup is only performed (adding
the result to the cache) when the cache is unable satisfy the query.

When a modification is made to DNS resolution, the `clear-unit-knownhost-cache`
action should be used. This action refreshes the charm's cache and updates the
`known_hosts` file on the nova-compute units. Information can be updated
selectively by targeting a specific unit, an application group, or all
application groups:

    juju run-action --wait nova-cloud-controller/0 clear-unit-knownhost-cache target=nova-compute/2
    juju run-action --wait nova-cloud-controller/0 clear-unit-knownhost-cache target=nova-compute
    juju run-action --wait nova-cloud-controller/0 clear-unit-knownhost-cache

When nova-cloud-controller is under HA, the same invocation must be run on all
nova-cloud-controller units.

## Policy overrides

Policy overrides is an advanced feature that allows an operator to override the
default policy of an OpenStack service. The policies that the service supports,
the defaults it implements in its code, and the defaults that a charm may
include should all be clearly understood before proceeding.

> **Caution**: It is possible to break the system (for tenants and other
  services) if policies are incorrectly applied to the service.

Policy statements are placed in a YAML file. This file (or files) is then (ZIP)
compressed into a single file and used as an application resource. The override
is then enabled via a Boolean charm option.

Here are the essential commands (filenames are arbitrary):

    zip overrides.zip override-file.yaml
    juju attach-resource nova-cloud-controller policyd-override=overrides.zip
    juju config nova-cloud-controller use-policyd-override=true

See appendix [Policy overrides][cdg-appendix-n] in the [OpenStack Charms
Deployment Guide][cdg] for a thorough treatment of this feature.

# Documentation

The OpenStack Charms project maintains two documentation guides:

* [OpenStack Charm Guide][cg]: for project information, including development
  and support notes
* [OpenStack Charms Deployment Guide][cdg]: for charm usage information

# Bugs

Please report bugs on [Launchpad][lp-bugs-charm-nova-cloud-controller].

<!-- LINKS -->

[cg]: https://docs.openstack.org/charm-guide
[cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide
[cdg-appendix-n]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-policy-overrides.html
[lp-bugs-charm-nova-cloud-controller]: https://bugs.launchpad.net/charm-nova-cloud-controller/+filebug
[cdg-ha-apps]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-ha.html#ha-applications
[hacluster-charm]: https://jaas.ai/hacluster
[neutron-gateway-charm]: https://jaas.ai/neutron-gateway
[upstream-nova-quotas]: https://docs.openstack.org/nova/latest/admin/quotas.html
[juju-docs-actions]: https://jaas.ai/docs/actions
[juju-docs-config-apps]: https://juju.is/docs/configuring-applications
[wiki-uca]: https://wiki.ubuntu.com/OpenStack/CloudArchive
[anchor-ssh-caching]: #ssh-host-lookup-caching
[percona-cluster-charm]: https://jaas.ai/percona-cluster
[mysql-innodb-cluster-charm]: https://jaas.ai/mysql-innodb-cluster
[vault-charm]: https://jaas.ai/vault
[cdg-tls]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-certificate-management.html
[upstream-nova-api]: https://docs.openstack.org/nova/latest/cli/nova-api.html
[upstream-nova-conductor]: https://docs.openstack.org/nova/latest/cli/nova-conductor.html
[upstream-nova-scheduler]: https://docs.openstack.org/nova/latest/cli/nova-scheduler.html
