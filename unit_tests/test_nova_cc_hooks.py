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

from unittest.mock import MagicMock, patch, call
import os
import tempfile

from unit_tests.test_utils import CharmTestCase

import charmhelpers.contrib.hardening.harden as harden
import charmhelpers.core.unitdata

import hooks.nova_cc_utils as utils
import hooks.nova_cc_hooks as hooks


TO_PATCH = [
    'charmhelpers.contrib.hahelpers.cluster.get_hacluster_config',
    'charmhelpers.contrib.hahelpers.cluster.is_clustered',
    'charmhelpers.contrib.network.ip.get_iface_for_address',
    'charmhelpers.contrib.network.ip.get_netmask_for_address',
    'charmhelpers.contrib.network.ip.get_relation_ip',
    'charmhelpers.contrib.network.ip.ns_query',
    'charmhelpers.contrib.openstack.ha.utils.generate_ha_relation_data',
    'charmhelpers.contrib.openstack.ha.utils.update_dns_ha_resource_params',
    'charmhelpers.contrib.openstack.neutron.network_manager',
    'charmhelpers.contrib.openstack.policyd.maybe_do_policyd_overrides',
    'charmhelpers.contrib.openstack.policyd.'
    'maybe_do_policyd_overrides_on_config_changed',
    'charmhelpers.contrib.openstack.utils.configure_installation_source',
    'charmhelpers.contrib.openstack.utils.config_value_changed',
    'charmhelpers.contrib.openstack.utils.is_unit_paused_set',
    'charmhelpers.contrib.openstack.utils.is_db_maintenance_mode',
    'charmhelpers.contrib.openstack.utils.openstack_upgrade_available',
    'charmhelpers.contrib.openstack.utils.os_release',
    'charmhelpers.core.hookenv.charm_dir',
    'charmhelpers.core.hookenv.config',
    'charmhelpers.core.hookenv.is_leader',
    'charmhelpers.core.hookenv.is_relation_made',
    'charmhelpers.core.hookenv.local_unit',
    'charmhelpers.core.hookenv.log',
    'charmhelpers.core.hookenv.open_port',
    'charmhelpers.core.hookenv.related_units',
    'charmhelpers.core.hookenv.relation_get',
    'charmhelpers.core.hookenv.relation_ids',
    'charmhelpers.core.hookenv.relation_set',
    'charmhelpers.core.hookenv.status_set',
    'charmhelpers.core.hookenv.unit_get',
    'charmhelpers.core.host.service_pause',
    'charmhelpers.core.host.service_reload',
    'charmhelpers.core.host.service_restart',
    'charmhelpers.core.host.service_resume',
    'charmhelpers.fetch.apt_install',
    'charmhelpers.fetch.apt_update',
    'charmhelpers.payload.execd.execd_preinstall',
    'hooks.nova_cc_utils.determine_endpoints',
    'hooks.nova_cc_utils.determine_packages',
    'hooks.nova_cc_utils.determine_ports',
    'hooks.nova_cc_utils.do_openstack_upgrade',
    'hooks.nova_cc_utils.get_ca_cert_b64',
    'hooks.nova_cc_utils.migrate_nova_databases',
    'hooks.nova_cc_utils.placement_api_enabled',
    'hooks.nova_cc_utils.save_script_rc',
    'hooks.nova_cc_utils.serial_console_settings',
    'hooks.nova_cc_utils.services',
    'hooks.nova_cc_utils.ssh_authorized_keys_lines',
    'hooks.nova_cc_utils.ssh_compute_add_known_hosts',
    'hooks.nova_cc_utils.ssh_known_hosts_lines',
    'uuid',
]


FAKE_KS_AUTH_CFG = {
    'auth_host': 'kshost',
    'auth_port': '5000',
    'service_port': 'token',
    'service_username': 'admin_user',
    'service_password': 'admin_passwd',
    'service_tenant_name': 'admin_tenant',
    'auth_uri': 'http://kshost:5000/v2',
    # quantum-gateway interface deviates a bit.
    'keystone_host': 'kshost',
    'service_tenant': 'service_tenant',
}


class NovaCCHooksTests(CharmTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        charmhelpers.core.unitdata._KV = (
            charmhelpers.core.unitdata.Storage(':memory:'))

    def setUp(self):
        super(NovaCCHooksTests, self).setUp(hooks, TO_PATCH)
        (tmpfd, hooks.NOVA_CONSOLEAUTH_OVERRIDE) = tempfile.mkstemp()

        hooks.CONFIGS = None  # reset for each test
        self.config.side_effect = self.test_config.get
        self.relation_get.side_effect = self.test_relation.get
        self.charm_dir.return_value = '/var/lib/juju/charms/nova/charm'
        self.ns_query.return_value = None
        self.is_unit_paused_set.return_value = False
        self.is_db_maintenance_mode.return_value = False
        self.os_release.return_value = 'rocky'
        self.relation_ids.return_value = []
        # disable hardening for unit tests
        harden._DISABLE_HARDENING_FOR_UNIT_TEST = True

    def tearDown(self):
        try:
            os.remove(hooks.NOVA_CONSOLEAUTH_OVERRIDE)
        except OSError:
            pass

        super(NovaCCHooksTests, self).tearDown()

    @patch.object(utils, 'get_metadata_settings')
    def test_publish_remote_metadata(self, metadata):
        metadata.return_value = {
            'nova-metadata-host': 'metadata.example.test',
            'nova-metadata-protocol': 'https',
            'nova-metadata-port': 8775,
            'shared-metadata-secret': 'controller-secret',
        }
        self.get_ca_cert_b64.return_value = 'encoded-ca'
        hooks.publish_remote_metadata('remote:1')
        self.relation_set.assert_called_once_with(
            relation_id='remote:1', relation_settings={
                'private-address': 'metadata.example.test',
                'metadata-shared-secret': 'controller-secret',
                'nova-metadata-protocol': 'https',
                'nova-metadata-port': 8775,
                'ca_cert': 'encoded-ca',
            })

    @patch.object(utils, 'get_metadata_settings')
    def test_publish_remote_metadata_withdraws_unavailable_credentials(
            self, metadata):
        metadata.return_value = {}
        self.get_ca_cert_b64.return_value = ''
        self.relation_ids.return_value = ['remote:1', 'remote:2']
        hooks.publish_remote_metadata()
        self.assertEqual(2, self.relation_set.call_count)
        for call_args in self.relation_set.call_args_list:
            self.assertEqual({
                'private-address': None,
                'metadata-shared-secret': None,
                'nova-metadata-protocol': None,
                'nova-metadata-port': None,
                'ca_cert': None,
            }, call_args.kwargs['relation_settings'])

    @patch.object(utils, 'get_metadata_settings')
    def test_no_remote_relation_does_not_resolve_endpoint(self, metadata):
        self.relation_ids.return_value = []
        hooks.publish_remote_metadata()
        metadata.assert_not_called()
        self.relation_set.assert_not_called()

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    @patch.object(hooks.hookenv, 'leader_get')
    def test_remote_metadata_uses_controller_secret_and_vip(
            self, leader_get, canonical_url):
        self.os_release.return_value = 'caracal'
        self.get_ca_cert_b64.return_value = ''
        canonical_url.return_value = 'https://192.0.2.100'
        for secret in ('initial-controller-secret', 'rotated-secret'):
            with self.subTest(secret=secret):
                leader_get.return_value = secret
                hooks.publish_remote_metadata('remote:1')
                settings = self.relation_set.call_args.kwargs[
                    'relation_settings']
                self.assertEqual('192.0.2.100', settings['private-address'])
                self.assertEqual(secret, settings['metadata-shared-secret'])
                self.assertEqual('https', settings['nova-metadata-protocol'])
                self.assertEqual(8775, settings['nova-metadata-port'])
                leader_get.assert_called_with('shared-metadata-secret')

    @patch.object(hooks, 'publish_remote_metadata')
    def test_update_nova_relation_refreshes_remote_metadata(self, publish):
        hooks.update_nova_relation()
        publish.assert_called_once_with()

    def test_install_hook(self):
        self.os_release.return_value = 'rocky'
        self.determine_packages.return_value = [
            'nova-scheduler', 'nova-api-ec2']
        self.determine_ports.return_value = [80, 81, 82]
        self.is_unit_paused_set.return_value = False
        self.services.return_value = ['dummy-service']
        hooks.install()
        self.apt_install.assert_called_with(
            ['nova-scheduler', 'nova-api-ec2'], fatal=True)
        self.execd_preinstall.assert_called()
        self.service_pause.assert_called()

    @patch.object(utils, 'set_shared_metadatasecret')
    @patch.object(utils, 'get_shared_metadatasecret')
    @patch.object(hooks, 'update_nrpe_config')
    @patch.object(utils, 'resource_map')
    @patch('hooks.nova_cc_utils.update_aws_compat_services')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch('charmhelpers.fetch.filter_installed_packages')
    @patch.object(hooks, 'configure_https')
    def test_config_changed_no_upgrade(self, conf_https, mock_filter_packages,
                                       mock_is_db_initialised,
                                       mock_update_aws_compat_services,
                                       mock_resource_map,
                                       mock_update_nrpe_config,
                                       mock_get_shared_metadatasecret,
                                       mock_set_shared_metadatasecret):
        mock_resource_map.return_value = {}
        self.get_shared_metadatasecret = None
        self.determine_packages.return_value = []
        self.is_leader.return_value = True
        self.test_config.set('console-access-protocol', 'dummy')
        self.openstack_upgrade_available.return_value = False
        mock_is_db_initialised.return_value = False
        self.os_release.return_value = 'diablo'
        hooks.resolve_CONFIGS()
        hooks.config_changed()
        self.save_script_rc.assert_called()
        mock_filter_packages.assert_called_with([])
        mock_update_aws_compat_services.assert_called()

    @patch.object(utils, 'set_shared_metadatasecret')
    @patch.object(utils, 'get_shared_metadatasecret')
    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    @patch.object(hooks, 'update_nrpe_config')
    @patch('hooks.nova_cc_utils.update_aws_compat_services')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch('charmhelpers.fetch.filter_installed_packages')
    @patch.object(hooks, 'configure_https')
    def test_config_changed_ocata(self,
                                  conf_https,
                                  mock_filter_packages,
                                  mock_is_db_initialised,
                                  mock_update_aws_compat_services,
                                  mock_update_nrpe_config,
                                  mock_sub_ctxt,
                                  mock_get_shared_metadatasecret,
                                  mock_set_shared_metadatasecret):
        mock_get_shared_metadatasecret.return_value = None
        self.is_leader.return_value = True
        self.determine_packages.return_value = []
        self.test_config.set('console-access-protocol', 'dummy')
        self.openstack_upgrade_available.return_value = False
        mock_is_db_initialised.return_value = False
        self.os_release.return_value = 'diablo'
        hooks.resolve_CONFIGS()
        # probably need the with patch.object from below
        with patch.object(hooks.CONFIGS, 'write_all') as wa:
            hooks.config_changed()
            wa.assert_called()
        self.save_script_rc.assert_called()
        mock_filter_packages.assert_called_with([])
        mock_update_aws_compat_services.assert_called()
        mock_set_shared_metadatasecret.assert_called_once_with()

    @patch.object(utils, 'set_shared_metadatasecret')
    @patch.object(utils, 'get_shared_metadatasecret')
    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    @patch.object(hooks, 'update_nrpe_config')
    @patch('hooks.nova_cc_utils.update_aws_compat_services')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch('charmhelpers.fetch.filter_installed_packages')
    @patch.object(hooks, 'configure_https')
    def test_config_changed_no_upgrade_juno(self, conf_https,
                                            mock_filter_packages,
                                            mock_is_db_initialised,
                                            mock_update_aws_compat_services,
                                            mock_update_nrpe_config,
                                            mock_sub_ctxt,
                                            mock_get_shared_metadatasecret,
                                            mock_set_shared_metadatasecret):
        self.determine_packages.return_value = []
        self.test_config.set('console-access-protocol', 'dummy')
        self.openstack_upgrade_available.return_value = False
        mock_is_db_initialised.return_value = False
        self.os_release.return_value = 'juno'
        hooks.resolve_CONFIGS()
        with patch.object(hooks.CONFIGS, 'write_all') as wa:
            hooks.config_changed()
            wa.assert_called()
        self.save_script_rc.assert_called()
        mock_filter_packages.assert_called_with([])
        mock_update_aws_compat_services.assert_called()
        self.service_pause.assert_called_with('neutron-server')

    @patch.object(utils, 'set_shared_metadatasecret')
    @patch.object(utils, 'get_shared_metadatasecret')
    @patch.object(hooks, 'update_nrpe_config')
    @patch.object(utils, 'resource_map')
    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    @patch('hooks.nova_cc_utils.update_aws_compat_services')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch('charmhelpers.fetch.filter_installed_packages')
    @patch.object(hooks, 'configure_https')
    def test_config_changed_no_upgrade_juno_no_neutron_server(
            self,
            conf_https,
            mock_filter_packages,
            mock_is_db_initialised,
            mock_update_aws_compat_services,
            mock_sub_ctxt,
            mock_resource_map,
            mock_update_nrpe_config,
            mock_get_shared_metadatasecret,
            mock_set_shared_metadatasecret):
        mock_resource_map.return_value = {}
        self.determine_packages.return_value = []
        self.test_config.set('console-access-protocol', 'dummy')
        self.openstack_upgrade_available.return_value = False
        mock_is_db_initialised.return_value = False
        self.os_release.return_value = 'juno'
        self.service_pause.side_effect = ValueError
        hooks.resolve_CONFIGS()
        with patch.object(hooks.CONFIGS, 'write_all'):
            hooks.config_changed()
        self.save_script_rc.assert_called()
        mock_filter_packages.assert_called_with([])
        mock_update_aws_compat_services.assert_called()
        self.service_pause.assert_called_with('neutron-server')

    @patch.object(utils, 'set_shared_metadatasecret')
    @patch.object(utils, 'get_shared_metadatasecret')
    @patch.object(hooks, 'update_nrpe_config')
    @patch.object(utils, 'resource_map')
    @patch('hooks.nova_cc_utils.update_aws_compat_services')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch.object(hooks, 'quantum_joined')
    @patch('charmhelpers.contrib.openstack.ip.unit_get')
    @patch('charmhelpers.contrib.hahelpers.cluster.relation_ids')
    @patch.object(hooks, 'db_joined')
    @patch('charmhelpers.fetch.filter_installed_packages')
    @patch('charmhelpers.contrib.openstack.ip.service_name',
           lambda *args: 'nova-cloud-controller')
    @patch.object(hooks, 'cluster_joined')
    @patch.object(hooks, 'identity_joined')
    @patch.object(hooks, 'neutron_api_relation_joined')
    @patch.object(hooks, 'configure_https')
    @patch.object(hooks, 'compute_joined')
    @patch.object(hooks, 'nova_cell_api_relation_joined')
    def test_config_changed_with_upgrade(self,
                                         mock_nova_cell_api_relation_joined,
                                         mock_compute_joined,
                                         conf_https, neutron_api_joined,
                                         identity_joined, cluster_joined,
                                         mock_filter_packages, db_joined,
                                         mock_relids,
                                         mock_unit_get,
                                         mock_quantum_joined,
                                         mock_is_db_initialised,
                                         mock_update_aws_compat_services,
                                         mock_resource_map,
                                         mock_update_nrpe_config,
                                         mock_get_shared_metadatasecret,
                                         mock_set_shared_metadatasecret):
        mock_resource_map.return_value = {}
        self.determine_packages.return_value = []
        mock_is_db_initialised.return_value = False
        self.openstack_upgrade_available.return_value = True
        self.relation_ids.return_value = ['generic_rid']
        self.test_config.set('console-access-protocol', 'dummy')
        mock_relids.return_value = []
        mock_unit_get.return_value = '127.0.0.1'
        self.os_release.return_value = 'diablo'
        hooks.resolve_CONFIGS()
        hooks.config_changed()
        self.do_openstack_upgrade.assert_called()
        neutron_api_joined.assert_called()
        identity_joined.assert_called()
        cluster_joined.assert_called()
        db_joined.assert_called()
        self.save_script_rc.assert_called()
        mock_filter_packages.assert_called_with([])
        mock_quantum_joined.assert_called()
        mock_update_aws_compat_services.assert_called()

        # test upgrade from stein->train without placement related
        self.do_openstack_upgrade.return_value = None
        self.os_release.return_value = 'stein'
        self.save_script_rc.reset_mock()
        hooks.config_changed()
        self.do_openstack_upgrade.assert_called()
        self.save_script_rc.assert_not_called()

    @patch.object(utils, 'set_shared_metadatasecret')
    @patch.object(utils, 'get_shared_metadatasecret')
    @patch.object(hooks, 'update_nrpe_config')
    @patch.object(utils, 'resource_map')
    @patch('charmhelpers.contrib.hahelpers.cluster.relation_ids')
    @patch('hooks.nova_cc_utils.update_aws_compat_services')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch('charmhelpers.fetch.filter_installed_packages')
    @patch.object(hooks, 'configure_https')
    @patch.object(hooks, 'compute_joined')
    @patch.object(hooks, 'set_region_on_relation_from_config')
    def test_config_changed_region_change(
            self,
            mock_set_region_on_relation_from_config,
            mock_compute_joined,
            mock_config_https,
            mock_filter_packages,
            mock_is_db_initialised,
            mock_update_aws_compat_services,
            mock_relation_ids,
            mock_resource_map,
            mock_update_nrpe_config,
            mock_get_shared_metadatasecret,
            mock_set_shared_metadatasecret):
        mock_resource_map.return_value = {}
        self.openstack_upgrade_available.return_value = False
        self.config_value_changed.return_value = True
        self.related_units.return_value = ['unit/0']
        self.relation_ids.side_effect = \
            lambda x: ['generic_rid'] if x == 'cloud-compute' else []
        mock_set_region_on_relation_from_config.return_value = False
        self.os_release.return_value = 'diablo'
        hooks.resolve_CONFIGS()
        hooks.config_changed()
        mock_set_region_on_relation_from_config.assert_has_calls(
            [call('generic_rid')])
        mock_compute_joined.assert_has_calls(
            [call(rid='generic_rid', remote_restart=False)])
        mock_update_aws_compat_services.assert_called()

    @patch.object(hooks, 'add_hosts_to_cell_when_ready')
    @patch.object(hooks, 'set_region_on_relation_from_config')
    @patch.object(hooks, 'update_ssh_key')
    @patch.object(hooks, 'update_compute_units_with_ssh_key_change')
    def test_cloud_compute_relation_changed(
            self,
            mock_update_compute_units_with_ssh_key_change,
            mock_update_ssh_key,
            mock_set_region_on_relation_from_config,
            mock_add_hosts_to_cell_when_ready):
        hooks.cloud_compute_relation_changed()
        mock_add_hosts_to_cell_when_ready.assert_called_once_with()
        mock_set_region_on_relation_from_config.assert_called_once_with(
            rid=None)
        mock_update_ssh_key.assert_called_once_with(rid=None, unit=None)
        mock_update_compute_units_with_ssh_key_change.assert_called_once_with(
            rid=None, unit=None)

    @patch('charmhelpers.core.hookenv.related_units')
    @patch('charmhelpers.core.hookenv.expected_related_units')
    def test__goal_state_achieved_for_relid__goal_state_not_available(
            self, mock_expected_related_units, mock_related_units):
        mock_related_units.return_value = ['service/0']

        def _side_effect(*_, **__):
            raise NotImplementedError()

        mock_expected_related_units.side_effect = _side_effect
        self.assertTrue(hooks._goal_state_achieved_for_relid('aservice', None))

    @patch('charmhelpers.core.hookenv.related_units')
    @patch('charmhelpers.core.hookenv.expected_related_units')
    def test__goal_state_achieved_for_relid__goal_state_key_error(
            self, mock_expected_related_units, mock_related_units):
        mock_related_units.return_value = ['service/0']

        def _side_effect(*_, **__):
            raise KeyError()

        mock_expected_related_units.side_effect = _side_effect
        self.assertFalse(
            hooks._goal_state_achieved_for_relid('aservice', None))

    @patch('charmhelpers.core.hookenv.related_units')
    @patch('charmhelpers.core.hookenv.expected_related_units')
    def test__goal_state_achieved_for_relid__goal_state_no_related_units_yet(
            self, mock_expected_related_units, mock_related_units):
        mock_related_units.return_value = []
        mock_expected_related_units.return_value = ['service/0']
        self.assertFalse(
            hooks._goal_state_achieved_for_relid('aservice', None))

    @patch('charmhelpers.core.hookenv.related_units')
    @patch('charmhelpers.core.hookenv.expected_related_units')
    def test__goal_state_achieved_for_relid__goal_state_insufficient_units(
            self, mock_expected_related_units, mock_related_units):
        mock_related_units.return_value = ['service/0']
        mock_expected_related_units.return_value = ['service/0', 'service/1']
        self.assertFalse(
            hooks._goal_state_achieved_for_relid('aservice', None))

    @patch('charmhelpers.core.hookenv.related_units')
    @patch('charmhelpers.core.hookenv.expected_related_units')
    def test__goal_state_achieved_for_relid__goal_state_sufficient_units(
            self, mock_expected_related_units, mock_related_units):
        # BUG: #1859050 -- units out of order should still match
        mock_related_units.return_value = ['service/1', 'service/0']
        mock_expected_related_units.return_value = ['service/0', 'service/1']
        self.assertTrue(hooks._goal_state_achieved_for_relid('aservice', None))

    @patch('charmhelpers.core.hookenv.related_units')
    @patch('charmhelpers.core.hookenv.expected_related_units')
    def test__goal_state_achieved_for_relid__goal_state_different_units(
            self, mock_expected_related_units, mock_related_units):
        # this shouldn't actually be able to happen, but let's check for it
        # anyway
        mock_related_units.return_value = ['service/0']
        mock_expected_related_units.return_value = \
            ['service-a/0', 'service-b/0']
        self.assertFalse(
            hooks._goal_state_achieved_for_relid('aservice', None))

    @patch.object(utils.hookenv, 'ingress_address')
    @patch('charmhelpers.contrib.openstack.utils.get_hostname')
    @patch('charmhelpers.core.unitdata.Storage.set')
    @patch('hooks.nova_cc_utils.add_authorized_key_if_doesnt_exist')
    @patch('hooks.nova_cc_utils.ssh_compute_add_known_hosts')
    @patch('hooks.nova_cc_utils.remote_service_from_unit')
    def test_update_ssh_key(
            self,
            mock_remote_service_from_unit,
            mock_ssh_compute_add_known_hosts,
            mock_add_authorized_key_if_doesnt_exist,
            mock_db_set,
            mock_get_hostname,
            mock_ingress_address):

        def fake_get_hostname(addr):
            if addr == '10.0.0.1':
                return "bond0.bighost.ace"
            elif addr == '10.1.2.3':
                return "bighost.ace"

            raise Exception("unexpected resolve for address {}".format(addr))

        mock_get_hostname.side_effect = fake_get_hostname
        mock_remote_service_from_unit.return_value = 'aservice'
        mock_ingress_address.return_value = '10.1.2.3'
        self.relation_get.side_effect = [{
            'migration_auth_type': 'ssh', 'ssh_public_key': 'fookey',
            'private-address': '10.0.0.1', 'region': 'RegionOne'}]

        hooks.update_ssh_key(rid=None, unit=None)
        mock_ssh_compute_add_known_hosts.assert_called_once_with(
            'aservice', sorted(['10.0.0.1', 'bond0.bighost.ace', '10.1.2.3',
                                'bighost.ace']), user=None)
        mock_add_authorized_key_if_doesnt_exist.assert_called_once_with(
            'fookey', 'aservice', '10.0.0.1', user=None)
        mock_db_set.assert_has_calls([call('hostset-10.0.0.1',
                                           ['10.0.0.1', 'bond0.bighost.ace']),
                                      call('hostset-10.1.2.3',
                                           ['10.1.2.3', 'bighost.ace'])])

    @patch('charmhelpers.contrib.openstack.utils.get_hostname')
    @patch('charmhelpers.core.unitdata.Storage.set')
    @patch('hooks.nova_cc_utils.add_authorized_key_if_doesnt_exist')
    @patch('hooks.nova_cc_utils.ssh_compute_add_known_hosts')
    @patch('hooks.nova_cc_utils.remote_service_from_unit')
    def test_update_ssh_key_nova_user(
            self,
            mock_remote_service_from_unit,
            mock_ssh_compute_add_known_hosts,
            mock_add_authorized_key_if_doesnt_exist,
            mock_db_set,
            mock_get_hostname):
        mock_get_hostname.return_value = None
        mock_remote_service_from_unit.return_value = 'aservice'

        self.relation_get.side_effect = [{
            'migration_auth_type': 'sasl', 'nova_ssh_public_key': 'fookey',
            'private-address': '10.0.0.1', 'region': 'RegionOne'}]

        hooks.update_ssh_key(rid=None, unit=None)
        mock_ssh_compute_add_known_hosts.assert_called_once_with(
            'aservice', ['10.0.0.1'], user='nova')
        mock_add_authorized_key_if_doesnt_exist.assert_called_once_with(
            'fookey', 'aservice', '10.0.0.1', user='nova')
        mock_db_set.assert_called_once_with('hostset-10.0.0.1', ['10.0.0.1'])

    @patch('os.listdir')
    def test_notify_ssh_keys_to_compute_units(self, mock_listdir):
        self.relation_ids.return_value = [
            'cloud-compute:15', 'cloud-compute:16']

        mock_listdir.return_value = ['nova-compute1', 'nova-compute2']

        self.relation_get.side_effect = None
        self.relation_get.return_value = {
            'migration_auth_type': 'ssh', 'ssh_public_key': 'fookey',
            'private-address': '10.0.0.1', 'region': 'RegionOne'}

        self.ssh_known_hosts_lines.side_effect = [
            ['1k_h_0', '1k_h_1'], ['2k_h_0', '2k_h_1'],
            ['1k_h_0', '1k_h_1'], ['2k_h_0', '2k_h_1'],
        ]
        self.ssh_authorized_keys_lines.side_effect = [
            ['1auth_0', '1auth_1'], ['2auth_0', '2auth_1'],
            ['1auth_0', '1auth_1'], ['2auth_0', '2auth_1'],
        ]

        hooks.notify_ssh_keys_to_compute_units('cloud-compute:X', 'cmp/X')

        self.relation_set.assert_has_calls([
            call(relation_id='cloud-compute:X',
                 relation_settings={'known_hosts_0': '1k_h_0'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'known_hosts_1': '1k_h_1'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'known_hosts_2': '2k_h_0'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'known_hosts_3': '2k_h_1'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'known_hosts_max_index': 4}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'authorized_keys_0': '1auth_0'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'authorized_keys_1': '1auth_1'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'authorized_keys_2': '2auth_0'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'authorized_keys_3': '2auth_1'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'authorized_keys_max_index': 4}),
        ])

    @patch('os.listdir')
    def test_notify_ssh_keys_to_compute_units_nova_user(self, mock_listdir):
        self.relation_ids.return_value = [
            'cloud-compute:15', 'cloud-compute:16']

        mock_listdir.return_value = ['nova-compute1', 'nova-compute2']

        self.relation_get.side_effect = None
        self.relation_get.return_value = {
            'migration_auth_type': 'sasl', 'nova_ssh_public_key': 'fookey',
            'private-address': '10.0.0.1', 'region': 'RegionOne'}

        self.ssh_known_hosts_lines.side_effect = [
            ['1k_h_0', '1k_h_1'], ['2k_h_0', '2k_h_1'],
            ['1k_h_0', '1k_h_1'], ['2k_h_0', '2k_h_1'],
        ]
        self.ssh_authorized_keys_lines.side_effect = [
            ['1auth_0', '1auth_1'], ['2auth_0', '2auth_1'],
            ['1auth_0', '1auth_1'], ['2auth_0', '2auth_1'],
        ]

        hooks.notify_ssh_keys_to_compute_units('cloud-compute:X', 'cmp/X')

        self.relation_set.assert_has_calls([
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_known_hosts_0': '1k_h_0'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_known_hosts_1': '1k_h_1'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_known_hosts_2': '2k_h_0'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_known_hosts_3': '2k_h_1'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_known_hosts_max_index': 4}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_authorized_keys_0': '1auth_0'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_authorized_keys_1': '1auth_1'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_authorized_keys_2': '2auth_0'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_authorized_keys_3': '2auth_1'}),
            call(relation_id='cloud-compute:X',
                 relation_settings={'nova_authorized_keys_max_index': 4}),
        ])

    @patch('hooks.nova_cc_hooks._goal_state_achieved_for_relid')
    @patch('hooks.nova_cc_hooks.notify_ssh_keys_to_compute_units')
    def test_update_compute_units_with_ssh_key_change_rel_changed(
            self,
            mock_notify_ssh_keys_to_compute_units,
            mock__goal_state_achieved_for_relid):

        self.relation_ids.return_value = [
            'cloud-compute:15', 'cloud-compute:16']
        mock__goal_state_achieved_for_relid.side_effect = [True, True]

        self.related_units.side_effect = [['cmp/0', 'cmp/1'],
                                          ['cmp2/0', 'cmp2/1']]

        hooks.update_compute_units_with_ssh_key_change()

        mock__goal_state_achieved_for_relid.assert_has_calls([
            call('cloud-compute', 'cloud-compute:15'),
            call('cloud-compute', 'cloud-compute:16'),
        ])

        mock_notify_ssh_keys_to_compute_units.assert_has_calls([
            call(rid='cloud-compute:15', unit='cmp/0'),
            call(rid='cloud-compute:15', unit='cmp/1'),
            call(rid='cloud-compute:16', unit='cmp2/0'),
            call(rid='cloud-compute:16', unit='cmp2/1'),
        ])

    @patch('hooks.nova_cc_hooks._goal_state_achieved_for_relid')
    @patch('hooks.nova_cc_hooks.notify_ssh_keys_to_compute_units')
    def test_update_compute_units_with_ssh_key_change_upgrade_charm(
            self,
            mock_notify_ssh_keys_to_compute_units,
            mock__goal_state_achieved_for_relid):

        self.relation_ids.return_value = [
            'cloud-compute:15', 'cloud-compute:16']
        mock__goal_state_achieved_for_relid.side_effect = [True, True]

        hooks.update_compute_units_with_ssh_key_change(
            rid='cloud-compute:X', unit='cmp/X')

        mock__goal_state_achieved_for_relid.assert_has_calls([
            call('cloud-compute', 'cloud-compute:15'),
            call('cloud-compute', 'cloud-compute:16'),
        ])

        mock_notify_ssh_keys_to_compute_units.assert_called_once_with(
            rid='cloud-compute:X', unit='cmp/X')

    @patch('hooks.nova_cc_utils.is_cellv2_init_ready')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch('hooks.nova_cc_utils.add_hosts_to_cell')
    def test_add_hosts_to_cell_when_ready_leader(self,
                                                 mock_add_hosts_to_cell,
                                                 mock_is_db_initialised,
                                                 mock_is_cellv2_init_ready):
        self.is_leader.return_value = True
        mock_is_db_initialised.return_value = True
        mock_is_cellv2_init_ready.return_value = True
        hooks.add_hosts_to_cell_when_ready()
        self.is_leader.assert_called()
        mock_is_db_initialised.assert_called()
        mock_is_cellv2_init_ready.assert_called()
        self.is_db_maintenance_mode.assert_called()
        mock_add_hosts_to_cell.assert_called()

    @patch('hooks.nova_cc_utils.is_cellv2_init_ready')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch('hooks.nova_cc_utils.add_hosts_to_cell')
    def test_add_hosts_to_cell_when_ready_nonleader(self,
                                                    mock_add_hosts_to_cell,
                                                    mock_is_db_initialised,
                                                    mock_is_cellv2_init_ready):
        self.is_leader.return_value = False
        mock_is_db_initialised.return_value = True
        mock_is_cellv2_init_ready.return_value = True
        hooks.add_hosts_to_cell_when_ready()
        self.is_leader.assert_called()
        mock_is_db_initialised.assert_not_called()
        mock_is_cellv2_init_ready.assert_not_called()
        self.is_db_maintenance_mode.assert_not_called()
        mock_add_hosts_to_cell.assert_not_called()

    @patch('hooks.nova_cc_utils.is_cellv2_init_ready')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch('hooks.nova_cc_utils.add_hosts_to_cell')
    def test_add_hosts_to_cell_when_database_maintenance(
            self, mock_add_hosts_to_cell, mock_is_db_initialised,
            mock_is_cellv2_init_ready):
        self.is_leader.return_value = True
        mock_is_db_initialised.return_value = True
        mock_is_cellv2_init_ready.return_value = True
        self.is_db_maintenance_mode.return_value = True
        hooks.add_hosts_to_cell_when_ready()
        self.is_leader.assert_called()
        mock_is_db_initialised.assert_called()
        mock_is_cellv2_init_ready.assert_called()
        self.is_db_maintenance_mode.assert_called()
        mock_add_hosts_to_cell.assert_not_called()

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    @patch.object(hooks, '_auth_config')
    def test_compute_joined_neutron(self, auth_config, _canonical_url):
        self.is_relation_made.return_value = False
        self.network_manager.return_value = 'neutron'
        self.is_leader = True
        self.get_ca_cert_b64.return_value = 'foocert64'
        self.unit_get.return_value = 'nova-cc-host1'
        self.serial_console_settings.return_value = {
            'enable_serial_console': 'false',
            'serial_console_base_url': 'ws://controller:6803',
        }
        _canonical_url.return_value = 'http://nova-cc-host1'
        auth_config.return_value = FAKE_KS_AUTH_CFG
        hooks.compute_joined()

        self.relation_set.assert_called_with(
            relation_id=None,
            console_access_protocol=None,
            ca_cert='foocert64',
            region='RegionOne',
            cross_az_attach=True,
            volume_service='cinder',
            ec2_host='nova-cc-host1',
            network_manager='neutron',
            enable_serial_console='false',
            serial_console_base_url='ws://controller:6803',
            **FAKE_KS_AUTH_CFG)

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    @patch('hooks.nova_cc_context.NeutronAPIContext')
    @patch.object(hooks, '_auth_config')
    def test_compute_joined_neutron_api_rel(self, auth_config, napi,
                                            _canonical_url):
        def mock_NeutronAPIContext():
            return {
                'neutron_plugin': 'bob',
                'neutron_security_groups': 'yes',
                'neutron_url': 'http://nova-cc-host1:9696',
                'dns_domain': 'example.tld',
            }

        napi.return_value = mock_NeutronAPIContext
        self.is_relation_made.return_value = True
        self.network_manager.return_value = 'neutron'
        self.is_leader = True
        self.get_ca_cert_b64.return_value = 'foocert64'
        self.unit_get.return_value = 'nova-cc-host1'
        self.serial_console_settings.return_value = {
            'enable_serial_console': 'false',
            'serial_console_base_url': 'ws://controller:6803',
        }
        _canonical_url.return_value = 'http://nova-cc-host1'
        auth_config.return_value = FAKE_KS_AUTH_CFG
        hooks.compute_joined()
        self.relation_set.assert_called_with(
            relation_id=None,
            console_access_protocol=None,
            quantum_url='http://nova-cc-host1:9696',
            ca_cert='foocert64',
            quantum_port=9696,
            quantum_host='nova-cc-host1',
            quantum_security_groups='yes',
            region='RegionOne',
            cross_az_attach=True,
            volume_service='cinder',
            ec2_host='nova-cc-host1',
            quantum_plugin='bob',
            network_manager='neutron',
            enable_serial_console='false',
            serial_console_base_url='ws://controller:6803',
            dns_domain='example.tld',
            **FAKE_KS_AUTH_CFG)

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    @patch.object(hooks, '_auth_config')
    def test_nova_vmware_joined(self, auth_config, _canonical_url):
        auth_config.return_value = FAKE_KS_AUTH_CFG
        self.is_relation_made.return_value = False
        self.network_manager.return_value = 'neutron'
        _canonical_url.return_value = 'http://nova-cc-host1'
        hooks.nova_vmware_relation_joined()
        self.relation_set.assert_called_with(
            network_manager='neutron',
            relation_id=None,
            **FAKE_KS_AUTH_CFG)

    def test_db_joined(self):
        self.get_relation_ip.return_value = '10.10.10.10'
        self.is_relation_made.return_value = False
        self.os_release.return_value = 'diablo'
        hooks.db_joined()
        self.relation_set.assert_called_with(nova_database='nova',
                                             nova_username='nova',
                                             nova_hostname='10.10.10.10',
                                             relation_id=None)
        self.get_relation_ip.assert_called_with('shared-db',
                                                cidr_network=None)

    def test_db_joined_spaces(self):
        self.get_relation_ip.return_value = '192.168.20.1'
        self.unit_get.return_value = 'nova.foohost.com'
        self.is_relation_made.return_value = False
        self.os_release.return_value = 'diablo'
        hooks.db_joined()
        self.relation_set.assert_called_with(nova_database='nova',
                                             nova_username='nova',
                                             nova_hostname='192.168.20.1',
                                             relation_id=None)

    def test_db_joined_mitaka(self):
        self.get_relation_ip.return_value = '10.10.10.10'
        self.os_release.return_value = 'mitaka'
        self.is_relation_made.return_value = False
        hooks.db_joined()
        self.relation_set.assert_has_calls([
            call(nova_database='nova',
                 nova_username='nova',
                 nova_hostname='10.10.10.10',
                 relation_id=None),
            call(novaapi_database='nova_api',
                 novaapi_username='nova',
                 novaapi_hostname='10.10.10.10',
                 relation_id=None),
        ])

        self.get_relation_ip.assert_called_with('shared-db',
                                                cidr_network=None)

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    @patch('charmhelpers.contrib.openstack.ip.is_clustered')
    def test_identity_joined(self, _is_clustered, mock_canonical_url):
        _is_clustered.return_value = False
        mock_canonical_url.side_effect = [
            'http://ncc.example.com',
            'http://127.0.0.1',
            'http://127.0.0.2',
        ]
        self.test_config.set('os-public-hostname', 'ncc.example.com')
        hooks.identity_joined()
        mock_canonical_url.assert_has_calls([
            call(hooks.CONFIGS, hooks.ch_ip.PUBLIC),
            call(hooks.CONFIGS, hooks.ch_ip.INTERNAL),
            call(hooks.CONFIGS, hooks.ch_ip.ADMIN)])
        self.determine_endpoints.assert_called_with(
            'http://ncc.example.com',
            'http://127.0.0.1',
            'http://127.0.0.2'
        )

    def test_identity_joined_partial_cluster(self):
        self.is_clustered.return_value = False
        self.test_config.set('vip', '10.0.0.10')
        hooks.identity_joined()
        self.relation_set.assert_not_called()

    @patch.object(utils, 'resource_map')
    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_missing_relation_data(
            self, configs, mock_resource_map):
        mock_resource_map.return_value = {}
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = []
        hooks.db_changed()
        self.log.assert_called_with(
            'shared-db relation incomplete. Peer not ready?'
        )

    def _shared_db_test(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['shared-db']
        configs.write = MagicMock()
        hooks.db_changed()

    @patch.object(utils, 'resource_map')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch.object(hooks, 'CONFIGS')
    def test_db_changed(self, configs,
                        mock_is_db_initialised, mock_resource_map):
        mock_is_db_initialised.return_value = False
        mock_resource_map.return_value = {}
        'No database migration is attempted when ACL list is not present'
        self.os_release.return_value = 'diablo'
        self._shared_db_test(configs)
        configs.write_all.assert_called()
        self.migrate_nova_databases.assert_not_called()

    @patch.object(utils, 'resource_map')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_allowed(self, configs, mock_is_db_initialised,
                                mock_resource_map):
        mock_is_db_initialised.return_value = False
        mock_resource_map.return_value = {}
        allowed_units = 'nova-cloud-controller/0 nova-cloud-controller/3'
        self.test_relation.set({
            'nova_allowed_units': allowed_units,
        })
        self.local_unit.return_value = 'nova-cloud-controller/3'
        self.os_release.return_value = 'diablo'
        self.is_leader.return_value = True
        self._shared_db_test(configs)
        configs.write_all.assert_called()
        self.migrate_nova_databases.assert_called_with()

    @patch.object(utils, 'resource_map')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_not_allowed(self, configs, mock_is_db_initialised,
                                    mock_resource_map):
        mock_is_db_initialised.return_value = False
        mock_resource_map.return_value = {}
        allowed_units = 'nova-cloud-controller/0 nova-cloud-controller/3'
        self.test_relation.set({
            'nova_allowed_units': allowed_units,
        })
        self.local_unit.return_value = 'nova-cloud-controller/1'
        self.os_release.return_value = 'diablo'
        self._shared_db_test(configs)
        configs.write_all.assert_called()
        self.migrate_nova_databases.assert_not_called()

    @patch.object(utils, 'resource_map')
    @patch.object(hooks, 'quantum_joined')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch.object(hooks, 'compute_joined')
    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_remote_restarts(self, configs, comp_joined,
                                        mock_is_db_initialised,
                                        quantum_joined,
                                        mock_resource_map):
        mock_is_db_initialised.return_value = False
        mock_resource_map.return_value = {}

        def _relation_ids(rel):
            relid = {
                'cloud-compute': ['nova-compute/0'],
                'nova-cell-api': ['nova-cell-controller/0'],
                'neutron-api': ['neutron-api/0'],
                'quantum-network-service': ['neutron-gateway/0'],
                'neutron-plugin-remote': [],
            }
            return relid[rel]
        self.relation_ids.side_effect = _relation_ids
        allowed_units = 'nova-cloud-controller/0'
        self.test_relation.set({
            'nova_allowed_units': allowed_units,
        })
        self.local_unit.return_value = 'nova-cloud-controller/0'
        self.os_release.return_value = 'diablo'
        self.is_leader.return_value = True
        self._shared_db_test(configs)
        comp_joined.assert_called_with(remote_restart=True,
                                       rid='nova-compute/0')
        quantum_joined.assert_called_with(remote_restart=True,
                                          rid='neutron-gateway/0')
        self.migrate_nova_databases.assert_called_with()

    @patch.object(hooks, 'CONFIGS')
    def test_amqp_relation_broken(self, configs):
        configs.write = MagicMock()
        self.relation_ids.return_value = ['nova-cell-api/0']
        hooks.relation_broken()
        configs.write_all.assert_called()

    @patch.object(hooks, 'update_child_cell_records')
    @patch.object(utils, 'resource_map')
    @patch.object(hooks, 'leader_init_db_if_ready_allowed_units')
    @patch.object(hooks, 'update_cell_db_if_ready_allowed_units')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch.object(hooks, 'update_nova_relation')
    @patch.object(hooks, 'CONFIGS')
    def test_amqp_changed_api_rel(self, configs,
                                  update_nova_relation, mock_is_db_initialised,
                                  update_db_allowed, init_db_allowed,
                                  mock_resource_map,
                                  mock_update_child_cell_records):
        mock_resource_map.return_value = {}
        self.relation_ids.side_effect = [
            ['quantum-service/0'],
        ]
        mock_is_db_initialised.return_value = False
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['amqp']
        configs.write = MagicMock()
        self.os_release.return_value = 'diablo'
        self.is_relation_made.return_value = True
        hooks.amqp_changed()
        self.assertEqual(configs.write.call_args_list,
                         [call('/etc/nova/nova.conf')])
        update_nova_relation.assert_called_with(remote_restart=True)

    @patch.object(hooks, 'update_child_cell_records')
    @patch.object(hooks, 'leader_init_db_if_ready_allowed_units')
    @patch.object(hooks, 'update_cell_db_if_ready_allowed_units')
    @patch.object(utils, 'resource_map')
    @patch('hooks.nova_cc_utils.is_db_initialised')
    @patch.object(hooks, 'update_nova_relation')
    @patch.object(hooks, 'CONFIGS')
    def test_amqp_changed_noapi_rel(self,
                                    configs,
                                    update_nova_relation,
                                    mock_is_db_initialised,
                                    mock_resource_map,
                                    update_db_allowed,
                                    init_db_allowed,
                                    mock_update_child_cell_records):
        mock_resource_map.return_value = {}
        mock_is_db_initialised.return_value = False
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['amqp']
        configs.write = MagicMock()
        self.is_relation_made.return_value = False
        self.network_manager.return_value = 'neutron'
        self.os_release.return_value = 'diablo'
        hooks.amqp_changed()
        self.assertEqual(configs.write.call_args_list,
                         [call('/etc/nova/nova.conf')])
        update_nova_relation.assert_called_with(remote_restart=True)

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    @patch.object(os, 'rename')
    @patch.object(os.path, 'isfile')
    @patch.object(hooks, 'CONFIGS')
    def test_neutron_api_relation_joined(self, configs, isfile,
                                         rename, _canonical_url):
        nova_url = 'http://novaurl:8774/v2'
        isfile.return_value = True
        _identity_joined = self.patch('identity_joined')
        self.relation_ids.return_value = ['relid']
        _canonical_url.return_value = 'http://novaurl'
        self.uuid.uuid4.return_value = 'bob'
        hooks.neutron_api_relation_joined(remote_restart=True)
        _identity_joined.assert_called()
        self.relation_set.assert_called_with(relation_id=None,
                                             nova_url=nova_url,
                                             restart_trigger='bob')

    @patch('hooks.nova_cc_utils.resource_map')
    @patch.object(hooks, 'CONFIGS')
    def test_neutron_api_relation_changed(self, configs, mock_resource_map):
        mock_resource_map.return_value = {}
        self.relation_ids.side_effect = lambda name: (
            [] if name == 'neutron-plugin-remote' else ['relid'])
        _compute_joined = self.patch('compute_joined')
        _quantum_joined = self.patch('quantum_joined')
        hooks.neutron_api_relation_changed()
        configs.write.assert_called_with('/etc/nova/nova.conf')
        _compute_joined.assert_called()
        _quantum_joined.assert_called()

    @patch.object(utils, 'resource_map')
    @patch.object(os, 'remove')
    @patch.object(os.path, 'isfile')
    @patch.object(hooks, 'CONFIGS')
    def test_neutron_api_relation_broken(self, configs, isfile, remove,
                                         mock_resource_map):
        mock_resource_map.return_value = {}
        isfile.return_value = True
        self.relation_ids.side_effect = lambda name: (
            [] if name == 'neutron-plugin-remote' else ['relid'])
        _compute_joined = self.patch('compute_joined')
        _quantum_joined = self.patch('quantum_joined')
        hooks.neutron_api_relation_broken()
        configs.write_all.assert_called()
        _compute_joined.assert_called()
        _quantum_joined.assert_called()

    @patch.object(utils, 'resource_map')
    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    def test_console_settings_vnc(self, _canonical_url, mock_resource_map):
        self.test_config.set('console-access-protocol', 'vnc')
        self.os_release.return_value = 'kilo'
        mock_resource_map.return_value = {}
        _cc_host = "nova-cc-host1"
        _canonical_url.return_value = 'http://' + _cc_host
        hooks.resolve_CONFIGS()
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_proxy_novnc_address': 'http://%s:6080/vnc_auto.html' %
                                           (_cc_host),
            'console_proxy_novnc_port': 6080,
            'console_access_protocol': 'vnc',
            'console_proxy_novnc_host': _cc_host,
            'console_proxy_xvpvnc_port': 6081,
            'console_proxy_xvpvnc_host': _cc_host,
            'console_proxy_xvpvnc_address': 'http://%s:6081/console' %
                                            (_cc_host),
            'console_keymap': 'en-us',
            'spice_agent_enabled': True,
        }
        self.assertEqual(_con_sets, console_settings)

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    def test_console_settings_xvpvnc(self, _canonical_url):
        self.test_config.set('console-access-protocol', 'xvpvnc')
        _cc_host = "nova-cc-host1"
        _canonical_url.return_value = 'http://' + _cc_host
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_access_protocol': 'xvpvnc',
            'console_keymap': 'en-us',
            'console_proxy_xvpvnc_port': 6081,
            'console_proxy_xvpvnc_host': _cc_host,
            'console_proxy_xvpvnc_address': 'http://%s:6081/console' %
                                            (_cc_host),
            'spice_agent_enabled': True,
        }
        self.assertEqual(_con_sets, console_settings)

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    def test_console_settings_novnc(self, _canonical_url):
        self.test_config.set('console-access-protocol', 'novnc')
        _cc_host = "nova-cc-host1"
        _canonical_url.return_value = 'http://' + _cc_host
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_proxy_novnc_address': 'http://%s:6080/vnc_auto.html' %
                                           (_cc_host),
            'console_proxy_novnc_port': 6080,
            'console_access_protocol': 'novnc',
            'console_proxy_novnc_host': _cc_host,
            'console_keymap': 'en-us',
            'spice_agent_enabled': True,
        }
        self.assertEqual(_con_sets, console_settings)

    @patch('charmhelpers.contrib.openstack.ip.canonical_url')
    def test_console_settings_spice(self, _canonical_url):
        self.test_config.set('console-access-protocol', 'spice')
        _cc_host = "nova-cc-host1"
        _canonical_url.return_value = 'http://' + _cc_host
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_proxy_spice_address': 'http://%s:6082/spice_auto.html' %
                                           (_cc_host),
            'console_proxy_spice_host': _cc_host,
            'console_proxy_spice_port': 6082,
            'console_access_protocol': 'spice',
            'console_keymap': 'en-us',
            'spice_agent_enabled': True,
        }
        self.assertEqual(_con_sets, console_settings)

    def test_console_settings_none(self):
        self.test_config.set('console-access-protocol', '')
        self.assertEqual(
            hooks.console_settings(),
            {'console_access_protocol': None})

    @patch('charmhelpers.contrib.hahelpers.cluster.https')
    def test_console_settings_explicit_ip(self, _https):
        self.test_config.set('console-access-protocol', 'spice')
        _https.return_value = False
        _cc_public_host = "public-host"
        self.test_config.set('console-proxy-ip', _cc_public_host)
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_proxy_spice_address': 'http://%s:6082/spice_auto.html' %
                                           (_cc_public_host),
            'console_proxy_spice_host': _cc_public_host,
            'console_proxy_spice_port': 6082,
            'console_access_protocol': 'spice',
            'console_keymap': 'en-us',
            'spice_agent_enabled': True,
        }
        self.assertEqual(_con_sets, console_settings)

    @patch('charmhelpers.contrib.hahelpers.cluster.https')
    def test_console_settings_explicit_ip_with_https(self, _https):
        self.test_config.set('console-access-protocol', 'spice')
        _https.return_value = True
        _cc_public_host = "public-host"
        self.test_config.set('console-proxy-ip', _cc_public_host)
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_proxy_spice_address': 'https://%s:6082/spice_auto.html' %
                                           (_cc_public_host),
            'console_proxy_spice_host': _cc_public_host,
            'console_proxy_spice_port': 6082,
            'console_access_protocol': 'spice',
            'console_keymap': 'en-us',
            'spice_agent_enabled': True,
        }
        self.assertEqual(_con_sets, console_settings)

    def test_ha_relation_joined(self):
        self.test_config.set('dns-ha', False)
        self.generate_ha_relation_data.return_value = {'ha': 'settings'}
        hooks.ha_joined()
        self.generate_ha_relation_data.assert_called_once_with(
            'nova',
            extra_settings={'delete_resources': ['vip_consoleauth',
                                                 'res_nova_consoleauth']})
        self.relation_set.assert_called_once_with(
            ha='settings',
            relation_id=None)

    def test_ha_relation_joined_dnsha(self):
        self.test_config.set('console-access-protocol', 'novnc')
        self.test_config.set('dns-ha', True)
        self.generate_ha_relation_data.return_value = {'ha': 'settings'}
        hooks.ha_joined()
        self.generate_ha_relation_data.assert_called_once_with(
            'nova',
            extra_settings={'delete_resources': ['vip_consoleauth',
                                                 'res_nova_consoleauth']})
        self.relation_set.assert_called_once_with(
            ha='settings',
            relation_id=None)

    @patch('charmhelpers.contrib.openstack.context.relation_ids')
    def test_ha_relation_changed_not_clustered(self, ctxt_relation_ids):
        self.relation_get.return_value = ''
        self.os_release.return_value = 'ussuri'
        ctxt_relation_ids.return_value = []
        hooks.resolve_CONFIGS()
        with patch.object(hooks.CONFIGS, 'write') as configs_write:
            hooks.ha_changed()
            configs_write.assert_not_called()

    @patch.object(hooks, 'update_nova_relation')
    @patch.object(hooks, 'identity_joined')
    @patch('charmhelpers.contrib.openstack.context.relation_get')
    @patch('charmhelpers.contrib.openstack.context.related_units')
    @patch('charmhelpers.contrib.openstack.context.relation_ids')
    def test_ha_relation_changed_clustered(self, ctxt_relation_ids,
                                           ctxt_related_units,
                                           ctxt_relation_get,
                                           identity_joined,
                                           update_nova_relation):
        ctxt_relation_get.return_value = None
        self.test_relation.set({'clustered': True})
        self.os_release.return_value = 'ussuri'
        self.relation_ids.return_value = ['identity-service:1']
        ctxt_related_units.return_value = ['keystone/0']
        hooks.resolve_CONFIGS()
        with patch.object(hooks.CONFIGS, 'write') as configs_write:
            hooks.ha_changed()
            configs_write.assert_called_with(utils.NOVA_CONF)
            identity_joined.assert_called_with(rid='identity-service:1')
            update_nova_relation.assert_called_with()

    @patch('hooks.nova_cc_utils.disable_deprecated_nova_placement_apache_site')
    def test_placement_joined(self, disable_nova_placement):
        hooks.placement_relation_joined()
        disable_nova_placement.assert_called()
        self.relation_set.assert_called_with(nova_placement_disabled=True,
                                             relation_id=None)

    @patch.object(hooks, 'compute_joined')
    @patch.object(hooks, 'identity_joined')
    @patch.object(hooks, 'CONFIGS')
    def test_placement_changed(self, configs, identity_joined, compute_joined):
        self.test_relation.set({
            'placement_enabled': True,
        })
        self.services.return_value = ['dummy-service']
        self.relation_ids.return_value = ['generic_rid']
        hooks.placement_relation_changed()
        self.service_restart.assert_called()
        configs.write_all.assert_called()
        identity_joined.assert_called()
        compute_joined.assert_called()

    @patch.object(hooks, 'memcached_common')
    def test_memcache_joined(self, _memcached_common):
        self.get_relation_ip.return_value = 'foo'
        hooks.memcached_joined()
        self.get_relation_ip.assert_called_once_with('memcache')
        self.relation_set.assert_called_once_with(
            relation_id=None,
            relation_settings={'private-address': 'foo'})
        hooks.memcached_joined()

    @patch.object(utils, 'resource_map')
    @patch.object(hooks, 'quantum_joined')
    @patch.object(hooks, 'compute_joined')
    @patch.object(hooks, 'configure_https')
    @patch.object(hooks.cert_utils, 'process_certificates')
    def test_certs_changed(self, process_certificates, configure_https,
                           compute_joined, quantum_joined, resource_map):
        resource_map.return_value = {}
        self.os_release.return_value = 'rocky'
        self.relation_ids.side_effect = lambda name: {
            'neutron-plugin-remote': [],
            'cloud-compute': ['relid1'],
            'quantum-network-service': ['relid2'],
        }[name]
        hooks.certs_changed()
        process_certificates.assert_called_once_with('nova', None, None,
                                                     group='nova')
        configure_https.assert_called_once_with()
        compute_joined.assert_called_once_with(remote_restart=False,
                                               rid='relid1')
        quantum_joined.assert_called_once_with(remote_restart=False,
                                               rid='relid2')

    @patch.object(hooks.ch_host, 'service_restart')
    @patch.object(hooks.ch_utils, 'save_endpoint_changed_triggers')
    @patch.object(utils, 'resource_map')
    @patch.object(hooks, 'configure_https')
    @patch.object(hooks, 'compute_joined')
    @patch.object(hooks, 'nova_vmware_relation_joined')
    @patch.object(hooks, 'neutron_api_relation_joined')
    @patch.object(hooks.ch_utils, 'endpoint_changed')
    @patch.object(hooks.time, 'sleep')
    @patch.object(hooks, 'update_nova_relation')
    @patch.object(hooks, 'CONFIGS')
    def test_identity_changed(self, configs, update_nova_relation, sleep,
                              endpoint_changed, neutron_api_relation_joined,
                              nova_vmware_relation_joined,
                              compute_joined, configure_https, resource_map,
                              save_endpoint_changed_triggers, service_restart):
        configs.complete_contexts.return_value = ['identity-service']
        endpoint_changed.return_value = True

        relations = {
            'cloud-compute': {
                'ridcomp7': {},
                'ridcomp9': {}},
            'nova-vmware': {
                'ridvmware1': {},
                'ridvmware2': {}},
            'neutron-api': {
                'ridnapi1': {},
                'ridnapi3': {}},
            'identity-service': {
                'ridnid2': {
                    'ks/1': {'catalog_ttl': '2'},
                    'ks/3': {}},
                'ridnid5': {
                    'rks/1': {'catalog_ttl': '2'},
                    'rks/3': {'catalog_ttl': '73'}}}}

        def _relation_ids(rel_name):
            return relations[rel_name].keys()

        def _rid_data(relid):
            for rel_name in relations.keys():
                if relid in relations[rel_name].keys():
                    return relations[rel_name][relid]
            return []

        def _related_units(relid):
            return _rid_data(relid).keys()

        def _relation_get(rid, unit, attribute):
            return _rid_data(rid)[unit].get(attribute)

        self.relation_ids.side_effect = _relation_ids
        self.related_units.side_effect = _related_units
        self.relation_get.side_effect = _relation_get

        hooks.identity_changed()
        nova_vmware_relation_joined.assert_has_calls([
            call('ridvmware1'), call('ridvmware2')])
        neutron_api_relation_joined.assert_has_calls([
            call('ridnapi1'), call('ridnapi3')])
        configure_https.assert_called_once_with()
        sleep.assert_called_once_with(73)
        service_restart.assert_has_calls([
            call('nova-scheduler'), call('nova-conductor')])
        save_endpoint_changed_triggers.assert_called_once_with(['placement'])
        compute_joined.assert_has_calls([
            call(rid='ridcomp7', remote_restart=True),
            call(rid='ridcomp9', remote_restart=True)], any_order=True)

    @patch('charmhelpers.contrib.charmsupport.nrpe.NRPE.remove_check')
    @patch('charmhelpers.contrib.charmsupport.nrpe.copy_nrpe_checks')
    @patch('charmhelpers.contrib.charmsupport.nrpe.config')
    @patch('charmhelpers.contrib.charmsupport.nrpe.relation_ids')
    @patch('charmhelpers.contrib.charmsupport.nrpe.local_unit')
    def test_update_nrpe_config(self,
                                mock_local_unit,
                                mock_relation_ids,
                                mock_config,
                                mock_copy_nrpe_checks,
                                mock_remove_check):
        self.os_release.return_value = 'train'
        self.config.side_effect = self.test_config
        mock_config.return_value = self.test_config

        hooks.update_nrpe_config()
        mock_remove_check.assert_called_with(shortname='nova-consoleauth')
