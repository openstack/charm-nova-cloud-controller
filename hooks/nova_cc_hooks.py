#!/usr/bin/env python3
#
# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse
import uuid


_path = os.path.dirname(os.path.realpath(__file__))
_root = os.path.abspath(os.path.join(_path, '..'))


def _add_path(path):
    if path not in sys.path:
        sys.path.insert(1, path)


_add_path(_root)


import charmhelpers.contrib.charmsupport.nrpe as nrpe
import charmhelpers.contrib.hahelpers.cluster as ch_cluster
import charmhelpers.contrib.hardening.harden as ch_harden
import charmhelpers.contrib.network.ip as ch_network_ip
import charmhelpers.contrib.openstack.cert_utils as cert_utils
import charmhelpers.contrib.openstack.context as ch_context
import charmhelpers.contrib.openstack.ha.utils as ch_ha_utils
import charmhelpers.contrib.openstack.ip as ch_ip
import charmhelpers.contrib.openstack.neutron as ch_neutron
import charmhelpers.contrib.openstack.policyd as policyd
import charmhelpers.contrib.openstack.utils as ch_utils
import charmhelpers.contrib.peerstorage as ch_peerstorage
import charmhelpers.core.hookenv as hookenv
import charmhelpers.core.host as ch_host
import charmhelpers.fetch as ch_fetch
import charmhelpers.payload.execd as execd

import hooks.nova_cc_common as common
import hooks.nova_cc_context as nova_cc_context
import hooks.nova_cc_utils as ncc_utils

try:
    FileNotFoundError
except NameError:
    # python3 compatibility
    FileNotFoundError = OSError

hooks = hookenv.Hooks()
# Note that CONFIGS is now set up via resolve_CONFIGS so that it is not a
# module load time constraint.
CONFIGS = None


def deferred_config(k):
    """Returns a callable that will return the config.  To be used with
    functions that need lazy evaluation because the run at loadtime, but the
    evaluation should happen at runtime.

    :param k: the config key to lookup
    :type k: Option[String, None]
    :returns: the result of config(k)
    """
    return lambda: hookenv.config(k)


def resolve_CONFIGS():
    """lazy function to resolve the CONFIGS so that it doesn't have to evaluate
    at module load time.  Note that it also returns the CONFIGS so that it can
    be used in other, module loadtime, functions.

    :returns: CONFIGS variable
    :rtype: `:class:templating.OSConfigRenderer`
    """
    global CONFIGS
    if CONFIGS is None:
        CONFIGS = ncc_utils.register_configs()
    return CONFIGS


def leader_init_db_if_ready(skip_acl_check=False, db_rid=None, unit=None):
    """Initialise db if leader and db not yet intialised.

    NOTE: must be called from database context.
    """
    if not hookenv.is_leader():
        hookenv.log("Not leader - skipping db init", level=hookenv.DEBUG)
        return

    if ncc_utils.is_db_initialised():
        hookenv.log("Database already initialised - skipping db init",
                    level=hookenv.DEBUG)
        return

    # Bugs 1353135 & 1187508. Dbs can appear to be ready before the units
    # acl entry has been added. So, if the db supports passing a list of
    # permitted units then check if we're in the list.
    allowed_units = hookenv.relation_get('nova_allowed_units',
                                         rid=db_rid, unit=unit)
    if skip_acl_check or (allowed_units and hookenv.local_unit() in
                          allowed_units.split()):
        hookenv.status_set('maintenance', 'Running nova db migration')
        ncc_utils.migrate_nova_databases()
        hookenv.log('Triggering remote restarts.')
        update_nova_relation(remote_restart=True)
    else:
        hookenv.log('allowed_units either not presented, or local unit '
                    'not in acl list: %s' % repr(allowed_units))


def leader_init_db_if_ready_allowed_units():
    """Loop through all related db units and attempt to initialize db

    By looping through all related db units, the relation ID and unit can
    be passed to leader_init_db_if_ready(), enabling use of allowed_units
    to determine if this nova-cc unit is allowed to perform db init.
    """
    rels = ['shared-db']
    for rname in rels:
        for rid in hookenv.relation_ids(rname):
            for unit in hookenv.related_units(rid):
                leader_init_db_if_ready(db_rid=rid, unit=unit)


def update_cell_db_if_ready(skip_acl_check=False, db_rid=None, unit=None):
    """Update the cells db if leader and db's are already intialised"""
    if not hookenv.is_leader():
        return

    if not ncc_utils.is_db_initialised():
        hookenv.log("Database not initialised - skipping cell db update",
                    level=hookenv.DEBUG)
        return

    if not ncc_utils.is_cellv2_init_ready():
        return

    allowed_units = hookenv.relation_get('nova_allowed_units',
                                         rid=db_rid, unit=unit)
    if skip_acl_check or (allowed_units and hookenv.local_unit() in
                          allowed_units.split()):
        ncc_utils.update_cell_database()
    else:
        hookenv.log('allowed_units either not presented, or local unit '
                    'not in acl list: %s' % repr(allowed_units))


def update_cell_db_if_ready_allowed_units():
    """Loop through all related db units and attempt to update cell db

    By looping through all related db units, the relation ID and unit can
    be passed to update_cell_db_if_ready(), enabling use of allowed_units
    to determine if this nova-cc unit is allowed to perform db updates.
    """
    rels = ['shared-db']
    for rname in rels:
        for rid in hookenv.relation_ids(rname):
            for unit in hookenv.related_units(rid):
                update_cell_db_if_ready(db_rid=rid, unit=unit)


def update_child_cell_records():
    for r_id in hookenv.relation_ids('nova-cell-api'):
        for unit in hookenv.related_units(relid=r_id):
            nova_cell_api_relation_changed(rid=r_id, unit=unit)


@hooks.hook('install.real')
@ch_harden.harden()
def install():
    hookenv.status_set('maintenance', 'Executing pre-install')
    execd.execd_preinstall()
    ch_utils.configure_installation_source(hookenv.config('openstack-origin'))

    hookenv.status_set('maintenance', 'Installing apt packages')
    ch_fetch.apt_update()
    # (ajkavanagh) LP: #1989538
    # Tactical fix to force openstack-release to match the configured
    # installation source; note that it comes after apt_update().
    ch_fetch.apt_install(['openstack-release'], fatal=False, quiet=True)
    ch_fetch.apt_install(ncc_utils.determine_packages(), fatal=True)

    ncc_utils.disable_package_apache_site()
    ncc_utils.stop_deprecated_services()

    _files = os.path.join(hookenv.charm_dir(), 'files')
    if os.path.isdir(_files):
        for f in os.listdir(_files):
            f = os.path.join(_files, f)
            if os.path.isfile(f):
                hookenv.log('Installing %s to /usr/bin' % f)
                shutil.copy2(f, '/usr/bin')
    for port in ncc_utils.determine_ports():
        hookenv.open_port(port)
    msg = 'Disabling services into db relation joined'
    hookenv.log(msg)
    hookenv.status_set('maintenance', msg)
    if not ch_utils.is_unit_paused_set():
        for svc in ncc_utils.services():
            ch_host.service_pause(svc)
    else:
        hookenv.log('Unit is in paused state, not issuing stop/pause '
                    'to all services')
    # call the policy overrides handler which will install any policy overrides
    policyd.maybe_do_policyd_overrides(
        ch_utils.os_release('nova-common'), 'nova')


@hooks.hook('config-changed')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map, stopstart=True)
@ch_harden.harden()
def config_changed():
    # if we are paused, delay doing any config changed hooks.
    # It is forced on the resume.
    if ch_utils.is_unit_paused_set():
        hookenv.log("Unit is pause or upgrading. Skipping config_changed",
                    hookenv.WARNING)
        return

    # neutron-server runs if < juno. Neutron-server creates mysql tables
    # which will subsequently cause db migrations to fail if >= juno.
    # Disable neutron-server if >= juno
    if ch_utils.CompareOpenStackReleases(
            ch_utils.os_release('nova-common')) >= 'juno':
        try:
            ch_host.service_pause('neutron-server')
        except ValueError:
            # neutron-server service not installed, ignore.
            pass
    if hookenv.config('prefer-ipv6'):
        hookenv.status_set('maintenance', 'configuring ipv6')
        ncc_utils.setup_ipv6()
        ch_utils.sync_db_with_multi_ipv6_addresses(
            hookenv.config('database'),
            hookenv.config('database-user'),
            relation_prefix='nova')

    global CONFIGS
    if not hookenv.config('action-managed-upgrade'):
        if ch_utils.openstack_upgrade_available('nova-common'):
            hookenv.status_set('maintenance', 'Running openstack upgrade')
            if not ncc_utils.do_openstack_upgrade(CONFIGS):
                return
            for rid in hookenv.relation_ids('neutron-api'):
                neutron_api_relation_joined(rid=rid, remote_restart=True)
            # NOTE(jamespage): Force re-fire of shared-db joined hook
            # to ensure that nova_api database is setup if required.
            for r_id in hookenv.relation_ids('shared-db'):
                db_joined(relation_id=r_id)

    ncc_utils.save_script_rc()
    configure_https()
    CONFIGS.write_all()

    # NOTE(jamespage): deal with any changes to the console and serial
    #                  console configuration options
    filtered = ch_fetch.filter_installed_packages(
        ncc_utils.determine_packages())
    if filtered:
        ch_fetch.apt_install(filtered, fatal=True)

    for r_id in hookenv.relation_ids('identity-service'):
        identity_joined(rid=r_id)
    for rid in hookenv.relation_ids('cluster'):
        cluster_joined(rid)
    update_nova_relation()

    update_nrpe_config()

    # If the region value has changed, notify the cloud-compute relations
    # to ensure the value is propagated to the compute nodes.
    if ch_utils.config_value_changed('region'):
        for rid in hookenv.relation_ids('cloud-compute'):
            set_region_on_relation_from_config(rid)

    ncc_utils.update_aws_compat_services()

    if hookenv.is_leader() and not ncc_utils.get_shared_metadatasecret():
        ncc_utils.set_shared_metadatasecret()
    publish_remote_metadata()
    for rid in hookenv.relation_ids('ha'):
        ha_joined(rid)
    if (not ch_utils.is_unit_paused_set() and
            ncc_utils.is_consoleauth_enabled()):
        ch_host.service_resume('nova-consoleauth')
    # call the policy overrides handler which will install any policy overrides
    policyd.maybe_do_policyd_overrides_on_config_changed(
        ch_utils.os_release('nova-common'), 'nova')


@hooks.hook('amqp-relation-joined')
def amqp_joined(relation_id=None):
    hookenv.relation_set(relation_id=relation_id,
                         username=hookenv.config('rabbit-user'),
                         vhost=hookenv.config('rabbit-vhost'))


@hooks.hook('amqp-relation-changed')
@hooks.hook('amqp-relation-departed')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def amqp_changed():
    if 'amqp' not in CONFIGS.complete_contexts():
        hookenv.log('amqp relation incomplete. Peer not ready?')
        return
    CONFIGS.write(ncc_utils.NOVA_CONF)
    if ch_utils.is_db_maintenance_mode():
        hookenv.log(
            'Database maintenance mode, defering db updates.',
            level=hookenv.DEBUG)
    else:
        leader_init_db_if_ready_allowed_units()
        # db init for cells v2 requires amqp transport_url and db connections
        # to be set in nova.conf, so we attempt db init in here as well as the
        # db relation-changed hooks.
        update_cell_db_if_ready_allowed_units()

        update_child_cell_records()

    if hookenv.is_leader():
        # NOTE: trigger restart on nova-api-metadata on
        #       neutron-gateway units once nova-cc has working
        #       amqp connection (avoiding service down on n-gateway)
        #       Also trigger restart of nova-compute Bug #1861094
        update_nova_relation(remote_restart=True)


@hooks.hook('shared-db-relation-joined')
def db_joined(relation_id=None):
    cmp_os_release = ch_utils.CompareOpenStackReleases(
        ch_utils.os_release('nova-common'))
    if hookenv.config('prefer-ipv6'):
        ch_utils.sync_db_with_multi_ipv6_addresses(
            hookenv.config('database'),
            hookenv.config('database-user'),
            relation_prefix='nova')

        if cmp_os_release >= 'mitaka':
            # NOTE: mitaka uses a second nova-api database as well
            ch_utils.sync_db_with_multi_ipv6_addresses(
                'nova_api',
                hookenv.config('database-user'),
                relation_prefix='novaapi')

        if cmp_os_release >= 'ocata':
            # NOTE: ocata requires cells v2
            ch_utils.sync_db_with_multi_ipv6_addresses(
                'nova_cell0',
                hookenv.config('database-user'),
                relation_prefix='novacell0')
    else:
        # Avoid churn check for access-network early
        access_network = None
        for unit in hookenv.related_units(relid=relation_id):
            access_network = hookenv.relation_get(rid=relation_id, unit=unit,
                                                  attribute='access-network')
            if access_network:
                break
        host = ch_network_ip.get_relation_ip('shared-db',
                                             cidr_network=access_network)

        hookenv.relation_set(nova_database=hookenv.config('database'),
                             nova_username=hookenv.config('database-user'),
                             nova_hostname=host,
                             relation_id=relation_id)

        if cmp_os_release >= 'mitaka':
            # NOTE: mitaka uses a second nova-api database as well
            hookenv.relation_set(
                novaapi_database='nova_api',
                novaapi_username=hookenv.config('database-user'),
                novaapi_hostname=host,
                relation_id=relation_id)

        if cmp_os_release >= 'ocata':
            # NOTE: ocata requires cells v2
            hookenv.relation_set(
                novacell0_database='nova_cell0',
                novacell0_username=hookenv.config('database-user'),
                novacell0_hostname=host,
                relation_id=relation_id)


@hooks.hook('shared-db-relation-changed')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def db_changed():
    if 'shared-db' not in CONFIGS.complete_contexts():
        hookenv.log('shared-db relation incomplete. Peer not ready?')
        return

    if ch_utils.is_db_maintenance_mode():
        hookenv.log(
            'Database maintenance mode, aborting hook.',
            level=hookenv.DEBUG)
        return

    CONFIGS.write_all()
    leader_init_db_if_ready()
    # db init for cells v2 requires amqp transport_url and db connections to
    # be set in nova.conf, so we attempt db init in here as well as the
    # amqp-relation-changed hook.
    update_cell_db_if_ready()
    update_child_cell_records()


@hooks.hook('image-service-relation-changed')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def image_service_changed():
    if 'image-service' not in CONFIGS.complete_contexts():
        hookenv.log('image-service relation incomplete. Peer not ready?')
        return
    CONFIGS.write(ncc_utils.NOVA_CONF)
    # TODO: special case config flag for essex (strip protocol)


@hooks.hook('identity-service-relation-joined')
def identity_joined(rid=None):
    if hookenv.config('vip') and not ch_cluster.is_clustered():
        hookenv.log('Defering registration until clustered',
                    level=hookenv.DEBUG)
        return
    public_url = ch_ip.canonical_url(CONFIGS, ch_ip.PUBLIC)
    internal_url = ch_ip.canonical_url(CONFIGS, ch_ip.INTERNAL)
    admin_url = ch_ip.canonical_url(CONFIGS, ch_ip.ADMIN)
    settings = ncc_utils.determine_endpoints(
        public_url,
        internal_url,
        admin_url)
    settings['subscribe_ep_change'] = 'neutron placement'
    hookenv.relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook('identity-service-relation-changed')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def identity_changed():
    if 'identity-service' not in CONFIGS.complete_contexts():
        hookenv.log('identity-service relation incomplete. Peer not ready?')
        return
    CONFIGS.write('/etc/nova/api-paste.ini')
    CONFIGS.write(ncc_utils.NOVA_CONF)
    update_nova_relation()
    for rid in hookenv.relation_ids('nova-vmware'):
        nova_vmware_relation_joined(rid)
    for rid in hookenv.relation_ids('neutron-api'):
        neutron_api_relation_joined(rid)
    configure_https()
    if ch_utils.endpoint_changed('placement'):
        hookenv.log("Placement endpoint has changed, restarting services",
                    "INFO")
        restart_delay = 0
        for rid in hookenv.relation_ids('identity-service'):
            for unit in hookenv.related_units(relid=rid):
                _delay = hookenv.relation_get(
                    rid=rid,
                    unit=unit,
                    attribute='catalog_ttl')
                if _delay and int(_delay) > restart_delay:
                    restart_delay = int(_delay)
        hookenv.log("Waiting for catalog cache ttl to expire {}".format(
            restart_delay), "INFO")
        hookenv.status_set(
            'maintenance',
            'Waiting for cache expiry before restart')
        time.sleep(restart_delay)
        hookenv.status_set(
            'active',
            'Restart complete')
        for service in ['nova-scheduler', 'nova-conductor']:
            ch_host.service_restart(service)
        hookenv.log(("Placement endpoint has changed, requesting nova-compute "
                     "restart"),
                    "INFO")
        for rid in hookenv.relation_ids('cloud-compute'):
            compute_joined(rid=rid, remote_restart=True)
        ch_utils.save_endpoint_changed_triggers(['placement'])


@hooks.hook('nova-volume-service-relation-joined',
            'cinder-volume-service-relation-joined')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def volume_joined():
    CONFIGS.write(ncc_utils.NOVA_CONF)
    # kick identity_joined() to publish possibly new nova-volume endpoint.
    for rid in hookenv.relation_ids('identity-service'):
        identity_joined(rid)


def _auth_config():
    '''Grab all KS auth token config from api-paste.ini, or return empty {}'''
    ks_auth_host = ncc_utils.auth_token_config('auth_host')
    if not ks_auth_host:
        # if there is no auth_host set, identity-service changed hooks
        # have not fired, yet.
        return {}
    cfg = {
        'auth_host': ks_auth_host,
        'auth_port': ncc_utils.auth_token_config('auth_port'),
        'auth_protocol': ncc_utils.auth_token_config('auth_protocol'),
        'service_protocol': ncc_utils.auth_token_config('service_protocol'),
        'service_port': ncc_utils.auth_token_config('service_port'),
        'service_username': ncc_utils.auth_token_config('admin_user'),
        'service_password': ncc_utils.auth_token_config('admin_password'),
        'service_tenant_name': ncc_utils.auth_token_config(
            'admin_tenant_name'),
        'auth_uri': ncc_utils.auth_token_config('auth_uri'),
        # quantum-gateway interface deviates a bit.
        'keystone_host': ks_auth_host,
        'service_tenant': ncc_utils.auth_token_config('admin_tenant_name'),
        # add api version if found
        'api_version': ncc_utils.auth_token_config('api_version') or '3.0',
        'admin_domain_name': ncc_utils.auth_token_config('admin_domain_name')
    }
    return cfg


def save_novarc():
    auth = _auth_config()
    # XXX hard-coded http
    ks_url = '%s://%s:%s/v%s' % (auth['auth_protocol'],
                                 auth['auth_host'],
                                 auth['auth_port'],
                                 auth['api_version'])
    with open('/etc/quantum/novarc', 'wb') as out:
        out.write('export OS_USERNAME=%s\n' % auth['service_username'])
        out.write('export OS_PASSWORD=%s\n' % auth['service_password'])
        out.write('export OS_TENANT_NAME=%s\n' % auth['service_tenant_name'])
        out.write('export OS_AUTH_URL=%s\n' % ks_url)
        out.write('export OS_REGION_NAME=%s\n' % hookenv.config('region'))


def neutron_settings():
    neutron_settings = {}
    if hookenv.is_relation_made('neutron-api', 'neutron-plugin'):
        neutron_api_info = nova_cc_context.NeutronAPIContext()()
        neutron_settings.update({
            # XXX: Rename these relations settings?
            'quantum_plugin': neutron_api_info['neutron_plugin'],
            'region': hookenv.config('region'),
            'quantum_security_groups':
            neutron_api_info['neutron_security_groups'],
            'quantum_url': neutron_api_info['neutron_url'],
        })
        # DNS domain is optional
        if neutron_api_info.get('dns_domain'):
            neutron_settings['dns_domain'] = neutron_api_info['dns_domain']
        neutron_url = urlparse(neutron_settings['quantum_url'])
        neutron_settings['quantum_host'] = neutron_url.hostname
        neutron_settings['quantum_port'] = neutron_url.port
    return neutron_settings


def keystone_compute_settings():
    ks_auth_config = _auth_config()
    rel_settings = {}

    if ch_neutron.network_manager() == 'neutron':
        if ks_auth_config:
            rel_settings.update(ks_auth_config)
        rel_settings.update(neutron_settings())
    ca = ncc_utils.get_ca_cert_b64()
    if ca:
        rel_settings['ca_cert'] = ca
    return rel_settings


def console_settings():
    rel_settings = {}
    proto = common.console_attributes('protocol')
    if not proto:
        return {'console_access_protocol': None}
    rel_settings['console_keymap'] = hookenv.config('console-keymap')
    rel_settings['console_access_protocol'] = proto

    console_ssl = False
    if (hookenv.config('console-ssl-cert') and
            hookenv.config('console-ssl-key')):
        console_ssl = True

    if hookenv.config('console-proxy-ip') == 'local':
        if console_ssl:
            address = ch_ip.resolve_address(endpoint_type=ch_ip.PUBLIC)
            address = ch_network_ip.format_ipv6_addr(address) or address
            proxy_base_addr = 'https://%s' % address
        else:
            # canonical_url will only return 'https:' if API SSL are enabled.
            proxy_base_addr = ch_ip.canonical_url(CONFIGS, ch_ip.PUBLIC)
    else:
        if console_ssl or ch_cluster.https():
            schema = "https"
        else:
            schema = "http"

        proxy_base_addr = ("{}://{}"
                           .format(schema, hookenv.config('console-proxy-ip')))

    if proto == 'vnc':
        protocols = ['novnc', 'xvpvnc']
    else:
        protocols = [proto]

    for _proto in protocols:
        rel_settings['console_proxy_{}_address'.format(_proto)] = \
            "{}:{}{}".format(
                proxy_base_addr,
                common.console_attributes('proxy-port', proto=_proto),
                common.console_attributes('proxy-page', proto=_proto))
        rel_settings['console_proxy_%s_host' % (_proto)] = \
            urlparse(proxy_base_addr).hostname
        rel_settings['console_proxy_%s_port' % (_proto)] = \
            common.console_attributes('proxy-port', proto=_proto)

    rel_settings['spice_agent_enabled'] = hookenv.config('spice-agent-enabled')

    return rel_settings


def get_compute_config(remote_restart=False):
    """Get the compute config as a dictionary to set on the relation.

    This gets the console settings (from console_settings()) the serial console
    settings and some additional items that are in the form suitable for a
    relation_set.

    :param remote_restart: whether a restart should be notified
    :type remote_restart: bool
    :returns: dictionary settings for the relation
    :rtype: Dict[str, ANY]
    """
    rel_settings = {
        'network_manager': ch_neutron.network_manager(),
        'volume_service': 'cinder',
        # (comment from bash vers) XXX Should point to VIP if clustered, or
        # this may not even be needed.
        'ec2_host': hookenv.unit_get('private-address'),
        'region': hookenv.config('region'),
        'cross_az_attach': hookenv.config('cross-az-attach'),
    }
    rel_settings.update(console_settings())
    rel_settings.update(ncc_utils.serial_console_settings())
    # update relation setting if we're attempting to restart remote
    # services
    if remote_restart:
        rel_settings['restart_trigger'] = str(uuid.uuid4())

    return rel_settings


def update_nova_relation(remote_restart=False):
    publish_remote_metadata()
    for rid in hookenv.relation_ids('cloud-compute'):
        compute_joined(rid=rid, remote_restart=remote_restart)
    for rid in hookenv.relation_ids('quantum-network-service'):
        quantum_joined(rid=rid, remote_restart=remote_restart)
    for rid in hookenv.relation_ids('nova-cell-api'):
        nova_cell_api_relation_joined(rid=rid, remote_restart=remote_restart)


@hooks.hook('cloud-compute-relation-joined')
def compute_joined(rid=None, remote_restart=False):
    rel_settings = get_compute_config(remote_restart=remote_restart)
    rel_settings.update(keystone_compute_settings())
    hookenv.relation_set(relation_id=rid, **rel_settings)


@hooks.hook('cloud-compute-relation-changed')
def cloud_compute_relation_changed():
    """Performs actions associated with when the cloud compute relation changes
    for a unit.

    * add hosts to the cell when ready
    * notifies the region to the unit, if it has changed
    * notifies the ssh known hosts and authorized keys to the unit
    """
    add_hosts_to_cell_when_ready()
    set_region_on_relation_from_config(rid=None)
    update_ssh_key(rid=None, unit=None)
    update_compute_units_with_ssh_key_change(rid=None, unit=None)


def add_hosts_to_cell_when_ready():
    """Helper function to call add_hosts_to_cell() when the unit is the leader
    and the cellv2 and database are ready.

    :raises: subprocess.CalledProcessError if cells command fails
    """
    if (hookenv.is_leader() and
            ncc_utils.is_cellv2_init_ready() and
            ncc_utils.is_db_initialised() and
            not ch_utils.is_db_maintenance_mode()):
        ncc_utils.add_hosts_to_cell()


def set_region_on_relation_from_config(rid=None):
    """Helper function that sets the new region for that relation to trigger a
    change for any units that see it differently.

    :param rid: The relation to set, or if None, the current one related
                to the hook.
    :type rid: Union[str. None]
    """
    hookenv.relation_set(relation_id=rid, region=hookenv.config('region'))


def set_cross_az_attach_on_relation_from_config(rid=None):
    """Helper function that sets the cross-az-attach policy for that relation
    to trigger a change for any units that see it differently.

    :param rid: The relation to set, or if None, the current one related
                to the hook.
    :type rid: Union[str, None]
    """
    hookenv.relation_set(relation_id=rid,
                         cross_az_attach=hookenv.config('cross-az-attach'))


def update_compute_units_with_ssh_key_change(rid=None, unit=None):
    """Notify the updated ssh keys to nova-compute units

    Notify all associated nova-compute units of the relation.

    If rid=None and unit=None, then this function is being called in the
    context of a cloud-compute relation changed hook.

    :param rid: The relation to check/set, or if None, the current one related
                to the hook.
    :type rid: Union[str. None]
    :param unit: the unit to check, of None for the current one according to
                  the hook.
    :type unit: Union[str, None]
    """

    # if we have goal state, then only notify the ssh authorized_keys and
    # known_hosts onto the relation when the last compute unit has arrived
    # (i.e. we've reached the goal state)
    rids = hookenv.relation_ids('cloud-compute')
    if all(_goal_state_achieved_for_relid('cloud-compute', rid)
           for rid in rids):
        # NOTE(ganso): we are either in a relation-changed hook of a specific
        # unit or already in a loop from upgrade-charm
        if rid is None and unit is None:
            for rid in rids:
                for unit in hookenv.related_units(rid):
                    notify_ssh_keys_to_compute_units(rid=rid, unit=unit)
        else:
            notify_ssh_keys_to_compute_units(rid=rid, unit=unit)


def _goal_state_achieved_for_relid(reltype, rid=None):
    """Check that the goal-state has been achieved for the reltype and relid.

    If goal state is not available, then the function returns True.
    Otherwise, as goal state (from Juju) replies with all the units for the
    relation type, without respect for the relation id.  i.e. normally, Juju is
    a hierarchy of relation type -> relation id -> units, but goal state is
    relation type -> units (where all the units across the relation ids are
    grouped.

    If the relid is None, then the relation_id for the hook is used (by the
    library function related_units()).

    Note this function checks a particular relation id for reaching goal state,
    not all relation ids.  To do that (with this function) do:

        all(_goal_state_achieved_for_relid(reltype, rid)
            for rid in relation_ids(reltype))

    :param reltype: the relation type (e.g. 'cloud-compute')
    :type reltype: str
    :param rid: the relation id, or None for the default
    :type rid: Union[str, None]
    :returns: True if goal state is achieved, or not available
    :rtype: bool
    """
    try:
        # There should always be one unit -- if not, this block KeyErrors and
        # so the goal is false.
        units_so_far = hookenv.related_units(relid=rid)
        # goal state returns all the units by the relation type (in this
        # case 'cloud-compute').  So we need to only check the ones with
        # the same prefix e.g. nova-compute/0, nova-compute/1 vs
        # nova-compute-b/0, etc if there were two separate relations to two
        # nova-compute applications
        all_units = list(
            hookenv.expected_related_units(reltype=reltype))
        prefix = units_so_far[0].split('/')[0]
        target_units = [u for u in all_units if u.split('/')[0] == prefix]
        # BUG: #1859050 -- the units may not necessarily be sorted, so we have
        # to compare sorted lists
        return sorted(units_so_far) == sorted(target_units)
    except (KeyError, IndexError):
        # expected_related_units() can raise a KeyError in the case there are
        # no units  - in that case assume that the goal wasn't met
        # if there are no units_so_far, then Index error is raised
        return False
    except NotImplementedError:
        # Not implemented means that goal state is not available
        pass
    return True


def update_ssh_key(rid=None, unit=None):
    """Update ssh keys for a nova-compute unit connected on the cloud-compute
    relation.

    If rid=None and unit=None, then this function is being called in the
    context of a cloud-compute relation changed hook, and will relate to that
    unit.  If rid and unit are set, then this function is being called to
    refresh/update all specified units.

    If the 'migration_auth_type' isn't 'ssh' or the 'nova_ssh_public_key' in
    the relation data from the connected nova-compute unit isn't available,
    then this function does nothing.  Note that the compute unit sets keys for
    the charm (root user) and the nova service (nova user), and these are
    supplied separately.  Note that the nova ssh public is processed (if
    available) even if the migration auth type is not 'ssh'.

    :param rid: The relation to check/set, or if None, the current one related
                to the hook.
    :type rid: Union[str, None]
    :param unit: the unit to check, of None for the current one according to
                 the hook.
    :type unit: Union[str, None]
    """
    rel_settings = hookenv.relation_get(rid=rid, unit=unit)

    migration_auth_type = rel_settings.get('migration_auth_type', None)

    # bail out of doing ANY ssh keys for the remote unit if not
    # migration_auth_type is set in that units relation_data
    if migration_auth_type is None:
        return

    remote_service = ncc_utils.remote_service_from_unit(unit)
    private_address = rel_settings.get('private-address', None)
    hostname = rel_settings.get('hostname', '')

    # only resolve the hosts once, so this is the memo for it
    resolved_hosts = []

    if migration_auth_type == 'ssh':
        # TODO(ajkavanagh) -- the hookenv was previous behaviour, but there
        # isn't a good place to put this yet; it will be moved or removed at
        # the end of the patch series.
        # hookenv.status_set('maintenance', 'configuring live migration')
        key = rel_settings.get('ssh_public_key')
        if not key:
            hookenv.log('SSH migration set but peer did not publish key.'
                        ' relation={}, unit={}'
                        .format(rid or hookenv.relation_id(),
                                unit or hookenv.remote_unit()))
            return

        resolved_hosts = ncc_utils.resolve_hosts_for(private_address,
                                                     hostname)
        # Ensure management address and fqdn always in known_hosts (see LP
        # 1969971)
        ingress_address = hookenv.ingress_address(rid=rid, unit=unit)
        if ingress_address:
            if ingress_address not in resolved_hosts:
                resolved_hosts.append(ingress_address)

            ingress_host = ncc_utils.resolve_hosts_for(ingress_address, None)
            if ingress_host:
                for host in ingress_host:
                    if host not in resolved_hosts:
                        resolved_hosts.append(host)

        # sort mainly for unit tests
        resolved_hosts = sorted(resolved_hosts)
        ncc_utils.ssh_compute_add_known_hosts(
            remote_service, resolved_hosts, user=None)
        ncc_utils.add_authorized_key_if_doesnt_exist(
            key, remote_service, private_address, user=None)

    nova_ssh_public_key = rel_settings.get('nova_ssh_public_key', None)

    # Always try to fetch the user 'nova' key on the remote compute unit
    if nova_ssh_public_key:
        # in the unlikely event the migration type wasn't ssh, we still have to
        # resolve the hosts
        if not resolved_hosts:
            resolved_hosts = ncc_utils.resolve_hosts_for(private_address,
                                                         hostname)
        ncc_utils.ssh_compute_add_known_hosts(
            remote_service, resolved_hosts, user='nova')
        ncc_utils.add_authorized_key_if_doesnt_exist(
            nova_ssh_public_key, remote_service, private_address, user='nova')


def notify_ssh_keys_to_compute_units(rid=None, unit=None):
    """Notify the updated ssh keys to nova-compute units

    Notify all associated nova-compute units of the relation.

    :param rid: The relation to check/set.
    :type rid: str
    :param unit: the unit to check
    :type unit: str
    """
    rel_settings = hookenv.relation_get(rid=rid, unit=unit)

    migration_auth_type = rel_settings.get('migration_auth_type', None)
    if migration_auth_type is None:
        return

    # We distribute the ssh keys of all nova-compute units from all
    # nova-compute charm apps
    remote_services = set(dir_.split('_')[0]
                          for dir_ in os.listdir(ncc_utils.NOVA_SSH_DIR))

    if migration_auth_type == 'ssh':
        _set_hosts_and_keys_on_relation(remote_services, rid, user=None)

    if rel_settings.get('nova_ssh_public_key', None):
        _set_hosts_and_keys_on_relation(remote_services, rid, user='nova')


def _set_hosts_and_keys_on_relation(remote_services, rid=None, user=None):
    """Set the known hosts and authorized keys on the relation specified.

    Takes the authorized_keys and known hosts collected from all of the related
    compute units (that have been processed) and sets them on the relation via
    the _batch_write_ssh_on_relation() helper.

    :param remote_services: the remote service related the keys/hosts
    :type remote_services: list[str]
    :param rid: The relation to check/set, or if None, the current one related
                to the hook.
    :type rid: Union[str. None]
    :type unit: Union[str, None]
    :param user: the user to use in the format strings, or None for default
    :type user: Union[str, None]
    """
    if user is not None:
        known_hosts_prefix = "{}_known_hosts".format(user)
        known_hosts_max_key = "{}_known_hosts_max_index".format(user)
        authorized_prefix = "{}_authorized_keys".format(user)
        authorized_keys_max_key = "{}_authorized_keys_max_index".format(user)
    else:
        known_hosts_prefix = "known_hosts"
        known_hosts_max_key = "known_hosts_max_index"
        authorized_prefix = "authorized_keys"
        authorized_keys_max_key = "authorized_keys_max_index"

    _batch_write_ssh_on_relation(
        rid, known_hosts_prefix, known_hosts_max_key,
        [line for svc in remote_services
         for line in ncc_utils.ssh_known_hosts_lines(svc, user=user)])

    _batch_write_ssh_on_relation(
        rid, authorized_prefix, authorized_keys_max_key,
        [line for svc in remote_services
         for line in ncc_utils.ssh_authorized_keys_lines(svc, user=user)])


def _batch_write_ssh_on_relation(rid, prefix, max_index, _iter):
    """Helper to set the relation data from an iterable to specified relation
    (which may be None to indicate the current, default, relation).  The prefix
    param is used to construct the key a "{prefix}_{index}" with index
    incrementing from 0 for each line delivered from the iterable.

    :param rid: The relation to check/set, or if None, the current one related
                to the hook.
    :type rid: Union[str, None]
    :param prefix: The prefix for writing the related index line (e.g.
                   known_hosts)
    :type prefix: str
    :param max_index_key: the key against which to set the maximum index that
                          was written (i.e. number of keys set).
    :param _iter: an iterable that returns the lines to associate with keys
    :type _iter: Iterable[str]
    """
    index = 0
    for line in _iter:
        hookenv.relation_set(
            relation_id=rid,
            relation_settings={"{}_{}".format(prefix, index): line})
        index += 1
    hookenv.relation_set(relation_id=rid,
                         relation_settings={"{}".format(max_index): index})


@hooks.hook('cloud-compute-relation-departed')
def compute_departed():
    relation_data = hookenv.relation_get()
    ncc_utils.ssh_compute_remove(
        public_key=relation_data.get('ssh_public_key'))
    ncc_utils.clear_hostset_cache_for(relation_data.get('private-address'))


@hooks.hook('neutron-plugin-remote-relation-joined')
def publish_remote_metadata(rid=None):
    """Advertise the controller metadata endpoint and its existing secret.

    Use the canonical internal address so clustered deployments advertise the
    VIP. Remote chassis never supply credentials to the controller API.
    """
    rids = ([rid] if rid is not None else
            hookenv.relation_ids('neutron-plugin-remote'))
    if not rids:
        return
    metadata = ncc_utils.get_metadata_settings(CONFIGS)
    settings = {
        'private-address': metadata.get('nova-metadata-host'),
        'metadata-shared-secret': metadata.get('shared-metadata-secret'),
        'nova-metadata-protocol': metadata.get('nova-metadata-protocol'),
        'nova-metadata-port': metadata.get('nova-metadata-port'),
        'ca_cert': ncc_utils.get_ca_cert_b64() or None,
    }
    for relation in rids:
        hookenv.relation_set(relation_id=relation, relation_settings=settings)


@hooks.hook('neutron-network-service-relation-joined',
            'quantum-network-service-relation-joined')
def quantum_joined(rid=None, remote_restart=False):
    rel_settings = neutron_settings()

    # inform quantum about local keystone auth config
    ks_auth_config = _auth_config()
    rel_settings.update(ks_auth_config)

    # pass CA cert, if one exists.
    ca = ncc_utils.get_ca_cert_b64()
    if ca:
        rel_settings['ca_cert'] = ca

    # update relation setting if we're attempting to restart remote
    # services
    if remote_restart:
        rel_settings['restart_trigger'] = str(uuid.uuid4())

    rel_settings.update(ncc_utils.get_metadata_settings(CONFIGS))
    hookenv.relation_set(relation_id=rid, **rel_settings)


@hooks.hook('cluster-relation-joined')
def cluster_joined(relation_id=None):
    settings = {}

    for addr_type in ch_context.ADDRESS_TYPES:
        address = ch_network_ip.get_relation_ip(
            addr_type,
            cidr_network=hookenv.config('os-{}-network'.format(addr_type)))
        if address:
            settings['{}-address'.format(addr_type)] = address

    settings['private-address'] = ch_network_ip.get_relation_ip('cluster')

    hookenv.relation_set(relation_id=relation_id, relation_settings=settings)


@hooks.hook('cluster-relation-changed',
            'cluster-relation-departed',
            'leader-settings-changed')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map, stopstart=True)
def cluster_changed():
    CONFIGS.write_all()
    if hookenv.relation_ids('cluster'):
        ch_peerstorage.peer_echo(includes=['dbsync_state'])
        dbsync_state = ch_peerstorage.peer_retrieve('dbsync_state')
        if dbsync_state == 'complete':
            if not ch_utils.is_unit_paused_set():
                for svc in ncc_utils.services():
                    ch_host.service_resume(svc)
            else:
                hookenv.log('Unit is in paused state, not issuing '
                            'start/resume to all services')
        else:
            if not ch_utils.is_unit_paused_set():
                hookenv.log('Database sync not ready. Shutting down services')
                for svc in ncc_utils.services():
                    ch_host.service_pause(svc)
            else:
                hookenv.log(
                    'Database sync not ready. Would shut down services but '
                    'unit is in paused state, not issuing stop/pause to all '
                    'services')
    # The shared metadata secret is stored in the leader-db and if its changed
    # the gateway needs to know.
    publish_remote_metadata()
    for rid in hookenv.relation_ids('quantum-network-service'):
        quantum_joined(rid=rid, remote_restart=False)


@hooks.hook('ha-relation-joined')
def ha_joined(relation_id=None):
    ha_console_settings = {}
    ha_console_settings['delete_resources'] = [
        'vip_consoleauth',
        'res_nova_consoleauth'
    ]
    settings = ch_ha_utils.generate_ha_relation_data(
        'nova',
        extra_settings=ha_console_settings)

    hookenv.relation_set(relation_id=relation_id, **settings)


@hooks.hook('ha-relation-changed')
def ha_changed():
    clustered = hookenv.relation_get('clustered')
    if not clustered or clustered in [None, 'None', '']:
        hookenv.log('ha_changed: hacluster subordinate not fully clustered.')
        return

    CONFIGS.write(ncc_utils.NOVA_CONF)

    hookenv.log('Cluster configured, notifying other services and updating '
                'keystone endpoint configuration')
    for rid in hookenv.relation_ids('identity-service'):
        identity_joined(rid=rid)
    hookenv.log('Updating nova relations data')
    update_nova_relation()


@hooks.hook('shared-db-relation-broken')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
def db_departed():
    CONFIGS.write_all()
    update_cell_db_if_ready(skip_acl_check=True)
    for r_id in hookenv.relation_ids('cluster'):
        hookenv.relation_set(relation_id=r_id, dbsync_state='incomplete')
    if not ch_utils.is_unit_paused_set():
        for svc in ncc_utils.restart_map()[ncc_utils.NOVA_CONF]:
            ch_host.service_stop(svc)
    else:
        hookenv.log('Unit is in paused state, not issuing stop/pause to all '
                    'services')


@hooks.hook('amqp-relation-broken',
            'cinder-volume-service-relation-broken',
            'identity-service-relation-broken',
            'image-service-relation-broken',
            'nova-volume-service-relation-broken',
            'quantum-network-service-relation-broken')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
def relation_broken():
    CONFIGS.write_all()


def configure_https():
    '''
    Enables SSL API Apache config if appropriate and kicks identity-service
    with any required api updates.
    '''
    # need to write all to ensure changes to the entire request pipeline
    # propagate (c-api, haprxy, apache)
    CONFIGS.write_all()
    if 'https' in CONFIGS.complete_contexts():
        cmd = ['a2ensite', 'openstack_https_frontend']
        subprocess.check_call(cmd)
    else:
        cmd = ['a2dissite', 'openstack_https_frontend']
        subprocess.check_call(cmd)

    # TODO: improve this by checking if local CN certs are available
    # first then checking reload status (see LP #1433114).
    if not ch_utils.is_unit_paused_set():
        ch_host.service_reload('apache2', restart_on_failure=True)

    for rid in hookenv.relation_ids('identity-service'):
        identity_joined(rid=rid)


@hooks.hook()
def nova_vmware_relation_joined(rid=None):
    rel_settings = {'network_manager': ch_neutron.network_manager()}

    ks_auth = _auth_config()
    if ks_auth:
        rel_settings.update(ks_auth)
        rel_settings.update(neutron_settings())

    hookenv.relation_set(relation_id=rid, **rel_settings)


@hooks.hook('nova-vmware-relation-changed')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def nova_vmware_relation_changed():
    CONFIGS.write('/etc/nova/nova.conf')


@hooks.hook('upgrade-charm')
@ch_harden.harden()
def upgrade_charm():
    ch_fetch.apt_install(
        ch_fetch.filter_installed_packages(
            ncc_utils.determine_packages()), fatal=True)
    packages_removed = ncc_utils.remove_old_packages()
    if packages_removed:
        hookenv.log("Package purge detected, restarting services", "INFO")
        for s in ncc_utils.services():
            ch_host.service_restart(s)

    # For users already using bionic-rocky which are upgrading their
    # charm only we need ensure to not end-up with the old
    # 'wsgi-openstack-api' and the new 'wsgi-placement-api' apache
    # configurations installed at the same time.
    ncc_utils.stop_deprecated_services()
    ncc_utils.disable_package_apache_site(service_reload=True)
    for r_id in hookenv.relation_ids('amqp'):
        amqp_joined(relation_id=r_id)
    for r_id in hookenv.relation_ids('identity-service'):
        identity_joined(rid=r_id)

    r_ids = hookenv.relation_ids('cloud-compute')
    # NOTE(ganso): we update ssh data for all units first
    for r_id in r_ids:
        for unit in hookenv.related_units(r_id):
            update_ssh_key(rid=r_id, unit=unit)

    for r_id in r_ids:
        set_region_on_relation_from_config(r_id)
        set_cross_az_attach_on_relation_from_config(r_id)
        for unit in hookenv.related_units(r_id):
            update_compute_units_with_ssh_key_change(rid=r_id, unit=unit)
    for r_id in hookenv.relation_ids('shared-db'):
        db_joined(relation_id=r_id)

    add_hosts_to_cell_when_ready()

    leader_init_db_if_ready_allowed_units()

    publish_remote_metadata()
    update_nrpe_config()
    # call the policy overrides handler which will install any policy overrides
    policyd.maybe_do_policyd_overrides(
        ch_utils.os_release('nova-common'), 'nova')


@hooks.hook('neutron-api-relation-joined')
def neutron_api_relation_joined(rid=None, remote_restart=False):
    for id_rid in hookenv.relation_ids('identity-service'):
        identity_joined(rid=id_rid)
    rel_settings = {
        'nova_url': ch_ip.canonical_url(CONFIGS, ch_ip.INTERNAL) + ":8774/v2"
    }
    if remote_restart:
        rel_settings['restart_trigger'] = str(uuid.uuid4())
    hookenv.relation_set(relation_id=rid, **rel_settings)


@hooks.hook('neutron-api-relation-changed')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def neutron_api_relation_changed():
    CONFIGS.write(ncc_utils.NOVA_CONF)
    update_nova_relation()


@hooks.hook('neutron-api-relation-broken')
@ncc_utils.service_guard(ncc_utils.guard_map, resolve_CONFIGS,
                         active=deferred_config('service-guard'))
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def neutron_api_relation_broken():
    CONFIGS.write_all()
    update_nova_relation()


@hooks.hook('nrpe-external-master-relation-joined',
            'nrpe-external-master-relation-changed')
def update_nrpe_config():
    # python-dbus is used by check_upstart_job
    ch_fetch.apt_install('python-dbus')
    hostname = nrpe.get_nagios_hostname()
    current_unit = nrpe.get_nagios_unit_name()
    nrpe_setup = nrpe.NRPE(hostname=hostname)
    nrpe.copy_nrpe_checks()
    nrpe.add_init_service_checks(nrpe_setup,
                                 ncc_utils.services(),
                                 current_unit)
    nrpe.add_haproxy_checks(nrpe_setup, current_unit)
    if not ncc_utils.is_consoleauth_enabled():
        nrpe_setup.remove_check(shortname='nova-consoleauth')
    nrpe_setup.write()


@hooks.hook('memcache-relation-joined')
def memcached_joined():
    """When memcache relation joins we want to set our private address as the
    spaces address rather than leaving it as the unit address.  This is to
    support network spaces in the memcached charm.
    """
    hookenv.relation_set(
        relation_id=None,
        relation_settings={
            'private-address': ch_network_ip.get_relation_ip('memcache')
        })
    memcached_common()


@hooks.hook('memcache-relation-departed',
            'memcache-relation-changed',
            'memcache-relation-broken')
def memcached_other_hooks():
    memcached_common()


@ch_utils.pausable_restart_on_change(ncc_utils.restart_map)
def memcached_common():
    CONFIGS.write(ncc_utils.NOVA_CONF)


@hooks.hook('zeromq-configuration-relation-changed')
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map, stopstart=True)
def zeromq_configuration_relation_changed():
    CONFIGS.write(ncc_utils.NOVA_CONF)


@hooks.hook('certificates-relation-joined')
def certs_joined(relation_id=None):
    hookenv.relation_set(
        relation_id=relation_id,
        relation_settings=cert_utils.get_certificate_request())


@hooks.hook('certificates-relation-changed')
@ch_utils.pausable_restart_on_change(ncc_utils.restart_map, stopstart=True)
def certs_changed(relation_id=None, unit=None):
    cert_utils.process_certificates('nova', relation_id, unit, group='nova')
    configure_https()
    publish_remote_metadata()
    for rid in hookenv.relation_ids('cloud-compute'):
        compute_joined(rid=rid, remote_restart=False)
    for rid in hookenv.relation_ids('quantum-network-service'):
        quantum_joined(rid=rid, remote_restart=False)


@hooks.hook('amqp-cell-relation-joined')
def amqp_cell_joined(relation_id=None):
    hookenv.relation_set(relation_id=relation_id,
                         username='nova', vhost='nova')


@hooks.hook('shared-db-cell-relation-joined')
def shared_db_cell_joined(relation_id=None):
    access_network = None
    for unit in hookenv.related_units(relid=relation_id):
        access_network = hookenv.relation_get(rid=relation_id, unit=unit,
                                              attribute='access-network')
        if access_network:
            break
        host = ch_network_ip.get_relation_ip('shared-db',
                                             cidr_network=access_network)
    cell_db = {
        'nova_database': 'nova',
        'nova_username': hookenv.config('database-user'),
        'nova_hostname': host}
    hookenv.relation_set(relation_id=relation_id, **cell_db)


@hooks.hook('nova-cell-api-relation-joined')
def nova_cell_api_relation_joined(rid=None, remote_restart=False):
    rel_settings = get_compute_config(remote_restart=remote_restart)
    if ch_neutron.network_manager() == 'neutron':
        rel_settings.update(neutron_settings())
    hookenv.relation_set(relation_id=rid, **rel_settings)


@hooks.hook('shared-db-cell-relation-changed')
def shared_db_cell_changed(relation_id=None):
    update_child_cell_records()


@hooks.hook('amqp-cell-relation-changed')
def amqp_cell_changed(relation_id=None):
    update_child_cell_records()


@hooks.hook('nova-cell-api-relation-changed')
def nova_cell_api_relation_changed(rid=None, unit=None):
    data = hookenv.relation_get(rid=rid, unit=unit)
    ch_neutron.log("Data: {}".format(data), level=hookenv.DEBUG)
    if not data.get('cell-name'):
        return
    cell_updated = ncc_utils.update_child_cell(
        name=data['cell-name'],
        db_service=data['db-service'],
        amqp_service=data['amqp-service'])
    if cell_updated:
        hookenv.log(
            "Cell registration data changed, triggering a remote restart",
            level=hookenv.DEBUG)
        hookenv.relation_set(
            relation_id=rid,
            restart_trigger=str(uuid.uuid4()))


@hooks.hook('placement-relation-joined')
def placement_relation_joined(rid=None, unit=None):
    # For Stein->Train upgrades, operators must pause nova-cloud-controller
    # while placement charm is added.
    ncc_utils.disable_deprecated_nova_placement_apache_site()
    hookenv.relation_set(nova_placement_disabled=True, relation_id=rid)


@hooks.hook('placement-relation-changed')
def placement_relation_changed(rid=None, unit=None):
    data = hookenv.relation_get(rid=rid, unit=unit)
    if not data.get('placement_enabled'):
        return
    CONFIGS.write_all()
    # kick identity_joined() to publish endpoints without nova placement
    for rid in hookenv.relation_ids('identity-service'):
        identity_joined(rid)
    # kick compute_joined() to restart services on nova compute
    for rid in hookenv.relation_ids('cloud-compute'):
        compute_joined(rid=rid, remote_restart=True)
    # For Stein->Train upgrades, operators can resume nova-cloud-controller
    # once the new placement endpoints are published.
    for s in ncc_utils.services():
        ch_host.service_restart(s)


@hooks.hook('dashboard-relation-joined',
            'dashboard-relation-changed')
def dashboard_relation_changed():
    """
    Gather information from the related openstack-dashboard units
    """
    CONFIGS.write_all()


@hooks.hook('update-status')
@ch_harden.harden()
def update_status():
    hookenv.log('Updating status.')


@hooks.hook('pre-series-upgrade')
def pre_series_upgrade():
    hookenv.log("Running prepare series upgrade hook", "INFO")
    ch_utils.series_upgrade_prepare(ncc_utils.pause_unit_helper, CONFIGS)


@hooks.hook('post-series-upgrade')
def post_series_upgrade():
    hookenv.log("Running complete series upgrade hook", "INFO")
    ch_utils.series_upgrade_complete(ncc_utils.resume_unit_helper, CONFIGS)


def main():
    try:
        hooks.execute(sys.argv)
    except hookenv.UnregisteredHookError as e:
        hookenv.log('Unknown hook {} - skipping.'.format(e))
    ncc_utils.assess_status(CONFIGS)


if __name__ == '__main__':
    resolve_CONFIGS()
    main()
