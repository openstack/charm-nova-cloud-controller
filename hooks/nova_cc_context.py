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

import json
import os

import base64

import charmhelpers.contrib.hahelpers.cluster as ch_cluster
import charmhelpers.contrib.network.ip as ch_network_ip
import charmhelpers.contrib.openstack.context as ch_context
import charmhelpers.contrib.openstack.ip as ch_ip
import charmhelpers.contrib.openstack.neutron as ch_neutron
import charmhelpers.contrib.openstack.utils as ch_utils
import charmhelpers.core.hookenv as hookenv

import hooks.nova_cc_common as common

APACHE_24_CONF = '/etc/apache2/sites-available/openstack_https_frontend.conf'
APACHE_24_CONF_ENABLED = ('/etc/apache2/sites-enabled/'
                          'openstack_https_frontend.conf')


def context_complete(ctxt):
    _missing = []
    for k, v in ctxt.items():
        if v is None or v == '':
            _missing.append(k)
    if _missing:
        hookenv.log('Missing required data: %s' % ' '.join(_missing),
                    level='INFO')
        return False
    return True


class ApacheSSLContext(ch_context.ApacheSSLContext):

    interfaces = ['https']
    external_ports = []
    service_namespace = 'nova'

    # NOTE(fnordahl): The novncproxy service runs as user ``nova`` throughout
    # its lifespan, and it has no load certificates before dropping privileges
    # mechanism.
    #
    # Set file permissions on certificate files to support this. LP: #1819140
    group = 'nova'

    def __init__(self, _external_ports_maybe_callable):
        self._external_ports_maybe_callable = _external_ports_maybe_callable
        self.external_ports = None
        super(ApacheSSLContext, self).__init__()

    def __call__(self):
        if self.external_ports is None:
            if callable(self._external_ports_maybe_callable):
                self.external_ports = self._external_ports_maybe_callable()
            else:
                self.external_ports = self._external_ports_maybe_callable
        return super(ApacheSSLContext, self).__call__()


class NovaCellV2Context(ch_context.OSContextGenerator):

    interfaces = ['nova-cell-api']

    def __call__(self):
        ctxt = {}
        required_keys = ['cell-name', 'amqp-service', 'db-service']
        for rid in hookenv.relation_ids('nova-cell-api'):
            for unit in hookenv.related_units(rid):
                data = hookenv.relation_get(rid=rid, unit=unit)
                if set(required_keys).issubset(data.keys()):
                    ctxt[data['cell-name']] = {
                        'amqp_service': data['amqp-service'],
                        'db_service': data['db-service']}
        return ctxt


class NovaCellV2SharedDBContext(ch_context.OSContextGenerator):
    interfaces = ['shared-db']

    def __call__(self):
        hookenv.log('Generating template context for cell v2 share-db')
        ctxt = {}
        for rid in hookenv.relation_ids('shared-db'):
            for unit in hookenv.related_units(rid):
                rdata = hookenv.relation_get(rid=rid, unit=unit)
                ctxt = {
                    'novaapi_password': rdata.get('novaapi_password'),
                    'novacell0_password': rdata.get('novacell0_password'),
                    'nova_password': rdata.get('nova_password'),
                }
                if ch_context.context_complete(ctxt):
                    return ctxt
        return {}


class CloudComputeContext(ch_context.OSContextGenerator):
    "Dummy context used by service status to check relation exists"
    interfaces = ['nova-compute']

    def __call__(self):
        ctxt = {}
        rids = [rid for rid in hookenv.relation_ids('cloud-compute')]
        if rids:
            ctxt['rids'] = rids
        return ctxt


class PlacementContext(ch_context.OSContextGenerator):
    "Dummy context used by service status to check relation exists"
    interfaces = ['placement']

    def __call__(self):
        ctxt = {}
        rids = [rid for rid in hookenv.relation_ids('placement')]
        if rids:
            ctxt['rids'] = rids
        return ctxt


class NeutronAPIContext(ch_context.OSContextGenerator):
    interfaces = ['neutron-api']

    def __call__(self):
        hookenv.log('Generating template context from neutron api relation')
        ctxt = {}
        for rid in hookenv.relation_ids('neutron-api'):
            for unit in hookenv.related_units(rid):
                rdata = hookenv.relation_get(rid=rid, unit=unit)
                ctxt = {
                    'neutron_url': rdata.get('neutron-url'),
                    'neutron_plugin': rdata.get('neutron-plugin'),
                    'neutron_security_groups':
                    rdata.get('neutron-security-groups'),
                    'network_manager': 'neutron',
                }
                if (rdata.get('enable-sriov', '').lower() == 'true' or
                        rdata.get('enable-hardware-offload',
                                  '').lower() == 'true'):
                    ctxt['additional_neutron_filters'] = 'PciPassthroughFilter'
                # LP Bug#1805645
                if rdata.get('dns-domain', ''):
                    ctxt['dns_domain'] = rdata.get('dns-domain')
                if context_complete(ctxt):
                    return ctxt
        return {}


class VolumeServiceContext(ch_context.OSContextGenerator):
    interfaces = ['cinder-volume-service']

    def __call__(self):
        ctxt = {}
        if hookenv.relation_ids('cinder-volume-service'):
            ctxt['volume_service'] = 'cinder'
            # kick all compute nodes to know they should use cinder now.
            for rid in hookenv.relation_ids('cloud-compute'):
                hookenv.relation_set(relation_id=rid, volume_service='cinder')
        return ctxt


class HAProxyContext(ch_context.HAProxyContext):
    interfaces = ['ceph']

    def __call__(self):
        '''
        Extends the main charmhelpers HAProxyContext with a port mapping
        specific to this charm.
        Also used to extend nova.conf context with correct api_listening_ports
        '''
        ctxt = super(HAProxyContext, self).__call__()

        os_rel = ch_utils.os_release('nova-common')
        cmp_os_rel = ch_utils.CompareOpenStackReleases(os_rel)
        # determine which port api processes should bind to, depending
        # on existence of haproxy + apache frontends
        compute_api = ch_cluster.determine_api_port(
            common.api_port('nova-api-os-compute'), singlenode_mode=True)
        ec2_api = ch_cluster.determine_api_port(
            common.api_port('nova-api-ec2'), singlenode_mode=True)
        s3_api = ch_cluster.determine_api_port(
            common.api_port('nova-objectstore'), singlenode_mode=True)
        placement_api = ch_cluster.determine_api_port(
            common.api_port('nova-placement-api'), singlenode_mode=True)
        metadata_api = ch_cluster.determine_api_port(
            common.api_port('nova-api-metadata'), singlenode_mode=True)
        # Apache ports
        a_compute_api = ch_cluster.determine_apache_port(
            common.api_port('nova-api-os-compute'), singlenode_mode=True)
        a_ec2_api = ch_cluster.determine_apache_port(
            common.api_port('nova-api-ec2'), singlenode_mode=True)
        a_s3_api = ch_cluster.determine_apache_port(
            common.api_port('nova-objectstore'), singlenode_mode=True)
        a_placement_api = ch_cluster.determine_apache_port(
            common.api_port('nova-placement-api'), singlenode_mode=True)
        a_metadata_api = ch_cluster.determine_apache_port(
            common.api_port('nova-api-metadata'), singlenode_mode=True)
        # to be set in nova.conf accordingly.
        listen_ports = {
            'osapi_compute_listen_port': compute_api,
            'ec2_listen_port': ec2_api,
            's3_listen_port': s3_api,
            'placement_listen_port': placement_api,
            'metadata_listen_port': metadata_api,
        }

        port_mapping = {
            'nova-api-os-compute': [
                common.api_port('nova-api-os-compute'), a_compute_api],
            'nova-api-ec2': [
                common.api_port('nova-api-ec2'), a_ec2_api],
            'nova-objectstore': [
                common.api_port('nova-objectstore'), a_s3_api],
            'nova-placement-api': [
                common.api_port('nova-placement-api'), a_placement_api],
            'nova-api-metadata': [
                common.api_port('nova-api-metadata'), a_metadata_api],
        }

        if cmp_os_rel >= 'kilo':
            del listen_ports['ec2_listen_port']
            del listen_ports['s3_listen_port']
            del port_mapping['nova-api-ec2']
            del port_mapping['nova-objectstore']

        rids = hookenv.relation_ids('placement')
        if (rids or
                cmp_os_rel < 'ocata' or
                cmp_os_rel > 'stein'):
            del listen_ports['placement_listen_port']
            del port_mapping['nova-placement-api']

        healthcheck = [{
            'option': 'httpchk GET /',
            'http-check': 'expect status 200',
        }]

        backend_options = {
            'nova-api-os-compute': healthcheck,
            'nova-api-metadata': healthcheck,
        }

        # for haproxy.conf
        ctxt['service_ports'] = port_mapping
        # for nova.conf
        ctxt['listen_ports'] = listen_ports
        ctxt['backend_options'] = backend_options
        ctxt['https'] = ch_cluster.https()
        return ctxt


class PlacementAPIHAProxyContext(HAProxyContext):
    """Context for the nova placement api service."""

    def __call__(self):
        ctxt = super(PlacementAPIHAProxyContext, self).__call__()
        ctxt['port'] = ctxt['listen_ports']['placement_listen_port']
        return ctxt


class ComputeAPIHAProxyContext(HAProxyContext):
    """Context for the nova os compute api service."""

    def __call__(self):
        ctxt = super(ComputeAPIHAProxyContext, self).__call__()
        ctxt['port'] = ctxt['listen_ports']['osapi_compute_listen_port']
        return ctxt


class MetaDataHAProxyContext(HAProxyContext):
    """Context for the nova metadata service."""

    def __call__(self):
        ctxt = super(MetaDataHAProxyContext, self).__call__()
        ctxt['port'] = ctxt['listen_ports']['metadata_listen_port']
        return ctxt


def canonical_url():
    """Returns the correct HTTP URL to this host given the state of HTTPS
    configuration and hacluster.
    """
    scheme = 'http'
    if ch_cluster.https():
        scheme = 'https'

    addr = ch_ip.resolve_address(ch_ip.INTERNAL)
    return '%s://%s' % (scheme, ch_network_ip.format_ipv6_addr(addr) or addr)


class CinderConfigContext(ch_context.OSContextGenerator):
    def __call__(self):
        return {
            'cross_az_attach': hookenv.config('cross-az-attach')
        }


class NeutronCCContext(ch_context.NeutronContext):
    interfaces = ['quantum-network-service', 'neutron-network-service']

    @property
    def network_manager(self):
        return ch_neutron.network_manager()

    def _ensure_packages(self):
        # Only compute nodes need to ensure packages here, to install
        # required agents.
        return

    def __call__(self):
        ctxt = super(NeutronCCContext, self).__call__()
        ctxt['external_network'] = hookenv.config('neutron-external-network')
        ctxt['nova_url'] = "{}:8774/v2".format(canonical_url())
        return ctxt


class IdentityServiceContext(ch_context.IdentityServiceContext):

    def __call__(self):
        ctxt = super(IdentityServiceContext, self).__call__()
        if not ctxt:
            return

        # the ec2 api needs to know the location of the keystone ec2
        # tokens endpoint, set in nova.conf
        ec2_tokens = '%s://%s:%s/v2.0/ec2tokens' % (
            ctxt['service_protocol'] or 'http',
            ctxt['service_host'],
            ctxt['service_port']
        )
        ctxt['keystone_ec2_url'] = ec2_tokens
        ctxt['region'] = hookenv.config('region')

        return ctxt


_base_enabled_filters = [
    "RetryFilter",
    "AvailabilityZoneFilter",
    "CoreFilter",
    "RamFilter",
    "DiskFilter",
    "ComputeFilter",
    "ComputeCapabilitiesFilter",
    "ImagePropertiesFilter",
    "ServerGroupAntiAffinityFilter",
    "ServerGroupAffinityFilter",
    "DifferentHostFilter",
    "SameHostFilter",
]

# NOTE: Core,Ram,Disk filters obsolete due
#       placement API functionality
_pike_enabled_filters = [
    "RetryFilter",
    "AvailabilityZoneFilter",
    "ComputeFilter",
    "ComputeCapabilitiesFilter",
    "ImagePropertiesFilter",
    "ServerGroupAntiAffinityFilter",
    "ServerGroupAffinityFilter",
    "DifferentHostFilter",
    "SameHostFilter",
]
_victoria_enabled_filters = [
    "AvailabilityZoneFilter",
    "ComputeFilter",
    "ComputeCapabilitiesFilter",
    "ImagePropertiesFilter",
    "ServerGroupAntiAffinityFilter",
    "ServerGroupAffinityFilter",
    "DifferentHostFilter",
    "SameHostFilter",
]
_bobcat_enabled_filters = [
    "ComputeFilter",
    "ComputeCapabilitiesFilter",
    "ImagePropertiesFilter",
    "ServerGroupAntiAffinityFilter",
    "ServerGroupAffinityFilter",
    "DifferentHostFilter",
    "SameHostFilter",
]


def default_enabled_filters():
    """
    Determine the list of default filters for scheduler use

    :returns: list of filters to use
    :rtype: list of str
    """
    os_rel = ch_utils.os_release('nova-common')
    cmp_os_rel = ch_utils.CompareOpenStackReleases(os_rel)
    if cmp_os_rel >= 'bobcat':
        return _bobcat_enabled_filters
    if cmp_os_rel >= 'victoria':
        return _victoria_enabled_filters
    if cmp_os_rel >= 'pike':
        return _pike_enabled_filters
    return _base_enabled_filters


class NovaConfigContext(ch_context.WorkerConfigContext):
    def __call__(self):
        ctxt = super(NovaConfigContext, self).__call__()
        ctxt['scheduler_default_filters'] = (
            hookenv.config('scheduler-default-filters') or
            ','.join(default_enabled_filters()))
        if hookenv.config('pci-alias'):
            aliases = json.loads(hookenv.config('pci-alias'))
            if isinstance(aliases, list):
                ctxt['pci_aliases'] = [json.dumps(x, sort_keys=True)
                                       for x in aliases]
            else:
                ctxt['pci_alias'] = json.dumps(aliases, sort_keys=True)

        cmp_os_release = ch_utils.CompareOpenStackReleases(
            ch_utils.os_release('nova-common'))
        # Require explicit operator opt-in after compute inventories exist.
        if (cmp_os_release >= 'antelope' and
                hookenv.config('pci-in-placement')):
            ctxt['pci_in_placement'] = True

        ctxt['disk_allocation_ratio'] = hookenv.config('disk-allocation-ratio')
        ctxt['cpu_allocation_ratio'] = hookenv.config('cpu-allocation-ratio')
        ctxt['ram_allocation_ratio'] = hookenv.config('ram-allocation-ratio')

        ctxt['allow_resize_to_same_host'] = hookenv.config(
            'allow-resize-to-same-host')

        for rid in hookenv.relation_ids('cloud-compute'):
            rdata = {
                'disk_allocation_ratio': ctxt['disk_allocation_ratio'],
                'cpu_allocation_ratio': ctxt['cpu_allocation_ratio'],
                'ram_allocation_ratio': ctxt['ram_allocation_ratio'],
                'allow_resize_to_same_host': ctxt['allow_resize_to_same_host'],
            }
            hookenv.relation_set(relation_settings=rdata, relation_id=rid)

        ctxt['enable_new_services'] = hookenv.config('enable-new-services')
        addr = ch_ip.resolve_address(ch_ip.INTERNAL)
        ctxt['host_ip'] = ch_network_ip.format_ipv6_addr(addr) or addr
        ctxt['quota_instances'] = hookenv.config('quota-instances')
        ctxt['quota_cores'] = hookenv.config('quota-cores')
        ctxt['quota_ram'] = hookenv.config('quota-ram')
        ctxt['quota_metadata_items'] = hookenv.config('quota-metadata-items')
        ctxt['quota_injected_files'] = hookenv.config('quota-injected-files')
        ctxt['quota_injected_file_content_bytes'] = hookenv.config(
            'quota-injected-file-size')
        ctxt['quota_injected_file_path_length'] = hookenv.config(
            'quota-injected-path-size')
        ctxt['quota_key_pairs'] = hookenv.config('quota-key-pairs')
        ctxt['quota_server_groups'] = hookenv.config('quota-server-groups')
        ctxt['quota_server_group_members'] = hookenv.config(
            'quota-server-group-members')
        ctxt['quota_count_usage_from_placement'] = hookenv.config(
            'quota-count-usage-from-placement')
        ctxt['console_access_protocol'] = hookenv.config(
            'console-access-protocol')
        ctxt['console_access_port'] = hookenv.config('console-access-port')
        ctxt['scheduler_host_subset_size'] = hookenv.config(
            'scheduler-host-subset-size')
        ctxt['scheduler_max_attempts'] = hookenv.config(
            'scheduler-max-attempts')
        ctxt['unique_server_names'] = hookenv.config('unique-server-names')
        ctxt['skip_hosts_with_build_failures'] = hookenv.config(
            'skip-hosts-with-build-failures')
        ctxt['limit_tenants_to_placement_aggregate'] = hookenv.config(
            'limit-tenants-to-placement-aggregate')
        ctxt['placement_aggregate_required_for_tenants'] = hookenv.config(
            'placement-aggregate-required-for-tenants')
        ctxt['enable_isolated_aggregate_filtering'] = hookenv.config(
            'enable-isolated-aggregate-filtering')
        ctxt['max_local_block_devices'] = hookenv.config(
            'max-local-block-devices')

        enable_notify = hookenv.config('enable-notify')
        notify_on_state_change = hookenv.config('notify-on-state-change')
        if enable_notify and notify_on_state_change:
            ctxt['enable_notify'] = True
            ctxt['notify_on_state_change'] = notify_on_state_change
        else:
            ctxt['enable_notify'] = False
        return ctxt


class NovaIPv6Context(ch_context.BindHostContext):
    def __call__(self):
        ctxt = super(NovaIPv6Context, self).__call__()
        ctxt['use_ipv6'] = hookenv.config('prefer-ipv6')
        return ctxt


class RemoteMemcacheContext(ch_context.OSContextGenerator):
    interfaces = ['memcache']

    def __call__(self):
        servers = []
        try:
            for rid in hookenv.relation_ids(self.interfaces[0]):
                for rel in hookenv.relations_for_id(rid):
                    priv_addr = rel['private-address']
                    # Format it as IPv6 address if needed
                    priv_addr = (ch_network_ip.format_ipv6_addr(priv_addr) or
                                 priv_addr)
                    servers.append("%s:%s" % (priv_addr, rel['port']))
        except Exception as ex:
            hookenv.log("Could not get memcache servers: %s" % (ex),
                        level='WARNING')
            servers = []

        if servers:
            return {
                'memcached_servers': ','.join(servers)
            }
        return {}


class InstanceConsoleContext(ch_context.OSContextGenerator):
    interfaces = []

    def __call__(self):
        ctxt = {}
        # Configure nova-novncproxy https if nova-api is using https.
        if ch_cluster.https():
            cn = ch_ip.resolve_address(endpoint_type=ch_ip.PUBLIC)
            if cn:
                cert_filename = 'cert_{}'.format(cn)
                key_filename = 'key_{}'.format(cn)
            else:
                cert_filename = 'cert'
                key_filename = 'key'

            ssl_dir = '/etc/apache2/ssl/nova'
            cert = os.path.join(ssl_dir, cert_filename)
            key = os.path.join(ssl_dir, key_filename)
            if os.path.exists(cert) and os.path.exists(key):
                ctxt['ssl_cert'] = cert
                ctxt['ssl_key'] = key

        return ctxt


class ConsoleSSLContext(ch_context.OSContextGenerator):
    interfaces = []

    def __call__(self):
        ctxt = {}

        if (hookenv.config('console-ssl-cert') and
                hookenv.config('console-ssl-key') and
                hookenv.config('console-access-protocol')):
            ssl_dir = '/etc/nova/ssl/'
            if not os.path.exists(ssl_dir):
                hookenv.log('Creating %s.' % ssl_dir, level=hookenv.DEBUG)
                os.mkdir(ssl_dir)

            cert_path = os.path.join(ssl_dir, 'nova_cert.pem')
            decode_ssl_cert = base64.b64decode(
                hookenv.config('console-ssl-cert'))

            key_path = os.path.join(ssl_dir, 'nova_key.pem')
            decode_ssl_key = base64.b64decode(
                hookenv.config('console-ssl-key'))

            with open(cert_path, 'wb') as fh:
                fh.write(decode_ssl_cert)
            with open(key_path, 'wb') as fh:
                fh.write(decode_ssl_key)

            ctxt['ssl_only'] = True
            ctxt['ssl_cert'] = cert_path
            ctxt['ssl_key'] = key_path

            if ch_cluster.is_clustered():
                ip_addr = ch_ip.resolve_address(endpoint_type=ch_ip.PUBLIC)
            else:
                ip_addr = hookenv.unit_get('private-address')

            ip_addr = ch_network_ip.format_ipv6_addr(ip_addr) or ip_addr

            _proto = hookenv.config('console-access-protocol')
            url = "https://%s:%s%s" % (
                ip_addr,
                common.console_attributes('proxy-port', proto=_proto),
                common.console_attributes('proxy-page', proto=_proto))

            if _proto == 'novnc':
                ctxt['novncproxy_base_url'] = url
            elif _proto == 'spice':
                ctxt['html5proxy_base_url'] = url

        return ctxt


class SerialConsoleContext(ch_context.OSContextGenerator):
    interfaces = []

    def __call__(self):
        ip_addr = ch_ip.resolve_address(endpoint_type=ch_ip.PUBLIC)
        ip_addr = ch_network_ip.format_ipv6_addr(ip_addr) or ip_addr

        if os.path.isfile(APACHE_24_CONF):
            protocol = 'wss'
        else:
            protocol = 'ws'

        ctxt = {
            'enable_serial_console':
                str(hookenv.config('enable-serial-console')).lower(),
            'serial_console_base_url':
                '{protocol}://{ip_addr}:6083/'.format(ip_addr=ip_addr,
                                                      protocol=protocol),
        }
        if hookenv.config('enable-serial-console'):
            for rel_id in hookenv.relation_ids('dashboard'):
                ctxt['console_allowed_origins'] = []
                rel_units = hookenv.related_units(rel_id)
                if not rel_units:
                    continue

                os_public_hostname = hookenv.relation_get('os-public-hostname',
                                                          rid=rel_id,
                                                          app=rel_units[0])
                if os_public_hostname:
                    ctxt['console_allowed_origins'].append(os_public_hostname)

                vip = hookenv.relation_get('vip',
                                           rid=rel_id,
                                           app=rel_units[0])
                if vip:
                    ip_addresses = [ip.strip() for ip in vip.split(' ')]
                    ctxt['console_allowed_origins'] += ip_addresses

                for unit in rel_units:
                    ingress_address = hookenv.ingress_address(rel_id, unit)
                    if ingress_address:
                        ctxt['console_allowed_origins'].append(ingress_address)

        return ctxt


class APIRateLimitingContext(ch_context.OSContextGenerator):
    def __call__(self):
        ctxt = {}
        rate_rules = hookenv.config('api-rate-limit-rules')
        if rate_rules:
            ctxt['api_rate_limit_rules'] = rate_rules
        return ctxt


class NovaAPISharedDBContext(ch_context.SharedDBContext):
    '''
    Wrapper context to support multiple database connections being
    represented to a single config file

    ctxt values are namespaced with a nova_api_ prefix
    '''
    def __call__(self):
        ctxt = super(NovaAPISharedDBContext, self).__call__()
        if ctxt is not None:
            prefix = 'nova_api_{}'
            ctxt = {prefix.format(k): v for k, v in ctxt.items()}
        return ctxt


class NovaMetadataContext(ch_context.NovaVendorMetadataContext):
    """Context used for configuring the nova metadata service."""

    def __call__(self):
        vdata_values = super(NovaMetadataContext, self).__call__()

        release = ch_utils.os_release('nova-common')
        cmp_os_release = ch_utils.CompareOpenStackReleases(release)

        ctxt = {}

        if cmp_os_release >= 'rocky':
            ctxt.update(vdata_values)

            ctxt['metadata_proxy_shared_secret'] = hookenv.leader_get(
                'shared-metadata-secret')
            ctxt['enable_metadata'] = True
        else:
            hookenv.log("Vendor metadata has been configured but is not "
                        "effective in nova-cloud-controller because release "
                        "{} is prior to Rocky.".format(release),
                        level=hookenv.DEBUG)
            ctxt['enable_metadata'] = False

        # NOTE(ganso): always propagate config value for nova-compute since
        # we need to apply it there for all releases, and we cannot determine
        # whether nova-compute is really the one serving the vendor metadata
        for rid in hookenv.relation_ids('cloud-compute'):
            hookenv.relation_set(relation_id=rid,
                                 vendor_data=json.dumps(vdata_values))

        return ctxt


class NovaMetadataJSONContext(ch_context.NovaVendorMetadataJSONContext):

    def __call__(self):
        vdata_values = super(NovaMetadataJSONContext, self).__call__()

        # NOTE(ganso): always propagate config value for nova-compute since
        # we need to apply it there for releases prior to rocky
        for rid in hookenv.relation_ids('cloud-compute'):
            hookenv.relation_set(relation_id=rid,
                                 vendor_json=vdata_values['vendor_data_json'])

        release = ch_utils.os_release('nova-common')
        cmp_os_release = ch_utils.CompareOpenStackReleases(release)

        if cmp_os_release >= 'rocky':
            return vdata_values
        else:
            hookenv.log("Vendor metadata has been configured but is not "
                        "effective in nova-cloud-controller because release "
                        "{} is prior to Rocky.".format(release),
                        level=hookenv.DEBUG)
            return {'vendor_data_json': '{}'}
