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
from unittest import mock

import hooks.nova_cc_context as context

from charmhelpers.contrib.openstack import neutron
from charmhelpers.contrib.openstack import utils
import charmhelpers.core.unitdata

from unit_tests.test_utils import CharmTestCase

TO_PATCH = [
    'charmhelpers.contrib.hahelpers.cluster.https',
    'charmhelpers.contrib.openstack.utils.os_release',
    'charmhelpers.core.hookenv.config',
    'charmhelpers.core.hookenv.leader_get',
    'charmhelpers.core.hookenv.log',
    'charmhelpers.core.hookenv.related_units',
    'charmhelpers.core.hookenv.relation_get',
    'charmhelpers.core.hookenv.relation_set',
    'charmhelpers.core.hookenv.relation_ids',
    'charmhelpers.core.hookenv.relations_for_id',
]


def fake_log(msg, level=None):
    level = level or 'INFO'
    print('[juju test log (%s)] %s' % (level, msg))


class NovaComputeContextTests(CharmTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        charmhelpers.core.unitdata._KV = (
            charmhelpers.core.unitdata.Storage(':memory:'))

    def setUp(self):
        super(NovaComputeContextTests, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.log.side_effect = fake_log
        self.os_release.return_value = 'icehouse'

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address',
                lambda *args, **kwargs: None)
    @mock.patch.object(utils, 'os_release')
    @mock.patch('charmhelpers.contrib.network.ip.log')
    def test_remote_memcache_context_without_memcache(self, os_release, log_):
        self.relation_ids.return_value = 'cache:0'
        self.related_units.return_value = 'memcached/0'
        remote_memcache = context.RemoteMemcacheContext()
        os_release.return_value = 'icehouse'
        self.assertEqual({}, remote_memcache())

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address',
                lambda *args, **kwargs: None)
    @mock.patch.object(utils, 'os_release')
    @mock.patch('charmhelpers.contrib.network.ip.log')
    def test_remote_memcache_context_with_memcache(self, os_release, log_):
        self.check_remote_memcache_context_with_memcache(os_release,
                                                         '127.0.1.1',
                                                         '127.0.1.1')

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address',
                lambda *args, **kwargs: None)
    @mock.patch.object(utils, 'os_release')
    @mock.patch('charmhelpers.contrib.network.ip.log')
    def test_remote_memcache_context_with_memcache_ipv6(self, os_release,
                                                        log_):
        self.check_remote_memcache_context_with_memcache(os_release, '::1',
                                                         '[::1]')

    def check_remote_memcache_context_with_memcache(self, os_release, ip,
                                                    formated_ip):
        memcached_servers = [{'private-address': formated_ip,
                              'port': '11211'}]
        self.relation_ids.return_value = ['cache:0']
        self.relations_for_id.return_value = memcached_servers
        self.related_units.return_value = 'memcached/0'
        remote_memcache = context.RemoteMemcacheContext()
        os_release.return_value = 'icehouse'
        self.maxDiff = None
        self.assertEqual({'memcached_servers': "%s:11211" % (formated_ip, )},
                         remote_memcache())

    @mock.patch('charmhelpers.contrib.openstack.ip.config')
    @mock.patch('charmhelpers.contrib.openstack.neutron.config')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    @mock.patch('charmhelpers.contrib.openstack.neutron.os_release')
    @mock.patch('charmhelpers.contrib.openstack.ip.is_clustered')
    def test_neutron_context_single_vip(
            self, mock_is_clustered, _os_release, mock_config,
            mock_config_neutron, mock_config_ip):
        self.https.return_value = False
        mock_is_clustered.return_value = True
        _config = {'vip': '10.0.0.1',
                   'os-internal-network': '10.0.0.1/24',
                   'os-admin-network': '10.0.1.0/24',
                   'os-public-network': '10.0.2.0/24',
                   'network-manager': 'FlatDHCPManager'}
        mock_config.side_effect = lambda key: _config.get(key)
        mock_config_neutron.side_effect = lambda key: _config.get(key)
        mock_config_ip.side_effect = lambda key: _config.get(key)

        ctxt = context.NeutronCCContext()()
        self.assertEqual(ctxt['nova_url'], 'http://10.0.0.1:8774/v2')
        self.assertFalse('neutron_url' in ctxt)

    @mock.patch('charmhelpers.contrib.openstack.ip.config')
    @mock.patch('charmhelpers.contrib.openstack.neutron.config')
    @mock.patch('charmhelpers.contrib.openstack.neutron.os_release')
    @mock.patch('charmhelpers.contrib.openstack.ip.is_clustered')
    def test_neutron_context_multi_vip(
            self, mock_is_clustered, _os_release, mock_config, mock_config_ip):
        self.https.return_value = False
        mock_is_clustered.return_value = True
        _config = {'vip': '10.0.0.1 10.0.1.1 10.0.2.1',
                   'os-internal-network': '10.0.1.0/24',
                   'os-admin-network': '10.0.0.0/24',
                   'os-public-network': '10.0.2.0/24',
                   'network-manager': 'FlatDHCPManager'}
        mock_config.side_effect = lambda key: _config.get(key)
        mock_config_ip.side_effect = lambda key: _config.get(key)
        ctxt = context.NeutronCCContext()()
        self.assertEqual(ctxt['nova_url'], 'http://10.0.1.1:8774/v2')
        self.assertFalse('neutron_url' in ctxt)

    @mock.patch('charmhelpers.contrib.openstack.context.is_ipv6_disabled')
    @mock.patch('charmhelpers.core.hookenv.relation_ids')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    @mock.patch('charmhelpers.contrib.openstack.context.get_relation_ip')
    @mock.patch('charmhelpers.contrib.openstack.context.mkdir')
    @mock.patch.object(neutron, 'network_manager')
    @mock.patch('charmhelpers.contrib.hahelpers.cluster.https')
    @mock.patch('charmhelpers.contrib.openstack.context.kv')
    @mock.patch('charmhelpers.contrib.openstack.context.'
                'get_address_in_network')
    @mock.patch('charmhelpers.contrib.openstack.context.'
                'get_netmask_for_address')
    @mock.patch('charmhelpers.contrib.openstack.context.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.get_ipv6_addr')
    @mock.patch('charmhelpers.contrib.openstack.context.relation_ids')
    def test_haproxy_context(self, mock_relation_ids, mock_get_ipv6_addr,
                             mock_local_unit, mock_get_netmask_for_address,
                             mock_get_address_in_network, mock_kv, mock_https,
                             mock_network_manager, mock_mkdir,
                             mock_get_relation_ip, mock_config, mock_rids,
                             mock_is_ipv6_disabled):
        self.os_release.return_value = 'ocata'
        mock_config.side_effect = self.test_config.get
        mock_https.return_value = False
        mock_network_manager.return_value = 'neutron'
        mock_rids.return_value = []
        mock_is_ipv6_disabled.return_value = True
        ctxt = context.HAProxyContext()()
        self.assertEqual(ctxt['service_ports']['nova-api-os-compute'],
                         [8774, 8764])
        self.assertTrue('nova-placement-api' in ctxt['service_ports'])
        self.assertTrue('nova-api-ec2' not in ctxt['service_ports'])
        self.assertTrue('nova-objectstore' not in ctxt['service_ports'])

        self.os_release.return_value = 'icehouse'
        ctxt = context.HAProxyContext()()
        self.assertTrue('nova-placement-api' not in ctxt['service_ports'])
        self.assertTrue('nova-api-ec2' in ctxt['service_ports'])
        self.assertTrue('nova-objectstore' in ctxt['service_ports'])

        self.os_release.return_value = 'kilo'
        ctxt = context.HAProxyContext()()
        self.assertTrue('nova-placement-api' not in ctxt['service_ports'])
        self.assertTrue('nova-api-ec2' not in ctxt['service_ports'])
        self.assertTrue('nova-objectstore' not in ctxt['service_ports'])

    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_console_ssl_disabled(self, mock_config):
        config = {'console-ssl-cert': 'LS0tLS1CRUdJTiBDRV',
                  'console-ssl-key': 'LS0tLS1CRUdJTiBQUk'}
        mock_config.side_effect = lambda key: config.get(key)

        ctxt = context.ConsoleSSLContext()()
        self.assertEqual(ctxt, {})

        config = {'console-ssl-cert': None,
                  'console-ssl-key': None}
        mock_config.side_effect = lambda key: config.get(key)

        ctxt = context.ConsoleSSLContext()()
        self.assertEqual(ctxt, {})

        config = {'console-access-protocol': 'novnc',
                  'console-ssl-cert': None,
                  'console-ssl-key': None}
        mock_config.side_effect = lambda key: config.get(key)

        ctxt = context.ConsoleSSLContext()()
        self.assertEqual(ctxt, {})

    @mock.patch('builtins.open')
    @mock.patch('os.path.exists')
    @mock.patch('charmhelpers.core.hookenv.unit_get')
    @mock.patch('charmhelpers.contrib.hahelpers.cluster.is_clustered')
    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('base64.b64decode')
    def test_noVNC_ssl_enabled(self, mock_b64decode,
                               mock_resolve_address,
                               mock_is_clustered, mock_unit_get,
                               mock_exists, mock_open):
        config = {'console-ssl-cert': 'LS0tLS1CRUdJTiBDRV',
                  'console-ssl-key': 'LS0tLS1CRUdJTiBQUk',
                  'console-access-protocol': 'novnc'}
        self.test_config.update(config)
        mock_exists.return_value = True
        mock_unit_get.return_value = '127.0.0.1'
        mock_is_clustered.return_value = True
        mock_resolve_address.return_value = '10.5.100.1'
        mock_b64decode.return_value = 'decode_success'

        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = mock.Mock()

        ctxt = context.ConsoleSSLContext()()
        self.assertTrue(ctxt['ssl_only'])
        self.assertEqual(ctxt['ssl_cert'], '/etc/nova/ssl/nova_cert.pem')
        self.assertEqual(ctxt['ssl_key'], '/etc/nova/ssl/nova_key.pem')
        self.assertEqual(ctxt['novncproxy_base_url'],
                         'https://10.5.100.1:6080/vnc_auto.html')

    @mock.patch('builtins.open')
    @mock.patch('os.path.exists')
    @mock.patch('charmhelpers.core.hookenv.unit_get')
    @mock.patch('charmhelpers.contrib.hahelpers.cluster.is_clustered')
    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('base64.b64decode')
    def test_noVNC_ssl_enabled_no_cluster(self, mock_b64decode,
                                          mock_resolve_address,
                                          mock_is_clustered, mock_unit_get,
                                          mock_exists, mock_open):
        config = {'console-ssl-cert': 'LS0tLS1CRUdJTiBDRV',
                  'console-ssl-key': 'LS0tLS1CRUdJTiBQUk',
                  'console-access-protocol': 'novnc'}
        self.test_config.update(config)
        mock_exists.return_value = True
        mock_unit_get.return_value = '10.5.0.1'
        mock_is_clustered.return_value = False
        mock_b64decode.return_value = 'decode_success'

        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = mock.Mock()

        ctxt = context.ConsoleSSLContext()()
        self.assertTrue(ctxt['ssl_only'])
        self.assertEqual(ctxt['ssl_cert'], '/etc/nova/ssl/nova_cert.pem')
        self.assertEqual(ctxt['ssl_key'], '/etc/nova/ssl/nova_key.pem')
        self.assertEqual(ctxt['novncproxy_base_url'],
                         'https://10.5.0.1:6080/vnc_auto.html')

    @mock.patch('builtins.open')
    @mock.patch('os.path.exists')
    @mock.patch('charmhelpers.core.hookenv.unit_get')
    @mock.patch('charmhelpers.contrib.hahelpers.cluster.is_clustered')
    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('base64.b64decode')
    def test_spice_html5_ssl_enabled(self, mock_b64decode,
                                     mock_resolve_address,
                                     mock_is_clustered, mock_unit_get,
                                     mock_exists, mock_open):
        config = {'console-ssl-cert': 'LS0tLS1CRUdJTiBDRV',
                  'console-ssl-key': 'LS0tLS1CRUdJTiBQUk',
                  'console-access-protocol': 'spice'}
        self.test_config.update(config)
        mock_exists.return_value = True
        mock_unit_get.return_value = '127.0.0.1'
        mock_is_clustered.return_value = True
        mock_resolve_address.return_value = '10.5.100.1'
        mock_b64decode.return_value = 'decode_success'

        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = mock.Mock()

        ctxt = context.ConsoleSSLContext()()
        self.assertTrue(ctxt['ssl_only'])
        self.assertEqual(ctxt['ssl_cert'], '/etc/nova/ssl/nova_cert.pem')
        self.assertEqual(ctxt['ssl_key'], '/etc/nova/ssl/nova_key.pem')
        self.assertEqual(ctxt['html5proxy_base_url'],
                         'https://10.5.100.1:6082/spice_auto.html')

    @mock.patch('builtins.open')
    @mock.patch('os.path.exists')
    @mock.patch('charmhelpers.core.hookenv.unit_get')
    @mock.patch('charmhelpers.contrib.hahelpers.cluster.is_clustered')
    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('base64.b64decode')
    def test_spice_html5_ssl_enabled_no_cluster(self, mock_b64decode,
                                                mock_resolve_address,
                                                mock_is_clustered,
                                                mock_unit_get,
                                                mock_exists,
                                                mock_open):
        config = {'console-ssl-cert': 'LS0tLS1CRUdJTiBDRV',
                  'console-ssl-key': 'LS0tLS1CRUdJTiBQUk',
                  'console-access-protocol': 'spice'}
        self.test_config.update(config)
        mock_exists.return_value = True
        mock_unit_get.return_value = '10.5.0.1'
        mock_is_clustered.return_value = False
        mock_b64decode.return_value = 'decode_success'

        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = mock.Mock()

        ctxt = context.ConsoleSSLContext()()
        self.assertTrue(ctxt['ssl_only'])
        self.assertEqual(ctxt['ssl_cert'], '/etc/nova/ssl/nova_cert.pem')
        self.assertEqual(ctxt['ssl_key'], '/etc/nova/ssl/nova_key.pem')
        self.assertEqual(ctxt['html5proxy_base_url'],
                         'https://10.5.0.1:6082/spice_auto.html')

    @mock.patch('charmhelpers.contrib.openstack.ip.config')
    @mock.patch('charmhelpers.contrib.openstack.ip.unit_get')
    @mock.patch('charmhelpers.contrib.hahelpers.cluster.relation_ids')
    @mock.patch('charmhelpers.core.hookenv.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_nova_config_context(self, mock_config, local_unit,
                                 mock_relation_ids, mock_unit_get,
                                 mock_config_ip):
        local_unit.return_value = 'nova-cloud-controller/0'
        mock_config.side_effect = self.test_config.get
        mock_config_ip.side_effect = self.test_config.get
        mock_unit_get.return_value = '127.0.0.1'
        self.test_config.set('scheduler-default-filters', 'TestFilter')
        self.test_config.set('scheduler-max-attempts', 10)
        self.test_config.set('unique-server-names', 'project')
        ctxt = context.NovaConfigContext()()
        self.assertEqual(ctxt['scheduler_default_filters'],
                         self.config('scheduler-default-filters'))
        self.assertEqual(ctxt['scheduler_max_attempts'],
                         self.config('scheduler-max-attempts'))
        self.assertEqual(ctxt['cpu_allocation_ratio'],
                         self.config('cpu-allocation-ratio'))
        self.assertEqual(ctxt['ram_allocation_ratio'],
                         self.config('ram-allocation-ratio'))
        self.assertEqual(ctxt['disk_allocation_ratio'],
                         self.config('disk-allocation-ratio'))
        self.assertEqual(ctxt['quota_instances'],
                         self.config('quota-instances'))
        self.assertEqual(ctxt['quota_instances'], None)
        self.assertEqual(ctxt['quota_cores'],
                         self.config('quota-cores'))
        self.assertEqual(ctxt['quota_cores'], None)
        self.assertEqual(ctxt['quota_ram'],
                         self.config('quota-ram'))
        self.assertEqual(ctxt['quota_ram'], None)
        self.assertEqual(ctxt['quota_metadata_items'],
                         self.config('quota-metadata-items'))
        self.assertEqual(ctxt['quota_metadata_items'], None)
        self.assertEqual(ctxt['quota_injected_files'],
                         self.config('quota-injected-files'))
        self.assertEqual(ctxt['quota_injected_files'], None)
        self.assertEqual(ctxt['quota_injected_file_content_bytes'],
                         self.config('quota-injected-file-size'))
        self.assertEqual(ctxt['quota_injected_file_content_bytes'], None)
        self.assertEqual(ctxt['quota_injected_file_path_length'],
                         self.config('quota-injected-path-size'))
        self.assertEqual(ctxt['quota_injected_file_path_length'], None)
        self.assertEqual(ctxt['quota_key_pairs'],
                         self.config('quota-key-pairs'))
        self.assertEqual(ctxt['quota_key_pairs'], None)
        self.assertEqual(ctxt['quota_server_groups'],
                         self.config('quota-server-groups'))
        self.assertEqual(ctxt['quota_server_groups'], None)
        self.assertEqual(ctxt['quota_server_group_members'],
                         self.config('quota-server-group-members'))
        self.assertEqual(ctxt['quota_server_group_members'], None)
        self.assertEqual(ctxt['quota_count_usage_from_placement'],
                         self.config('quota-count-usage-from-placement'))
        self.assertEqual(ctxt['enable_new_services'],
                         self.config('enable-new-services'))
        self.assertEqual(ctxt['console_access_protocol'],
                         self.config('console-access-protocol'))
        self.assertEqual(ctxt['console_access_port'],
                         self.config('console-access-port'))
        self.assertEqual(ctxt['unique_server_names'],
                         self.config('unique-server-names'))
        self.assertEqual(ctxt['skip_hosts_with_build_failures'],
                         self.config('skip-hosts-with-build-failures'))
        self.assertEqual(ctxt['limit_tenants_to_placement_aggregate'],
                         self.config('limit-tenants-to-placement-aggregate'))
        self.assertEqual(
            ctxt["placement_aggregate_required_for_tenants"],
            self.config("placement-aggregate-required-for-tenants"),
        )
        self.assertEqual(ctxt['enable_isolated_aggregate_filtering'],
                         self.config('enable-isolated-aggregate-filtering'))
        self.assertEqual(ctxt['max_local_block_devices'],
                         self.config('max-local-block-devices'))

    _pci_alias1 = {
        "name": "IntelNIC",
        "capability_type": "pci",
        "product_id": "1111",
        "vendor_id": "8086",
        "device_type": "type-PF"}

    _pci_alias2 = {
        "name": " Cirrus Logic ",
        "capability_type": "pci",
        "product_id": "0ff2",
        "vendor_id": "10de",
        "device_type": "type-PCI"}

    _pci_alias_resource_class = {
        "name": "b300-nvlink-2gpu",
        "device_type": "type-PF",
        "resource_class": "CUSTOM_B300_NVLINK_2GPU",
        "numa_policy": "required"}

    _pci_alias_list = [_pci_alias1, _pci_alias2]

    @mock.patch('charmhelpers.contrib.openstack.ip.config')
    @mock.patch('charmhelpers.core.hookenv.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_allow_resize_to_same_host(self, mock_config,
                                       local_unit, mock_config_ip):
        _rel_data = {'disk_allocation_ratio':
                     self.config('disk-allocation-ratio'),
                     'cpu_allocation_ratio':
                     self.config('cpu-allocation-ratio'),
                     'ram_allocation_ratio':
                     self.config('ram-allocation-ratio'),
                     'allow_resize_to_same_host': True}
        self.test_config.set('allow-resize-to-same-host', True)
        self.relation_ids.return_value = ['nova-compute:0']
        ctxt = context.NovaConfigContext()()
        self.assertEqual(ctxt['allow_resize_to_same_host'],
                         self.config('allow-resize-to-same-host'))
        self.relation_set.assert_called_with(relation_id=mock.ANY,
                                             relation_settings=_rel_data)

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('charmhelpers.contrib.openstack.ip.unit_get')
    @mock.patch('charmhelpers.contrib.hahelpers.cluster.relation_ids')
    @mock.patch('charmhelpers.core.hookenv.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_nova_config_context_multi_pci_alias(self, mock_config,
                                                 local_unit,
                                                 mock_relation_ids,
                                                 mock_unit_get,
                                                 mock_resolve_address):
        local_unit.return_value = 'nova-cloud-controller/0'
        mock_config.side_effect = self.test_config.get
        mock_unit_get.return_value = '127.0.0.1'
        self.test_config.set(
            'pci-alias', json.dumps(self._pci_alias1))
        ctxt = context.NovaConfigContext()()
        self.assertEqual(
            ctxt['pci_alias'],
            ('{"capability_type": "pci", "device_type": "type-PF", '
             '"name": "IntelNIC", "product_id": "1111", '
             '"vendor_id": "8086"}'))

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('charmhelpers.contrib.openstack.ip.unit_get')
    @mock.patch('charmhelpers.contrib.hahelpers.cluster.relation_ids')
    @mock.patch('charmhelpers.core.hookenv.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_nova_config_context_multi_pci_aliases(self,
                                                   mock_config,
                                                   local_unit,
                                                   mock_relation_ids,
                                                   mock_unit_get,
                                                   mock_resolve_address):
        local_unit.return_value = 'nova-cloud-controller/0'
        mock_config.side_effect = self.test_config.get
        mock_unit_get.return_value = '127.0.0.1'
        self.test_config.set(
            'pci-alias', json.dumps(self._pci_alias_list))
        ctxt = context.NovaConfigContext()()
        self.assertEqual(
            ctxt['pci_aliases'][0],
            ('{"capability_type": "pci", "device_type": "type-PF", '
             '"name": "IntelNIC", "product_id": "1111", '
             '"vendor_id": "8086"}'))
        self.assertEqual(
            ctxt['pci_aliases'][1],
            ('{"capability_type": "pci", "device_type": "type-PCI", '
             '"name": " Cirrus Logic ", "product_id": "0ff2", '
             '"vendor_id": "10de"}'))

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('charmhelpers.contrib.openstack.ip.unit_get')
    @mock.patch('charmhelpers.core.hookenv.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_pci_alias_resource_class(self, mock_config, local_unit,
                                      mock_unit_get, mock_resolve_address):
        local_unit.return_value = 'nova-cloud-controller/0'
        mock_config.side_effect = self.test_config.get
        mock_unit_get.return_value = '127.0.0.1'
        mock_resolve_address.return_value = '10.0.0.1'
        self.test_config.set(
            'pci-alias', json.dumps(self._pci_alias_resource_class))

        ctxt = context.NovaConfigContext()()

        self.assertEqual(
            'CUSTOM_B300_NVLINK_2GPU',
            json.loads(ctxt['pci_alias'])['resource_class'])

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('charmhelpers.contrib.openstack.ip.unit_get')
    @mock.patch('charmhelpers.core.hookenv.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_pci_in_placement(self, mock_config, local_unit, mock_unit_get,
                              mock_resolve_address):
        local_unit.return_value = 'nova-cloud-controller/0'
        mock_config.side_effect = self.test_config.get
        mock_unit_get.return_value = '127.0.0.1'
        mock_resolve_address.return_value = '10.0.0.1'
        self.os_release.return_value = 'antelope'
        self.test_config.set('pci-in-placement', True)

        ctxt = context.NovaConfigContext()()

        self.assertTrue(ctxt['pci_in_placement'])

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('charmhelpers.contrib.openstack.ip.unit_get')
    @mock.patch('charmhelpers.core.hookenv.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_pci_in_placement_ignored_before_antelope(
            self, mock_config, local_unit, mock_unit_get,
            mock_resolve_address):
        local_unit.return_value = 'nova-cloud-controller/0'
        mock_config.side_effect = self.test_config.get
        mock_unit_get.return_value = '127.0.0.1'
        mock_resolve_address.return_value = '10.0.0.1'
        self.os_release.return_value = 'yoga'
        self.test_config.set('pci-in-placement', True)

        ctxt = context.NovaConfigContext()()

        self.assertNotIn('pci_in_placement', ctxt)

    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    @mock.patch('charmhelpers.contrib.openstack.ip.unit_get')
    @mock.patch('charmhelpers.core.hookenv.local_unit')
    @mock.patch('charmhelpers.contrib.openstack.context.config')
    def test_pci_in_placement_default(self, mock_config, local_unit,
                                      mock_unit_get, mock_resolve_address):
        local_unit.return_value = 'nova-cloud-controller/0'
        mock_config.side_effect = self.test_config.get
        mock_unit_get.return_value = '127.0.0.1'
        mock_resolve_address.return_value = '10.0.0.1'
        self.os_release.return_value = 'caracal'

        ctxt = context.NovaConfigContext()()

        self.assertNotIn('pci_in_placement', ctxt)

    @mock.patch('charmhelpers.contrib.network.ip.format_ipv6_addr')
    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    def test_serial_console_context(self,
                                    mock_resolve_address,
                                    mock_format_ipv6_address):
        mock_format_ipv6_address.return_value = None
        mock_resolve_address.return_value = '10.10.10.1'
        ctxt = context.SerialConsoleContext()()
        self.assertEqual(
            ctxt,
            {'serial_console_base_url': 'ws://10.10.10.1:6083/',
             'enable_serial_console': 'false'}
        )
        mock_resolve_address.assert_called_with(
            endpoint_type=context.ch_ip.PUBLIC)

    @mock.patch('charmhelpers.contrib.network.ip.format_ipv6_addr')
    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    def test_serial_console_context_enabled(self,
                                            mock_resolve_address,
                                            mock_format_ipv6_address):
        self.test_config.set('enable-serial-console', True)
        mock_format_ipv6_address.return_value = None
        mock_resolve_address.return_value = '10.10.10.1'

        # no relation to openstack-dashboard:dashboard
        ctxt = context.SerialConsoleContext()()
        self.assertEqual(
            ctxt,
            {'serial_console_base_url': 'ws://10.10.10.1:6083/',
             'enable_serial_console': 'true'}
        )
        mock_resolve_address.assert_called_with(
            endpoint_type=context.ch_ip.PUBLIC)

        # generated context when related to openstack-dashboard:dashboard
        fake_relation_ids = {
            'dashboard': ['dashboard:1'],
        }
        self.relation_ids.side_effect = fake_relation_ids.get
        fake_related_units = {'dashboard:1': ['openstack-dashboard/0']}
        self.related_units.side_effect = fake_related_units.get

        def fake_relation_get(attribute=None, rid=None, unit=None, app=None):
            data = {
                'dashboard:1': {
                    'openstack-dashboard/0': {
                        'os-public-hostname': 'myhostname',
                        'vip': '1.2.3.4',
                        'ingress-address': '10.20.30.40',
                    },
                }
            }
            if attribute:
                return data[rid][unit or app][attribute]
            else:
                return data[rid][unit or app]

        self.relation_get.side_effect = fake_relation_get

        ctxt = context.SerialConsoleContext()()
        self.assertEqual(
            ctxt,
            {'serial_console_base_url': 'ws://10.10.10.1:6083/',
             'enable_serial_console': 'true',
             'console_allowed_origins': ['myhostname', '1.2.3.4',
                                         '10.20.30.40']}
        )

        with mock.patch('os.path.isfile') as isfile:
            isfile.return_value = True
            ctxt = context.SerialConsoleContext()()
            self.assertEqual(
                ctxt,
                {'serial_console_base_url': 'wss://10.10.10.1:6083/',
                 'enable_serial_console': 'true',
                 'console_allowed_origins': ['myhostname', '1.2.3.4',
                                             '10.20.30.40']}
            )
            isfile.assert_called_with(context.APACHE_24_CONF)

    @mock.patch.object(context, 'ch_cluster')
    @mock.patch('os.path.exists')
    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    def test_instance_console_context(self,
                                      mock_resolve_address,
                                      mock_os_path_exists,
                                      mock_ch_cluster):
        mock_os_path_exists.return_value = True
        mock_resolve_address.return_value = "10.20.30.40"
        mock_ch_cluster.https.return_value = True
        ctxt = context.InstanceConsoleContext()()
        self.assertEqual(
            ctxt,
            {'ssl_cert': '/etc/apache2/ssl/nova/cert_10.20.30.40',
             'ssl_key': '/etc/apache2/ssl/nova/key_10.20.30.40'}
        )
        mock_resolve_address.assert_called_once_with(
            endpoint_type=context.ch_ip.PUBLIC
        )

    @mock.patch.object(context, 'ch_cluster')
    @mock.patch('os.path.exists')
    @mock.patch('charmhelpers.contrib.openstack.ip.resolve_address')
    def test_instance_console_context_no_https(self,
                                               mock_resolve_address,
                                               mock_os_path_exists,
                                               mock_ch_cluster):
        mock_os_path_exists.return_value = True
        mock_resolve_address.return_value = "10.20.30.40"
        mock_ch_cluster.https.return_value = False
        ctxt = context.InstanceConsoleContext()()
        self.assertEqual(
            ctxt, {}
        )

    def test_nova_cellv2_shared_db_context(self):
        self.relation_ids.return_value = ['shared-db:0']
        self.related_units.return_value = ['mysql/0']
        self.test_relation.set(
            {'novaapi_password': 'changeme',
             'novacell0_password': 'passw0rd',
             'nova_password': '1234'})
        self.assertEqual(
            context.NovaCellV2SharedDBContext()(),
            {'novaapi_password': 'changeme',
             'novacell0_password': 'passw0rd',
             'nova_password': '1234'})

    @mock.patch.object(context, 'context_complete', lambda *args: True)
    def test_NeutronAPIContext(self):
        self.relation_ids.return_value = ['neutron-api:12']
        self.related_units.return_value = ['neutron-api/0']
        settings = {'neutron-plugin': 'ovs',
                    'enable-sriov': 'False',
                    'enable-hardware-offload': 'False',
                    'neutron-security-groups': 'yes',
                    'neutron-url': 'http://neutron:9696'}

        def fake_rel_get(attribute=None, unit=None, rid=None):
            if attribute:
                return settings.get(attribute)

            return settings

        self.relation_get.side_effect = fake_rel_get
        ctxt = context.NeutronAPIContext()()
        expected = {'network_manager': 'neutron',
                    'neutron_plugin': 'ovs',
                    'neutron_security_groups': 'yes',
                    'neutron_url': 'http://neutron:9696'}
        self.assertEqual(ctxt, expected)

        settings['enable-sriov'] = 'True'
        expected['additional_neutron_filters'] = 'PciPassthroughFilter'
        ctxt = context.NeutronAPIContext()()
        self.assertEqual(ctxt, expected)

        settings['enable-sriov'] = 'False'
        settings['enable-hardware-offload'] = 'True'
        expected['additional_neutron_filters'] = 'PciPassthroughFilter'
        ctxt = context.NeutronAPIContext()()
        self.assertEqual(ctxt, expected)

    def test_CinderContext(self):
        self.test_config.update({'cross-az-attach': False, })
        ctxt = context.CinderConfigContext()()
        self.assertEqual({'cross_az_attach': False}, ctxt)

        self.test_config.update({'cross-az-attach': True, })
        ctxt = context.CinderConfigContext()()
        self.assertEqual({'cross_az_attach': True}, ctxt)

    @mock.patch('charmhelpers.contrib.openstack.context.'
                'NovaVendorMetadataContext.__call__')
    def test_vendordata_static_and_dynamic(self, parent):
        _vdata = {
            'vendor_data': True,
            'vendor_data_url': 'http://example.org/vdata',
            'vendordata_providers': 'StaticJSON,DynamicJSON',
        }
        self.relation_ids.return_value = ['nova-compute:1']
        self.os_release.return_value = 'rocky'
        self.leader_get.return_value = 'auuid'
        parent.return_value = _vdata
        ctxt = context.NovaMetadataContext('nova-common')()

        self.assertTrue(ctxt['vendor_data'])
        self.assertEqual(_vdata['vendor_data_url'], ctxt['vendor_data_url'])
        self.assertEqual('StaticJSON,DynamicJSON',
                         ctxt['vendordata_providers'])
        self.assertTrue(ctxt['enable_metadata'])
        self.assertEqual('auuid', ctxt['metadata_proxy_shared_secret'])
        self.relation_set.assert_called_with(relation_id=mock.ANY,
                                             vendor_data=json.dumps(_vdata))

    @mock.patch('charmhelpers.contrib.openstack.context.'
                'NovaVendorMetadataContext.__call__')
    def test_vendordata_pike(self, parent):
        _vdata = {
            'vendor_data': True,
            'vendor_data_url': 'http://example.org/vdata',
            'vendordata_providers': 'StaticJSON,DynamicJSON',
        }
        self.relation_ids.return_value = ['nova-compute:1']
        self.os_release.return_value = 'pike'
        parent.return_value = _vdata
        ctxt = context.NovaMetadataContext('nova-common')()

        self.assertEqual({'enable_metadata': False}, ctxt)
        self.relation_set.assert_called_with(relation_id=mock.ANY,
                                             vendor_data=json.dumps(_vdata))

    @mock.patch('charmhelpers.contrib.openstack.context.'
                'NovaVendorMetadataJSONContext.__call__')
    def test_vendor_json_valid(self, parent):
        self.os_release.return_value = 'rocky'
        _vdata = {'vendor_data_json': '{"good": "json"}'}
        parent.return_value = _vdata
        self.relation_ids.return_value = ['nova-compute:1']
        ctxt = context.NovaMetadataJSONContext('nova-common')()
        self.assertEqual(_vdata, ctxt)
        self.relation_set.assert_called_with(relation_id=mock.ANY,
                                             vendor_json='{"good": "json"}')

    @mock.patch('charmhelpers.contrib.openstack.context.'
                'NovaVendorMetadataJSONContext.__call__')
    def test_vendor_json_prior_rocky(self, parent):
        self.os_release.return_value = 'queens'
        _vdata = {'vendor_data_json': '{"good": "json"}'}
        parent.return_value = _vdata
        self.relation_ids.return_value = ['nova-compute:1']
        ctxt = context.NovaMetadataJSONContext('nova-common')()
        self.assertEqual({'vendor_data_json': '{}'}, ctxt)
        self.relation_set.assert_called_with(relation_id=mock.ANY,
                                             vendor_json='{"good": "json"}')

    def test_NovaCellV2Context(self):
        settings = {'cell-name': 'cell32',
                    'amqp-service': 'rabbitmq-cell2',
                    'db-service': 'percona-cell2'}

        def fake_rel_get(attribute=None, unit=None, rid=None):
            if attribute:
                return settings.get(attribute)

            return settings

        self.relation_get.side_effect = fake_rel_get
        self.relation_ids.return_value = ['nova-cell:0']
        self.related_units.return_value = ['nova-cell-conductor/0']
        ctxt = context.NovaCellV2Context()()
        self.assertEqual(
            ctxt,
            {'cell32': {
                'amqp_service': 'rabbitmq-cell2',
                'db_service': 'percona-cell2'}})

    def test_NovaCellV2Context_missing_amqp(self):
        settings = {'cell-name': 'cell32',
                    'db-service': 'percona-cell2'}

        def fake_rel_get(attribute=None, unit=None, rid=None):
            if attribute:
                return settings.get(attribute)

            return settings

        self.relation_get.side_effect = fake_rel_get
        self.relation_ids.return_value = ['nova-cell:0']
        self.related_units.return_value = ['nova-cell-conductor/0']
        ctxt = context.NovaCellV2Context()()
        self.assertEqual(ctxt, {})

    def test_default_enabled_filters_icehouse(self):
        self.os_release.return_value = 'icehouse'
        self.assertEqual(context.default_enabled_filters(),
                         context._base_enabled_filters)

    def test_default_enabled_filters_pike(self):
        self.os_release.return_value = 'pike'
        self.assertEqual(context.default_enabled_filters(),
                         context._pike_enabled_filters)

    def test_default_enabled_filters_rocky(self):
        self.os_release.return_value = 'rocky'
        self.assertEqual(context.default_enabled_filters(),
                         context._pike_enabled_filters)

    def test_default_enabled_filters_victoria(self):
        self.os_release.return_value = 'victoria'
        self.assertEqual(context.default_enabled_filters(),
                         context._victoria_enabled_filters)

    def test_default_enabled_filters_bobcat(self):
        self.os_release.return_value = 'bobcat'
        self.assertEqual(context.default_enabled_filters(),
                         context._bobcat_enabled_filters)
