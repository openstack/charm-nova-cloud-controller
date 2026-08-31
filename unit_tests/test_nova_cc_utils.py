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

from collections import OrderedDict
import subprocess
import charmhelpers.core.unitdata
import charmhelpers.contrib.openstack.templating as os_templating
from unittest.mock import patch, MagicMock, call

from unit_tests.test_utils import (
    CharmTestCase,
    patch_open,
)

import hooks.nova_cc_utils as utils


TO_PATCH = [
    'charmhelpers.contrib.openstack.ip.canonical_url',
    'charmhelpers.contrib.openstack.utils.configure_installation_source',
    'charmhelpers.contrib.openstack.utils.enable_memcache',
    'charmhelpers.contrib.openstack.utils.get_os_codename_install_source',
    'charmhelpers.contrib.openstack.utils.is_unit_paused_set',
    'charmhelpers.contrib.openstack.utils.os_application_version_set',
    'charmhelpers.contrib.openstack.utils.os_release',
    'charmhelpers.contrib.openstack.utils.save_script_rc',
    'charmhelpers.contrib.openstack.utils.token_cache_pkgs',
    'charmhelpers.contrib.peerstorage.peer_store',
    'charmhelpers.core.hookenv.config',
    'charmhelpers.core.hookenv.is_leader',
    'charmhelpers.core.hookenv.leader_get',
    'charmhelpers.core.hookenv.leader_set',
    'charmhelpers.core.hookenv.local_unit',
    'charmhelpers.core.hookenv.log',
    'charmhelpers.core.hookenv.related_units',
    'charmhelpers.core.hookenv.relation_get',
    'charmhelpers.core.hookenv.relation_ids',
    'charmhelpers.core.hookenv.remote_unit',
    'charmhelpers.core.hookenv.status_set',
    'charmhelpers.core.host.lsb_release',
    'charmhelpers.core.host.service_pause',
    'charmhelpers.core.host.service_restart',
    'charmhelpers.core.host.service_resume',
    'charmhelpers.core.host.service_running',
    'charmhelpers.core.host.service_start',
    'charmhelpers.core.host.service_stop',
    'charmhelpers.fetch.apt_autoremove',
    'charmhelpers.fetch.apt_install',
    'charmhelpers.fetch.apt_purge',
    'charmhelpers.fetch.apt_update',
    'charmhelpers.fetch.apt_upgrade',
    'disable_policy_rcd',
    'enable_policy_rcd',
    'hooks.nova_cc_utils.register_configs',
    'hooks.nova_cc_utils.services',
    'uuid.uuid1',
]

SCRIPTRC_ENV_VARS = {
    'OPENSTACK_PORT_MCASTPORT': 5404,
    'OPENSTACK_SERVICE_API_EC2': 'nova-api-ec2',
    'OPENSTACK_SERVICE_API_OS_COMPUTE': 'nova-api-os-compute',
    'OPENSTACK_SERVICE_CERT': 'nova-cert',
    'OPENSTACK_SERVICE_CONDUCTOR': 'nova-conductor',
    'OPENSTACK_SERVICE_OBJECTSTORE': 'nova-objectstore',
    'OPENSTACK_SERVICE_SCHEDULER': 'nova-scheduler',
}


AUTHORIZED_KEYS = """
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC27Us7lSjCpa7bumXAgc nova-compute-1
ssh-rsa BBBBB3NzaC1yc2EBBBBDBQBBBBBBBQC27Us7lSjCpa7bumXBgc nova-compute-2
ssh-rsa CCCCB3NzaC1yc2ECCCCDCQCBCCCBCQC27Us7lSjCpa7bumXCgc nova-compute-3
"""

BASE_ENDPOINTS = {
    'ec2_admin_url': 'http://foohost.com:8773/services/Cloud',
    'ec2_internal_url': 'http://foohost.com:8773/services/Cloud',
    'ec2_public_url': 'http://foohost.com:8773/services/Cloud',
    'ec2_region': 'RegionOne',
    'ec2_service': 'ec2',
    'nova_admin_url': 'http://foohost.com:8774/v2/$(tenant_id)s',
    'nova_internal_url': 'http://foohost.com:8774/v2/$(tenant_id)s',
    'nova_public_url': 'http://foohost.com:8774/v2/$(tenant_id)s',
    'nova_region': 'RegionOne',
    'nova_service': 'nova',
    's3_admin_url': 'http://foohost.com:3333',
    's3_internal_url': 'http://foohost.com:3333',
    's3_public_url': 'http://foohost.com:3333',
    's3_region': 'RegionOne',
    's3_service': 's3',
    'placement_region': None,
    'placement_service': None,
    'placement_admin_url': None,
    'placement_internal_url': None,
    'placement_public_url': None,
}

QUEENS_ENDPOINTS = {
    'ec2_admin_url': None,
    'ec2_internal_url': None,
    'ec2_public_url': None,
    'ec2_region': None,
    'ec2_service': None,
    'nova_admin_url': 'http://foohost.com:8774/v2.1',
    'nova_internal_url': 'http://foohost.com:8774/v2.1',
    'nova_public_url': 'http://foohost.com:8774/v2.1',
    'nova_region': 'RegionOne',
    'nova_service': 'nova',
    's3_admin_url': None,
    's3_internal_url': None,
    's3_public_url': None,
    's3_region': None,
    's3_service': None,
    'placement_region': 'RegionOne',
    'placement_service': 'placement',
    'placement_admin_url': 'http://foohost.com:8778',
    'placement_internal_url': 'http://foohost.com:8778',
    'placement_public_url': 'http://foohost.com:8778',
}

TRAIN_ENDPOINTS = {
    'ec2_admin_url': None,
    'ec2_internal_url': None,
    'ec2_public_url': None,
    'ec2_region': None,
    'ec2_service': None,
    'nova_admin_url': 'http://foohost.com:8774/v2.1',
    'nova_internal_url': 'http://foohost.com:8774/v2.1',
    'nova_public_url': 'http://foohost.com:8774/v2.1',
    'nova_region': 'RegionOne',
    'nova_service': 'nova',
    's3_admin_url': None,
    's3_internal_url': None,
    's3_public_url': None,
    's3_region': None,
    's3_service': None,
    'placement_region': None,
    'placement_service': None,
    'placement_admin_url': None,
    'placement_internal_url': None,
    'placement_public_url': None,
}

# Restart map should be constructed such that API services restart
# before frontends (haproxy/apache) to avoid port conflicts.
RESTART_MAP_ICEHOUSE = OrderedDict([
    ('/etc/nova/nova.conf', [
        'nova-api-ec2', 'nova-api-os-compute', 'nova-objectstore',
        'nova-cert', 'nova-scheduler', 'nova-conductor'
    ]),
    ('/etc/nova/api-paste.ini', [
        'nova-api-ec2', 'nova-api-os-compute'
    ]),
    ('/etc/haproxy/haproxy.cfg', ['haproxy']),
    ('/etc/apache2/sites-available/openstack_https_frontend', ['apache2']),
    ('/etc/apache2/ports.conf', ['apache2']),
])
RESTART_MAP_OCATA_ACTUAL = OrderedDict([
    ('/etc/nova/nova.conf', [
        'nova-api-os-compute', 'nova-scheduler', 'nova-conductor', 'apache2',
    ]),
    ('/etc/nova/api-paste.ini', ['nova-api-os-compute', 'apache2']),
    ('/etc/haproxy/haproxy.cfg', ['haproxy']),
    ('/etc/apache2/sites-available/openstack_https_frontend', ['apache2']),
    ('/etc/apache2/ports.conf', ['apache2']),
    ('/etc/apache2/sites-enabled/wsgi-placement-api.conf', ['apache2']),
])
RESTART_MAP_OCATA_BASE = OrderedDict([
    ('/etc/nova/nova.conf', [
        'nova-api-os-compute', 'nova-placement-api',
        'nova-scheduler', 'nova-conductor'
    ]),
    ('/etc/nova/api-paste.ini', [
        'nova-api-os-compute', 'nova-placement-api'
    ]),
    ('/etc/haproxy/haproxy.cfg', ['haproxy']),
    ('/etc/apache2/sites-available/openstack_https_frontend', ['apache2']),
    ('/etc/apache2/ports.conf', ['apache2']),
])
RESTART_MAP_ROCKY_ACTUAL = OrderedDict([
    ('/etc/nova/nova.conf', [
        'nova-scheduler', 'nova-conductor', 'apache2',
    ]),
    ('/etc/nova/api-paste.ini', ['apache2']),
    ('/etc/haproxy/haproxy.cfg', ['haproxy']),
    ('/etc/apache2/sites-available/openstack_https_frontend', ['apache2']),
    ('/etc/apache2/ports.conf', ['apache2']),
    ('/etc/apache2/sites-enabled/wsgi-api-os-compute.conf', ['apache2']),
    ('/etc/apache2/sites-enabled/wsgi-placement-api.conf', ['apache2']),
    ('/etc/apache2/sites-enabled/wsgi-openstack-metadata.conf', ['apache2']),
])


DPKG_OPTS = [
    '--option', 'Dpkg::Options::=--force-confnew',
    '--option', 'Dpkg::Options::=--force-confdef',
]

GPG_PPA_CLOUD_ARCHIVE = """-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: SKS 1.1.6
Comment: Hostname: keyserver.ubuntu.com

mI0EUCEyTAEEAMuUxyfiegCCwn4J/c0nw5PUTSJdn5FqiUTq6iMfij65xf1vl0g/Mxqw0gfg
AJIsCDvO9N9dloLAwF6FUBMg5My7WyhRPTAKF505TKJboyX3Pp4J1fU1LV8QFVOp87vUh1Rz
B6GU7cSglhnbL85gmbJTllkzkb3h4Yw7W+edjcQ/ABEBAAG0K0xhdW5jaHBhZCBQUEEgZm9y
IFVidW50dSBDbG91ZCBBcmNoaXZlIFRlYW2IuAQTAQIAIgUCUCEyTAIbAwYLCQgHAwIGFQgC
CQoLBBYCAwECHgECF4AACgkQimhEop9oEE7kJAP/eTBgq3Mhbvo0d8elMOuqZx3nmU7gSyPh
ep0zYIRZ5TJWl/7PRtvp0CJA6N6ZywYTQ/4ANHhpibcHZkh8K0AzUvsGXnJRSFoJeqyDbD91
EhoO+4ZfHs2HvRBQEDZILMa2OyuB497E5Mmyua3HDEOrG2cVLllsUZzpTFCx8NgeMHk=
=jLBm
-----END PGP PUBLIC KEY BLOCK-----
"""

# ppa:ubuntu-cloud-archive/newton-staging
OS_ORIGIN_NEWTON_STAGING = """deb http://ppa.launchpad.net/\
ubuntu-cloud-archive/newton-staging/ubuntu xenial main
|
%s
""" % GPG_PPA_CLOUD_ARCHIVE

# ppa:ubuntu-cloud-archive/liberty-staging
OS_ORIGIN_LIBERTY_STAGING = """deb http://ppa.launchpad.net/\
ubuntu-cloud-archive/liberty-staging/ubuntu trusty main
|
%s
""" % GPG_PPA_CLOUD_ARCHIVE

NM_CELLS_LIST = b"""
+-------+--------------------------------------+--------------+-------------+
| Name  | UUID                                 | Transport    | DB          |
+-------+--------------------------------------+--------------+-------------+
| cell0 | 00000000-0000-0000-0000-000000000000 | none:///     | mysql_cell0 |
| cell1 | 7a8a0e58-e127-4056-bb98-99d9579ca08b | rabbit_cell1 | mysql_cell1 |
+-------+--------------------------------------+--------------+-------------+
"""


class NovaCCUtilsTests(CharmTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        charmhelpers.core.unitdata._KV = (
            charmhelpers.core.unitdata.Storage(':memory:'))

    def setUp(self):
        super(NovaCCUtilsTests, self).setUp(utils, TO_PATCH)
        self.config.side_effect = self.test_config.get
        utils._BASE_RESOURCE_MAP = None  # reset this for each test
        self.maxDiff = None

    def test_nova_conf_template_release_selection(self):
        yoga_renderer = os_templating.OSConfigRenderer(
            templates_dir=utils.TEMPLATES, openstack_release='yoga')
        antelope_renderer = os_templating.OSConfigRenderer(
            templates_dir=utils.TEMPLATES, openstack_release='caracal')

        self.assertIn(
            'templates/yoga/nova.conf',
            yoga_renderer._get_template('nova.conf').filename)
        self.assertIn(
            'templates/antelope/nova.conf',
            antelope_renderer._get_template('nova.conf').filename)

    def test_resolve_services(self):
        # Icehouse with disable-aws-compat = True
        self.test_config.set('disable-aws-compat', True)
        self.os_release.return_value = "icehouse"
        _services = utils.resolve_services()
        for _service in utils.AWS_COMPAT_SERVICES:
            self.assertTrue(_service not in _services)

        # Icehouse with disable-aws-compat = False
        self.test_config.set('disable-aws-compat', False)
        self.os_release.return_value = "icehouse"
        _services = utils.resolve_services()
        for _service in utils.AWS_COMPAT_SERVICES:
            self.assertTrue(_service in _services)

        # Liberty
        self.os_release.return_value = "liberty"
        _services = utils.resolve_services()
        for _service in utils.AWS_COMPAT_SERVICES:
            self.assertTrue(_service not in _services)

        # Newton
        self.os_release.return_value = "newton"
        _services = utils.resolve_services()
        for _service in utils.AWS_COMPAT_SERVICES:
            self.assertTrue(_service not in _services)
        self.assertTrue('nova-cert' not in _services)

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_resource_map_vmware(self, subcontext):
        fake_context = MagicMock()
        fake_context.return_value = {
            'sections': [],
            'services': ['nova-compute', 'nova-network'],

        }
        subcontext.return_value = fake_context
        self.os_release.return_value = 'diablo'
        _map = utils.resource_map()
        for s in ['nova-compute', 'nova-network']:
            self.assertIn(s, _map['/etc/nova/nova.conf']['services'])

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_resource_map_neutron_no_agent_installed(self, subcontext):
        self.os_release.return_value = 'diablo'
        _map = utils.resource_map()
        services = []
        [services.extend(_map[c]['services'])for c in _map]
        for svc in services:
            self.assertNotIn('agent', svc)

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_resource_map_console_xvpvnc(self, subcontext):
        self.test_config.set('console-access-protocol', 'xvpvnc')
        self.os_release.return_value = 'diablo'
        self.relation_ids.return_value = []
        _map = utils.resource_map()
        console_services = ['nova-xvpvncproxy', 'nova-consoleauth']
        for service in console_services:
            self.assertIn(service, _map['/etc/nova/nova.conf']['services'])
        self.os_release.return_value = 'train'
        _map = utils.resource_map()
        self.assertNotIn(
            'nova-consoleauth',
            _map['/etc/nova/nova.conf']['services'])

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_resource_map_console_novnc(self, subcontext):
        self.test_config.set('console-access-protocol', 'novnc')
        self.relation_ids.return_value = []
        self.os_release.return_value = 'diablo'
        _map = utils.resource_map()
        console_services = ['nova-novncproxy', 'nova-consoleauth']
        for service in console_services:
            self.assertIn(service, _map['/etc/nova/nova.conf']['services'])
        self.os_release.return_value = 'train'
        _map = utils.resource_map()
        self.assertNotIn(
            'nova-consoleauth',
            _map['/etc/nova/nova.conf']['services'])

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_resource_map_console_vnc(self, subcontext):
        self.test_config.set('console-access-protocol', 'vnc')
        self.relation_ids.return_value = []
        self.os_release.return_value = 'diablo'
        _map = utils.resource_map()
        console_services = ['nova-novncproxy', 'nova-xvpvncproxy',
                            'nova-consoleauth']
        for service in console_services:
            self.assertIn(service, _map['/etc/nova/nova.conf']['services'])
        self.os_release.return_value = 'train'
        _map = utils.resource_map()
        self.assertNotIn(
            'nova-consoleauth',
            _map['/etc/nova/nova.conf']['services'])

    def test_console_attributes_none(self):
        self.test_config.set('console-access-protocol', 'None')
        _proto = utils.common.console_attributes('protocol')
        self.assertEqual(_proto, None)
        self.test_config.set('console-access-protocol', 'NONE')
        _proto = utils.common.console_attributes('protocol')
        self.assertEqual(_proto, None)
        self.test_config.set('console-access-protocol', 'none')
        _proto = utils.common.console_attributes('protocol')
        self.assertEqual(_proto, None)
        self.test_config.set('console-access-protocol', None)
        _proto = utils.common.console_attributes('protocol')
        self.assertEqual(_proto, None)
        self.test_config.set('console-access-protocol', "")
        _proto = utils.common.console_attributes('protocol')
        self.assertEqual(_proto, None)

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_resource_map_console_spice(self, subcontext):
        self.test_config.set('console-access-protocol', 'spice')
        self.os_release.return_value = 'diablo'
        self.relation_ids.return_value = []
        _map = utils.resource_map()
        console_services = ['nova-spiceproxy', 'nova-consoleauth']
        for service in console_services:
            self.assertIn(service, _map['/etc/nova/nova.conf']['services'])
        self.os_release.return_value = 'train'
        _map = utils.resource_map()
        self.assertNotIn(
            'nova-consoleauth',
            _map['/etc/nova/nova.conf']['services'])

    @patch('charmhelpers.contrib.openstack.neutron.os_release')
    @patch('os.path.exists')
    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_restart_map_api_before_frontends_icehouse(
            self, subcontext, _exists, _os_release):
        _os_release.return_value = 'icehouse'
        self.os_release.return_value = 'icehouse'
        _exists.return_value = False
        self.enable_memcache.return_value = False
        _map = utils.restart_map()
        self.assertIsInstance(_map, OrderedDict)
        self.assertEqual(_map, RESTART_MAP_ICEHOUSE)

    @patch('charmhelpers.core.hookenv.relation_ids')
    @patch('charmhelpers.contrib.openstack.neutron.os_release')
    @patch('os.path.exists')
    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_restart_map_api_actual_ocata(
            self, subcontext, _exists, _os_release, rids):
        _os_release.return_value = 'ocata'
        self.os_release.return_value = 'ocata'
        _exists.return_value = False
        self.enable_memcache.return_value = False
        rids.return_value = []
        _map = utils.restart_map()
        self.assertIsInstance(_map, OrderedDict)
        self.assertEqual(_map, RESTART_MAP_OCATA_ACTUAL)

    @patch('charmhelpers.core.hookenv.relation_ids')
    @patch('charmhelpers.contrib.openstack.neutron.os_release')
    @patch('os.path.exists')
    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_restart_map_api_actual_rocky(
            self, subcontext, _exists, _os_release, rids):
        _os_release.return_value = 'rocky'
        self.os_release.return_value = 'rocky'
        _exists.return_value = False
        self.enable_memcache.return_value = False
        rids.return_value = []
        _map = utils.restart_map()
        self.assertIsInstance(_map, OrderedDict)
        self.assertEqual(_map, RESTART_MAP_ROCKY_ACTUAL)

    @patch('charmhelpers.core.hookenv.relation_ids')
    @patch('charmhelpers.contrib.openstack.neutron.os_release')
    @patch('os.path.exists')
    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_restart_map_api_ocata_base(
            self, subcontext, _exists, _os_release, rids):
        _os_release.return_value = 'ocata'
        self.os_release.return_value = 'ocata'
        _exists.return_value = False
        self.enable_memcache.return_value = False
        rids.return_value = []
        _map = utils.restart_map(actual_services=False)
        self.assertIsInstance(_map, OrderedDict)
        self.assertEqual(_map, RESTART_MAP_OCATA_BASE)

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    @patch('os.path.exists')
    def test_restart_map_apache24(self, _exists, subcontext):
        _exists.return_value = True
        self.os_release.return_value = 'diablo'
        _map = utils.restart_map()
        self.assertIn('/etc/apache2/sites-available/'
                      'openstack_https_frontend.conf', _map)
        self.assertNotIn('/etc/apache2/sites-available/'
                         'openstack_https_frontend', _map)

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_restart_map_ssl(self, _isdir, _exists, subcontext):
        _exists.return_value = True
        _isdir.return_value = True
        self.os_release.return_value = 'diablo'
        _map = utils.restart_map()
        self.assertTrue('/etc/apache2/ssl/nova/*' in _map)
        _isdir.return_value = False
        _map = utils.restart_map()
        self.assertTrue('/etc/apache2/ssl/nova/*' not in _map)

    def test_console_attributes_spice(self):
        _proto = utils.common.console_attributes('protocol', proto='spice')
        self.assertEqual(_proto, 'spice')

    def test_console_attributes_vnc(self):
        self.test_config.set('console-access-protocol', 'vnc')
        _proto = utils.common.console_attributes('protocol')
        _servs = utils.common.console_attributes('services')
        _pkgs = utils.common.console_attributes('packages')
        _proxy_page = utils.common.console_attributes('proxy-page')
        vnc_pkgs = ['nova-novncproxy', 'nova-xvpvncproxy']
        vnc_servs = ['nova-novncproxy', 'nova-xvpvncproxy']
        self.assertEqual(_proto, 'vnc')
        self.assertEqual(sorted(_servs), sorted(vnc_servs))
        self.assertEqual(sorted(_pkgs), sorted(vnc_pkgs))
        self.assertEqual(_proxy_page, None)

    def test_console_attributes_console_access_port(self):
        self.test_config.set('console-access-port', '6080')
        _proxy_port = utils.common.console_attributes('proxy-port', 'novnc')
        self.assertEqual(_proxy_port, '6080')
        self.test_config.set('console-access-port', '6081')
        _proxy_port = utils.common.console_attributes('proxy-port', 'xvpvnc')
        self.assertEqual(_proxy_port, '6081')
        self.test_config.set('console-access-port', '6082')
        _proxy_port = utils.common.console_attributes('proxy-port', 'spice')
        self.assertEqual(_proxy_port, '6082')

    def test_database_setup(self):
        self.relation_ids.return_value = ['shared-db:12']
        self.related_units.return_value = ['mysql/0']
        self.relation_get.return_value = (
            'nova-cloud-controller/0 nova-cloud-controller/1')
        self.local_unit.return_value = 'nova-cloud-controller/0'
        self.assertTrue(utils.database_setup(prefix='nova'))
        self.relation_get.assert_called_with('nova_allowed_units',
                                             rid='shared-db:12',
                                             unit='mysql/0')

    def test_database_not_setup(self):
        self.relation_ids.return_value = ['shared-db:12']
        self.related_units.return_value = ['mysql/0']
        self.relation_get.return_value = 'nova-cloud-controller/1'
        self.local_unit.return_value = 'nova-cloud-controller/0'
        self.assertFalse(utils.database_setup(prefix='nova'))
        self.relation_get.assert_called_with('nova_allowed_units',
                                             rid='shared-db:12',
                                             unit='mysql/0')
        self.relation_get.return_value = None
        self.assertFalse(utils.database_setup(prefix='nova'))
        self.relation_get.assert_called_with('nova_allowed_units',
                                             rid='shared-db:12',
                                             unit='mysql/0')

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_determine_packages_console(self, subcontext):
        self.test_config.set('console-access-protocol', 'spice')
        self.relation_ids.return_value = []
        self.os_release.return_value = 'diablo'
        pkgs = utils.determine_packages()
        console_pkgs = ['nova-spiceproxy', 'nova-consoleauth']
        for console_pkg in console_pkgs:
            self.assertIn(console_pkg, pkgs)
        self.os_release.return_value = 'train'
        pkgs = utils.determine_packages()
        self.assertNotIn(
            'nova-consoleauth', pkgs)

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_determine_packages_base_icehouse(self, subcontext):
        self.relation_ids.return_value = []
        self.os_release.return_value = 'icehouse'
        self.token_cache_pkgs.return_value = []
        self.enable_memcache.return_value = False
        pkgs = utils.determine_packages()
        ex = list(set(utils.BASE_PACKAGES + utils.BASE_SERVICES))
        # nova-placement-api, et al, are purposely dropped unless it's ocata
        ex.remove('nova-placement-api')
        self.assertEqual(sorted(ex), sorted(pkgs))

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_determine_packages_base_queens(self, subcontext):
        self.relation_ids.return_value = []
        self.os_release.return_value = 'queens'
        self.token_cache_pkgs.return_value = []
        self.enable_memcache.return_value = False
        pkgs = utils.determine_packages()
        ex = list(set(utils.BASE_PACKAGES + utils.BASE_SERVICES))
        # some packages still need to be removed
        ex.remove('nova-cert')
        ex.remove('nova-objectstore')
        ex.remove('nova-api-ec2')
        self.assertEqual(sorted(ex), sorted(pkgs))

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_determine_packages_base_rocky(self, subcontext):
        self.relation_ids.return_value = []
        self.os_release.return_value = 'rocky'
        self.token_cache_pkgs.return_value = []
        self.enable_memcache.return_value = False
        pkgs = utils.determine_packages()
        ex = list(set([p for p in utils.BASE_PACKAGES + utils.BASE_SERVICES
                      if not p.startswith('python-')] + utils.PY3_PACKAGES))
        # some packages still need to be removed
        ex.remove('libapache2-mod-wsgi')
        ex.remove('nova-cert')
        ex.remove('nova-objectstore')
        ex.remove('nova-api-ec2')
        self.assertEqual(sorted(ex), sorted(pkgs))

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_determine_packages_base_stein(self, subcontext):
        self.relation_ids.return_value = []
        self.os_release.return_value = 'stein'
        self.token_cache_pkgs.return_value = []
        self.enable_memcache.return_value = False
        pkgs = utils.determine_packages()
        ex = list(set([p for p in utils.BASE_PACKAGES + utils.BASE_SERVICES
                      if not p.startswith('python-')] + utils.PY3_PACKAGES))
        # some packages still need to be removed
        ex.remove('libapache2-mod-wsgi')
        ex.remove('nova-cert')
        ex.remove('nova-objectstore')
        ex.remove('nova-api-ec2')
        ex.append('python3-mysqldb')
        self.assertEqual(sorted(ex), sorted(pkgs))

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_determine_packages_serial_console(self, subcontext):
        self.test_config.set('enable-serial-console', True)
        self.relation_ids.return_value = []
        self.os_release.return_value = 'juno'
        pkgs = utils.determine_packages()
        console_pkgs = ['nova-serialproxy', 'nova-consoleauth']
        for console_pkg in console_pkgs:
            self.assertIn(console_pkg, pkgs)
        self.os_release.return_value = 'train'
        pkgs = utils.determine_packages()
        self.assertNotIn('nova-consoleauth', pkgs)

    @patch('charmhelpers.contrib.openstack.context.SubordinateConfigContext')
    def test_determine_packages_serial_console_icehouse(self, subcontext):
        self.test_config.set('enable-serial-console', True)
        self.relation_ids.return_value = []
        self.os_release.return_value = 'icehouse'
        pkgs = utils.determine_packages()
        console_pkgs = ['nova-serialproxy', 'nova-consoleauth']
        for console_pkg in console_pkgs:
            self.assertNotIn(console_pkg, pkgs)

    def test_determine_purge_packages(self):
        'Ensure no packages are identified for purge prior to rocky'
        self.os_release.return_value = 'queens'
        self.assertEqual(utils.determine_purge_packages(), [])

    def test_determine_purge_packages_rocky(self):
        'Ensure python packages are identified for purge at rocky'
        self.os_release.return_value = 'rocky'
        self.assertEqual(utils.determine_purge_packages(),
                         [p for p in utils.BASE_PACKAGES
                          if p.startswith('python-')] +
                         ['python-nova', 'python-memcache',
                          'libapache2-mod-wsgi'])

    @patch.object(utils, 'restart_map')
    def test_determine_ports(self, restart_map):
        restart_map.return_value = {
            '/etc/nova/nova.conf': ['nova-api-os-compute', 'nova-api-ec2'],
            '/etc/nova/api-paste.ini': ['nova-api-os-compute', 'nova-api-ec2'],
        }
        ports = utils.determine_ports()
        ex = [8773, 8774]
        self.assertEqual(ex, sorted(ports))

    def test_save_script_rc_base(self):
        self.relation_ids.return_value = []
        utils.save_script_rc()
        self.save_script_rc.assert_called_with(**SCRIPTRC_ENV_VARS)

    @patch('charmhelpers.contrib.openstack.utils.lsb_release')
    def test_get_step_upgrade_source_target_liberty(self, lsb_release):
        self.lsb_release.return_value = {'DISTRIB_CODENAME': 'trusty'}
        lsb_release.return_value = {'DISTRIB_CODENAME': 'trusty'}
        self.get_os_codename_install_source.side_effect = self.originals[
            'charmhelpers.contrib.openstack.utils.'
            'get_os_codename_install_source']

        # icehouse -> liberty
        self.os_release.return_value = 'icehouse'
        self.assertEqual(
            utils.get_step_upgrade_source('cloud:trusty-liberty'),
            'cloud:trusty-kilo')

        # juno -> liberty
        self.os_release.return_value = 'juno'
        self.assertEqual(
            utils.get_step_upgrade_source('cloud:trusty-liberty'),
            'cloud:trusty-kilo')

        # kilo -> liberty
        self.os_release.return_value = 'kilo'
        with patch_open() as (_open, _file):
            self.assertEqual(
                utils.get_step_upgrade_source('cloud:trusty-liberty'),
                None)

    @patch('charmhelpers.contrib.openstack.utils.lsb_release')
    def test_get_setup_upgrade_source_target_newton(self, lsb_release):
        # mitaka -> newton
        self.lsb_release.return_value = {'DISTRIB_CODENAME': 'xenial'}
        lsb_release.return_value = {'DISTRIB_CODENAME': 'xenial'}
        self.os_release.return_value = 'mitaka'
        self.get_os_codename_install_source.side_effect = self.originals[
            'charmhelpers.contrib.openstack.utils.'
            'get_os_codename_install_source']

        step_src = utils.get_step_upgrade_source(OS_ORIGIN_NEWTON_STAGING)
        self.assertEqual(step_src, None)

    @patch('charmhelpers.contrib.openstack.utils.lsb_release')
    def test_get_setup_upgrade_source_target_ocata(self, lsb_release):
        # mitaka -> ocata
        self.lsb_release.return_value = {'DISTRIB_CODENAME': 'xenial'}
        lsb_release.return_value = {'DISTRIB_CODENAME': 'xenial'}
        self.os_release.return_value = 'mitaka'
        self.get_os_codename_install_source.side_effect = self.originals[
            'charmhelpers.contrib.openstack.utils.'
            'get_os_codename_install_source']

        step_src = utils.get_step_upgrade_source("cloud:xenial-ocata")
        self.assertEqual(step_src, "cloud:xenial-newton")

    @patch('charmhelpers.contrib.openstack.utils.lsb_release')
    def test_get_setup_upgrade_source_target_liberty_with_mirror(self,
                                                                 lsb_release):
        # from icehouse to liberty using a raw deb repo
        self.lsb_release.return_value = {'DISTRIB_CODENAME': 'trusty'}
        lsb_release.return_value = {'DISTRIB_CODENAME': 'trusty'}
        self.get_os_codename_install_source.side_effect = self.originals[
            'charmhelpers.contrib.openstack.utils.'
            'get_os_codename_install_source']
        self.os_release.return_value = 'icehouse'
        step_src = utils.get_step_upgrade_source(OS_ORIGIN_LIBERTY_STAGING)
        self.assertEqual(step_src, 'cloud:trusty-kilo')

    @patch.object(utils, 'remove_known_host')
    @patch.object(utils, 'ssh_known_host_key')
    @patch('subprocess.check_output')
    def test_add_known_host_exists(self, check_output, host_key, rm):
        check_output.return_value = b'|1|= fookey'
        host_key.return_value = '|1|= fookey'
        with patch_open() as (_open, _file):
            utils.add_known_host('foohost', 'aservice')
            rm.assert_not_called()
            _file.write.assert_not_called()

    @patch.object(utils, 'known_hosts')
    @patch.object(utils, 'remove_known_host')
    @patch.object(utils, 'ssh_known_host_key')
    @patch('subprocess.check_output')
    def test_add_known_host_exists_outdated(
            self, check_output, host_key, rm, known_hosts):
        check_output.return_value = b'|1|= fookey'
        host_key.return_value = '|1|= fookey_old'
        with patch_open() as (_open, _file):
            utils.add_known_host('foohost', None, None)
            rm.assert_called_with('foohost', None, None)

    @patch.object(utils, 'known_hosts')
    @patch.object(utils, 'remove_known_host')
    @patch.object(utils, 'ssh_known_host_key')
    @patch('subprocess.check_output')
    def test_add_known_host_exists_added(
            self, check_output, host_key, rm, known_hosts):
        check_output.return_value = b'|1|= fookey'
        host_key.return_value = None
        with patch_open() as (_open, _file):
            _file.write = MagicMock()
            utils.add_known_host('foohost', 'aservice')
            rm.assert_not_called()
            _file.write.assert_called_with('|1|= fookey\n')

    @patch('charmhelpers.contrib.openstack.cert_utils.'
           'get_cert_relation_ca_name')
    def test_get_ca_cert_b64_from_relation(self, get_cert_relation_ca_name):
        # Test input simulating the case where a CA certificate has been
        # provided by the 'certificates' relation and installed on disk:
        get_cert_relation_ca_name.return_value = 'rel_juju_ca_cert'
        open_side_effect = None  # file is found

        with patch_open() as (_open, _file):
            _file.readlines = MagicMock()
            _file.write = MagicMock()
            _file.read.return_value = b'mycert'
            _open.side_effect = open_side_effect
            self.assertEqual(
                utils.get_ca_cert_b64(),
                'bXljZXJ0')
            _open.assert_called_once_with(
                '/usr/local/share/ca-certificates/rel_juju_ca_cert.crt', 'rb')

    @patch('charmhelpers.contrib.openstack.cert_utils.'
           'get_cert_relation_ca_name')
    def test_get_ca_cert_b64_from_option(self, get_cert_relation_ca_name):
        # Test input simulating the case where a CA certificate has been
        # provided by ssl_* option and installed on disk:
        get_cert_relation_ca_name.return_value = ''
        open_side_effect = None  # file is found

        with patch_open() as (_open, _file):
            _file.readlines = MagicMock()
            _file.write = MagicMock()
            _file.read.return_value = b'mycert'
            _open.side_effect = open_side_effect
            self.assertEqual(
                utils.get_ca_cert_b64(),
                'bXljZXJ0')
            _open.assert_called_once_with(
                '/usr/local/share/ca-certificates/keystone_juju_ca_cert.crt',
                'rb')

    @patch('charmhelpers.contrib.openstack.cert_utils.'
           'get_cert_relation_ca_name')
    def test_get_ca_cert_b64_not_found(self, get_cert_relation_ca_name):
        # Test input simulating the case where no CA certificate can be found
        # on disk:
        get_cert_relation_ca_name.return_value = ''
        open_side_effect = OSError

        with patch_open() as (_open, _file):
            _open.side_effect = open_side_effect
            self.assertEqual(
                utils.get_ca_cert_b64(),
                '')

    @patch.object(utils, 'known_hosts')
    @patch('subprocess.check_call')
    def test_remove_host_key(self, check_call, known_hosts):
        known_hosts.return_value = '/tmp/known_hosts'
        utils.remove_known_host('foo', 'aservice')
        check_call.assert_called_with([
            'ssh-keygen', '-f', known_hosts(), '-R', 'foo'])

    @patch.object(utils, 'authorized_keys')
    def test_ssh_authorized_key_exists(self, keys):
        key = 'ssh-rsa BBBBB3NzaC1yc2EBBBBDBQBBBBBBBQC27Us7lSjCpa7bumXBgc' \
              ' nova-compute-2'
        with patch_open() as (_open, _file):
            _file.read.return_value = AUTHORIZED_KEYS
            self.assertTrue(utils.ssh_authorized_key_exists(key, 'aservice'))

    @patch.object(utils, 'authorized_keys')
    def test_ssh_authorized_key_doesnt_exist(self, keys):
        key = 'xxxx'
        with patch_open() as (_open, _file):
            _file.read = MagicMock()
            _file.readreturn_value = AUTHORIZED_KEYS
            self.assertFalse(utils.ssh_authorized_key_exists(key, 'aservice'))

    @patch.object(utils, 'known_hosts')
    @patch.object(utils, 'authorized_keys')
    @patch('os.path.isfile')
    def test_ssh_compute_remove(self, isfile,
                                auth_key, known_host):
        isfile.return_value = False

        removed_key = AUTHORIZED_KEYS.split('\n')[2]

        keys_removed = (
            "\nssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC27Us7lSjCpa7bumXAgc "
            "nova-compute-1\n"
            "ssh-rsa CCCCB3NzaC1yc2ECCCCDCQCBCCCBCQC27Us7lSjCpa7bumXCgc "
            "nova-compute-3\n"
        )
        isfile.return_value = True
        self.remote_unit.return_value = 'nova-compute/2'

        _written = ""

        def _writer(s):
            nonlocal _written
            _written += s

        with patch_open() as (_open, _file):
            _file.readlines = MagicMock()
            _file.write.side_effect = _writer
            _file.readlines.return_value = AUTHORIZED_KEYS.split('\n')
            utils.ssh_compute_remove(removed_key)
            self.assertEqual(_written, keys_removed)

    @patch.object(utils.ch_utils, 'get_host_ip')
    @patch.object(utils.ch_ip, 'ns_query')
    def test_resolve_hosts_for_bug_1992789(self, _ns_query, _get_host_ip):
        # regression test for bug: 1992789; when the function was refactored to
        # use a set instead of a list to ensure uniqueness of hosts, a method
        # was missed from being converted from .append() to .add()
        private_address = "myhostname"  # trigger behaviour of bug
        hostname = "myhostname2"
        db_key = "hostset-{}".format(private_address)

        # note that this is patched in class setup to :memory: sqlite db
        db = charmhelpers.core.unitdata.kv()
        db.unset(db_key)

        # ensure caching is disabled
        self.test_config.set('cache-known-hosts', False)
        _get_host_ip.return_value = "10.0.0.10"
        _ns_query.return_value = False
        hosts = utils.resolve_hosts_for(private_address, hostname)
        self.assertEqual(sorted(hosts),
                         ["10.0.0.10", "myhostname", "myhostname2"])

    def test_determine_endpoints_base(self):
        self.relation_ids.return_value = []
        self.os_release.return_value = 'diablo'
        self.assertEqual(
            BASE_ENDPOINTS, utils.determine_endpoints('http://foohost.com',
                                                      'http://foohost.com',
                                                      'http://foohost.com'))

    def test_determine_endpoints_queens(self):
        self.relation_ids.return_value = []
        self.os_release.return_value = 'queens'
        self.assertEqual(
            QUEENS_ENDPOINTS, utils.determine_endpoints('http://foohost.com',
                                                        'http://foohost.com',
                                                        'http://foohost.com'))

    def test_determine_endpoints_train(self):
        # Having placement related w/ train disables placement_api
        self.relation_ids.return_value = ['placement:1']
        self.os_release.return_value = 'train'
        self.assertEqual(
            TRAIN_ENDPOINTS, utils.determine_endpoints('http://foohost.com',
                                                       'http://foohost.com',
                                                       'http://foohost.com'))

    @patch.object(utils, 'known_hosts')
    @patch('subprocess.check_output')
    def test_ssh_known_host_key_rc0(self, _check_output, _known_hosts):
        _known_hosts.return_value = '/foo/known_hosts'
        _check_output.return_value = b"hash1 ssh-rsa key1\nhash2 ssh-rsa key2"
        result = utils.ssh_known_host_key('test', 'aservice')
        self.assertEqual("hash1 ssh-rsa key1", result)
        _check_output.assert_called_with(
            ['ssh-keygen', '-f', '/foo/known_hosts',
             '-H', '-F', 'test'])
        _known_hosts.assert_called_with('aservice', None)
        utils.ssh_known_host_key('test', 'bar')
        _known_hosts.assert_called_with('bar', None)

    @patch.object(utils, 'known_hosts')
    @patch('subprocess.check_output')
    def test_ssh_known_host_key_bug1500589(self, _check_output, _known_hosts):
        """On precise ssh-keygen does not error if host not found in file. So
         check charm processes empty output properly"""
        _known_hosts.return_value = '/foo/known_hosts'
        _check_output.return_value = b''
        key = utils.ssh_known_host_key('test', 'aservice')
        self.assertEqual(key, None)

    @patch.object(utils, 'known_hosts')
    @patch('subprocess.check_output')
    def test_ssh_known_host_key_rc0_header(self, _check_output, _known_hosts):
        cmd = ['ssh-keygen', '-f', '/foo/known_hosts',
               '-H', '-F', 'test']
        _known_hosts.return_value = '/foo/known_hosts'
        _check_output.return_value = (b"# Host foo found: line 7\n"
                                      b"hash1 ssh-rsa key1\n"
                                      b"hash2 ssh-rsa key2")
        result = utils.ssh_known_host_key('test', 'aservice')
        self.assertEqual("hash1 ssh-rsa key1", result)
        _check_output.assert_called_with(cmd)
        _known_hosts.assert_called_with('aservice', None)
        utils.ssh_known_host_key('test', 'bar')
        _known_hosts.assert_called_with('bar', None)

    @patch.object(utils, 'known_hosts')
    @patch('subprocess.check_output')
    def test_ssh_known_host_key_rc1(self, _check_output, _known_hosts):
        cmd = ['ssh-keygen', '-f', '/foo/known_hosts',
               '-H', '-F', 'test']
        _known_hosts.return_value = '/foo/known_hosts'
        _check_output.side_effect = subprocess.CalledProcessError(
            1, ' '.join(cmd),
            output=b"hash1 ssh-rsa key1\nhash2 ssh-rsa key2", stderr='')
        result = utils.ssh_known_host_key('test', 'aservice')
        self.assertEqual("hash1 ssh-rsa key1", result)
        _check_output.assert_called_with(cmd)
        _known_hosts.assert_called_with('aservice', None)
        utils.ssh_known_host_key('test', 'bar')
        _known_hosts.assert_called_with('bar', None)

    @patch.object(utils, 'known_hosts')
    @patch('subprocess.check_output')
    def test_ssh_known_host_key_rc1_stderr(self, _check_output, _known_hosts):
        cmd = ['ssh-keygen', '-f', '/foo/known_hosts',
               '-H', '-F', 'test']
        _known_hosts.return_value = '/foo/known_hosts'
        _check_output.side_effect = subprocess.CalledProcessError(
            1, ' '.join(cmd),
            output="foobar", stderr='command error')
        result = utils.ssh_known_host_key('test', 'aservice')
        self.assertIsNone(result)
        _check_output.assert_called_with(cmd)
        _known_hosts.assert_called_with('aservice', None)
        utils.ssh_known_host_key('test', 'bar')
        _known_hosts.assert_called_with('bar', None)

    @patch.object(utils, 'known_hosts')
    @patch('subprocess.check_call')
    def test_remove_known_host(self, _check_call, _known_hosts):
        _known_hosts.return_value = '/foo/known_hosts'
        utils.remove_known_host('test', 'aservice')
        _check_call.assert_called_with(
            ['ssh-keygen', '-f', '/foo/known_hosts',
             '-R', 'test'])
        _known_hosts.assert_called_with('aservice', None)
        utils.remove_known_host('test', 'bar')
        _known_hosts.assert_called_with('bar', None)

    @patch('subprocess.check_output')
    def test_migrate_nova_databases(self, check_output):
        "Migrate database with nova-manage"
        self.relation_ids.return_value = []
        self.os_release.return_value = 'diablo'
        self.is_unit_paused_set.return_value = False
        self.services.return_value = ['dummy-service']
        utils.migrate_nova_databases()
        check_output.assert_called_with(['nova-manage', 'db', 'sync'])
        self.service_resume.assert_called()

    @patch('subprocess.check_output')
    def test_migrate_nova_databases_cluster(self, check_output):
        "Migrate database with nova-manage in a clustered env"
        self.relation_ids.return_value = ['cluster:1']
        self.os_release.return_value = 'diablo'
        self.is_unit_paused_set.return_value = False
        self.services.return_value = ['dummy-service']
        utils.migrate_nova_databases()
        check_output.assert_called_with(['nova-manage', 'db', 'sync'])
        self.assertNotIn(call(['nova-manage', 'db', 'online_data_migrations']),
                         check_output.mock_calls)
        self.peer_store.assert_called_with('dbsync_state', 'complete')
        self.service_resume.assert_called()

    @patch('subprocess.check_output')
    def test_migrate_nova_databases_mitaka(self, check_output):
        "Migrate database with nova-manage in a clustered env"
        self.relation_ids.return_value = ['cluster:1']
        self.os_release.return_value = 'mitaka'
        self.is_unit_paused_set.return_value = False
        self.services.return_value = ['dummy-service']
        utils.migrate_nova_databases()
        check_output.assert_has_calls([
            call(['nova-manage', 'api_db', 'sync']),
            call(['nova-manage', 'db', 'sync']),
            call(['nova-manage', 'db', 'online_data_migrations']),
        ])
        self.peer_store.assert_called_with('dbsync_state', 'complete')
        self.service_resume.assert_called()

    @patch('subprocess.Popen')
    @patch('subprocess.check_output')
    @patch.object(utils, 'get_cell_uuid')
    @patch.object(utils, 'is_cellv2_init_ready')
    def test_migrate_nova_databases_ocata(self, cellv2_ready, get_cell_uuid,
                                          check_output, Popen):
        "Migrate database with nova-manage in a clustered env"
        get_cell_uuid.return_value = 'c83121db-f1c7-464a-b657-38c28fac84c6'
        self.relation_ids.return_value = ['cluster:1']
        self.os_release.return_value = 'ocata'
        self.is_unit_paused_set.return_value = False
        self.services.return_value = ['dummy-service']
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_value': 0}
        process_mock.configure_mock(**attrs)
        Popen.return_value = process_mock
        utils.migrate_nova_databases()
        check_output.assert_has_calls([
            call(['nova-manage', 'api_db', 'sync']),
            call(['nova-manage', 'cell_v2', 'map_cell0']),
            call(['nova-manage', 'cell_v2', 'create_cell', '--name', 'cell1',
                  '--verbose']),
            call(['nova-manage', 'db', 'sync']),
            call(['nova-manage', 'db', 'online_data_migrations']),
            call(['nova-manage', 'cell_v2', 'discover_hosts', '--cell_uuid',
                  'c83121db-f1c7-464a-b657-38c28fac84c6', '--verbose']),
        ])
        map_call = call([
            'nova-manage',
            'cell_v2', 'map_instances',
            '--cell_uuid', 'c83121db-f1c7-464a-b657-38c28fac84c6',
            '--max-count', '50000'], stdout=-1)
        Popen.assert_has_calls([map_call])
        self.peer_store.assert_called_with('dbsync_state', 'complete')
        self.service_resume.assert_called()

    @patch('subprocess.Popen')
    @patch('subprocess.check_output')
    @patch.object(utils, 'get_cell_uuid')
    @patch.object(utils, 'is_cellv2_init_ready')
    def test_migrate_nova_databases_pike(self, cellv2_ready, get_cell_uuid,
                                         check_output, Popen):
        "Migrate database with nova-manage in a clustered env"
        get_cell_uuid.return_value = 'c83121db-f1c7-464a-b657-38c28fac84c6'
        self.relation_ids.return_value = ['cluster:1']
        self.os_release.return_value = 'pike'
        self.is_unit_paused_set.return_value = False
        self.services.return_value = ['dummy-service']
        utils.migrate_nova_databases()
        check_output.assert_has_calls([
            call(['nova-manage', 'api_db', 'sync']),
            call(['nova-manage', 'cell_v2', 'map_cell0']),
            call(['nova-manage', 'cell_v2', 'create_cell', '--name', 'cell1',
                  '--verbose']),
            call(['nova-manage', 'db', 'sync']),
            call(['nova-manage', 'db', 'online_data_migrations']),
            call(['nova-manage', 'cell_v2', 'discover_hosts', '--cell_uuid',
                  'c83121db-f1c7-464a-b657-38c28fac84c6', '--verbose']),
        ])
        map_call = call([
            'nova-manage', 'cell_v2', 'map_instances', '--cell_uuid',
            'c83121db-f1c7-464a-b657-38c28fac84c6'])
        self.assertFalse(map_call in Popen.call_args_list)
        self.peer_store.assert_called_with('dbsync_state', 'complete')
        self.service_resume.assert_called()

    @patch('subprocess.check_output')
    def test_migrate_nova_flavors(self, check_output):
        utils.migrate_nova_flavors()
        check_output.assert_called_with(
            ['nova-manage', 'db', 'migrate_flavor_data'])

    @patch.object(utils, 'get_step_upgrade_source')
    @patch.object(utils, 'migrate_nova_databases')
    @patch.object(utils, 'determine_packages')
    def test_upgrade_icehouse_juno(self, determine_packages,
                                   migrate_nova_databases,
                                   get_step_upgrade_source):
        "Simulate a call to do_openstack_upgrade() for icehouse->juno"
        self.test_config.set('openstack-origin', 'cloud:trusty-juno')
        get_step_upgrade_source.return_value = None
        self.os_release.return_value = 'icehouse'
        self.get_os_codename_install_source.return_value = 'juno'
        self.is_leader.return_value = True
        self.relation_ids.return_value = []
        utils.do_openstack_upgrade(self.register_configs())
        self.apt_update.assert_called_with(fatal=True)
        self.apt_upgrade.assert_called_with(options=DPKG_OPTS, fatal=True,
                                            dist=True)
        self.apt_install.assert_called_with(determine_packages(), fatal=True)
        self.register_configs.assert_called_with(release='juno')
        self.assertTrue(migrate_nova_databases.call_count, 1)

    @patch.object(utils, 'get_step_upgrade_source')
    @patch.object(utils, 'migrate_nova_databases')
    @patch.object(utils, 'determine_packages')
    def test_upgrade_juno_kilo(self, determine_packages,
                               migrate_nova_databases,
                               get_step_upgrade_source):
        "Simulate a call to do_openstack_upgrade() for juno->kilo"
        self.test_config.set('openstack-origin', 'cloud:trusty-kilo')
        get_step_upgrade_source.return_value = None
        self.os_release.return_value = 'juno'
        self.get_os_codename_install_source.return_value = 'kilo'
        self.is_leader.return_value = True
        self.relation_ids.return_value = []
        utils.do_openstack_upgrade(self.register_configs())
        self.apt_update.assert_called_with(fatal=True)
        self.apt_upgrade.assert_called_with(options=DPKG_OPTS, fatal=True,
                                            dist=True)
        self.apt_install.assert_called_with(determine_packages(), fatal=True)
        self.register_configs.assert_called_with(release='kilo')
        self.assertTrue(migrate_nova_databases.call_count, 1)

    @patch.object(utils, 'get_step_upgrade_source')
    @patch.object(utils, 'migrate_nova_flavors')
    @patch.object(utils, 'migrate_nova_databases')
    @patch.object(utils, 'determine_packages')
    def test_upgrade_kilo_liberty(self, determine_packages,
                                  migrate_nova_databases,
                                  migrate_nova_flavors,
                                  get_step_upgrade_source):
        "Simulate a call to do_openstack_upgrade() for kilo->liberty"
        self.test_config.set('openstack-origin', 'cloud:trusty-liberty')
        get_step_upgrade_source.return_value = None
        self.os_release.return_value = 'kilo'
        self.get_os_codename_install_source.return_value = 'liberty'
        self.is_leader.return_value = True
        self.relation_ids.return_value = []
        utils.do_openstack_upgrade(self.register_configs())
        self.apt_update.assert_called_with(fatal=True)
        self.apt_upgrade.assert_called_with(options=DPKG_OPTS, fatal=True,
                                            dist=True)
        self.apt_install.assert_called_with(determine_packages(), fatal=True)
        self.register_configs.assert_called_with(release='liberty')
        self.assertTrue(migrate_nova_flavors.call_count, 1)
        self.assertTrue(migrate_nova_databases.call_count, 1)

    @patch.object(utils, 'database_setup')
    @patch.object(utils, 'get_step_upgrade_source')
    @patch.object(utils, 'migrate_nova_databases')
    @patch.object(utils, 'determine_packages')
    def test_upgrade_liberty_mitaka(self, determine_packages,
                                    migrate_nova_databases,
                                    get_step_upgrade_source,
                                    database_setup):
        "Simulate a call to do_openstack_upgrade() for liberty->mitaka"
        self.test_config.set('openstack-origin', 'cloud:trusty-kilo')
        get_step_upgrade_source.return_value = None
        self.os_release.return_value = 'liberty'
        self.get_os_codename_install_source.return_value = 'mitaka'
        self.is_leader.return_value = True
        self.relation_ids.return_value = []
        database_setup.return_value = False
        utils.do_openstack_upgrade(self.register_configs())
        self.apt_update.assert_called_with(fatal=True)
        self.apt_upgrade.assert_called_with(options=DPKG_OPTS, fatal=True,
                                            dist=True)
        self.apt_install.assert_called_with(determine_packages(), fatal=True)
        self.register_configs.assert_called_with(release='mitaka')
        migrate_nova_databases.assert_not_called()
        database_setup.assert_called_with(prefix='novaapi')

    @patch.object(utils, 'online_data_migrations_if_needed')
    @patch.object(utils, 'disable_package_apache_site')
    @patch.object(utils, 'database_setup')
    @patch.object(utils, 'get_step_upgrade_source')
    @patch.object(utils, 'migrate_nova_databases')
    @patch.object(utils, 'determine_packages')
    def test_upgrade_to_rocky_and_to_train(self, determine_packages,
                                           migrate_nova_databases,
                                           get_step_upgrade_source,
                                           database_setup,
                                           disable_package_apache_site,
                                           online_data_migrations_if_needed):
        "Simulate a call to do_openstack_upgrade() for queens->rocky"
        self.test_config.set('openstack-origin', 'cloud:bionic-queens')
        get_step_upgrade_source.return_value = None
        self.os_release.return_value = 'queens'
        self.get_os_codename_install_source.return_value = 'rocky'
        self.is_leader.return_value = True
        self.relation_ids.return_value = []
        database_setup.return_value = False

        utils.do_openstack_upgrade(self.register_configs())

        self.apt_update.assert_called_with(fatal=True)
        self.apt_upgrade.assert_called_with(options=DPKG_OPTS, fatal=True,
                                            dist=True)
        self.apt_install.assert_called_with(determine_packages(), fatal=True)
        self.register_configs.assert_called_with(release='rocky')
        migrate_nova_databases.assert_not_called()
        database_setup.assert_called_with(prefix='novaapi')
        online_data_migrations_if_needed.assert_called_once()
        disable_package_apache_site.assert_called_once()

        # test upgrade from stein->train without placement related
        self.os_release.return_value = 'stein'
        self.get_os_codename_install_source.return_value = 'train'
        self.apt_update.reset_mock()

        utils.do_openstack_upgrade(self.register_configs())

        self.apt_update.assert_not_called()

        # test upgrade from stein->train with placement related
        self.os_release.return_value = 'stein'
        self.get_os_codename_install_source.return_value = 'train'
        self.relation_ids.return_value = ['placement-id']
        self.apt_update.reset_mock()

        utils.do_openstack_upgrade(self.register_configs())

        self.apt_update.assert_called()

    def test_guard_map_nova(self):
        self.relation_ids.return_value = []
        self.os_release.return_value = 'icehouse'
        self.assertEqual(
            {'nova-api-ec2': ['identity-service', 'amqp', 'shared-db'],
             'nova-api-os-compute': ['identity-service', 'amqp', 'shared-db'],
             'nova-cert': ['identity-service', 'amqp', 'shared-db'],
             'nova-conductor': ['identity-service', 'amqp', 'shared-db'],
             'nova-objectstore': ['identity-service', 'amqp', 'shared-db'],
             'nova-placement-api': ['identity-service', 'amqp', 'shared-db'],
             'nova-scheduler': ['identity-service', 'amqp', 'shared-db']},
            utils.guard_map()
        )

    def test_guard_map_neutron(self):
        self.relation_ids.return_value = []
        self.os_release.return_value = 'icehouse'
        self.get_os_codename_install_source.return_value = 'icehouse'
        self.assertEqual(
            {'nova-api-ec2': ['identity-service', 'amqp', 'shared-db'],
             'nova-api-os-compute': ['identity-service', 'amqp', 'shared-db'],
             'nova-cert': ['identity-service', 'amqp', 'shared-db'],
             'nova-conductor': ['identity-service', 'amqp', 'shared-db'],
             'nova-objectstore': ['identity-service', 'amqp', 'shared-db'],
             'nova-placement-api': ['identity-service', 'amqp', 'shared-db'],
             'nova-scheduler': ['identity-service', 'amqp', 'shared-db'], },
            utils.guard_map()
        )
        self.os_release.return_value = 'mitaka'
        self.get_os_codename_install_source.return_value = 'mitaka'
        self.assertEqual(
            {'nova-api-os-compute': ['identity-service', 'amqp', 'shared-db'],
             'nova-cert': ['identity-service', 'amqp', 'shared-db'],
             'nova-conductor': ['identity-service', 'amqp', 'shared-db'],
             'nova-placement-api': ['identity-service', 'amqp', 'shared-db'],
             'nova-scheduler': ['identity-service', 'amqp', 'shared-db'], },
            utils.guard_map()
        )

    def test_service_guard_inactive(self):
        '''Ensure that if disabled, service guards nothing'''
        contexts = MagicMock()

        @utils.service_guard({'test': ['interfacea', 'interfaceb']},
                             contexts, False)
        def dummy_func():
            pass
        dummy_func()
        self.service_running.assert_not_called()
        contexts.complete_contexts.assert_not_called()

    def test_service_guard_active_guard(self):
        '''Ensure services with incomplete interfaces are stopped'''
        class MockContext(object):
            called = False

            def complete_contexts(self):
                self.called = True
                return ['interfacea']

        _mc = MockContext()
        self.service_running.return_value = True

        @utils.service_guard({'test': ['interfacea', 'interfaceb']},
                             _mc, True)
        def dummy_func():
            pass
        dummy_func()
        self.service_running.assert_called_with('test')
        self.service_stop.assert_called_with('test')
        self.assertTrue(_mc.called)

    def test_service_guard_active_release(self):
        '''Ensure services with complete interfaces are not stopped'''
        class MockContext(object):
            called = False

            def complete_contexts(self):
                self.called = True
                return ['interfacea', 'interfaceb']

        _mc = MockContext()

        @utils.service_guard({'test': ['interfacea', 'interfaceb']},
                             _mc, True)
        def dummy_func():
            pass

        dummy_func()
        self.service_running.assert_not_called()
        self.service_stop.assert_not_called()
        self.assertTrue(_mc.called)

    def test_service_guard_active_with_guardmap_function_object(self):
        class MockContext(object):
            called = False

            def complete_contexts(self):
                self.called = True
                return ['interfacea', 'interfaceb']

        _mc = MockContext()

        def guard_map():
            return {'test': ['interfacea', 'interfaceb']}

        @utils.service_guard(guard_map, _mc, True)
        def dummy_func():
            pass

        dummy_func()
        self.service_running.assert_not_called()
        self.service_stop.assert_not_called()
        self.assertTrue(_mc.called)

    def test_service_guard_active_with_contexts_function_object(self):
        class MockContext(object):
            called = False

            def complete_contexts(self):
                self.called = True
                return ['interfacea', 'interfaceb']

        _mc = MockContext()

        def lmc():
            return _mc

        @utils.service_guard({'test': ['interfacea', 'interfaceb']}, lmc, True)
        def dummy_func():
            pass

        dummy_func()
        self.service_running.assert_not_called()
        self.service_stop.assert_not_called()
        self.assertTrue(_mc.called)

    def test_service_guard_active_with_active_function_object(self):
        class MockContext(object):
            called = False

            def complete_contexts(self):
                self.called = True
                return ['interfacea', 'interfaceb']

        _mc = MockContext()

        @utils.service_guard({'test': ['interfacea', 'interfaceb']},
                             _mc, lambda: False)
        def dummy_func():
            pass

        dummy_func()
        self.service_running.assert_not_called()
        self.assertFalse(_mc.called)

    def test_assess_status(self):
        with patch.object(utils, 'assess_status_func') as asf:
            configs = MagicMock()
            callee = MagicMock()
            asf.return_value = callee
            utils.assess_status(configs)
            asf.assert_called_once_with(configs)
            callee.assert_called_once_with()
            self.os_application_version_set.assert_called_with(
                utils.VERSION_PACKAGE
            )

    @patch.object(utils.ch_cluster, 'get_managed_services_and_ports')
    @patch.object(utils, 'get_optional_interfaces')
    @patch.object(utils, 'check_optional_relations')
    @patch.object(utils, 'REQUIRED_INTERFACES')
    @patch.object(utils, 'services')
    @patch.object(utils, 'determine_ports')
    @patch.object(utils.ch_utils, 'make_assess_status_func')
    @patch.object(utils.ch_utils, 'CompareOpenStackReleases')
    def test_assess_status_func(self,
                                compare_releases,
                                make_assess_status_func,
                                determine_ports,
                                services,
                                REQUIRED_INTERFACES,
                                check_optional_relations,
                                get_optional_interfaces,
                                get_managed_services_and_ports):
        compare_releases.return_value = 'stein'
        get_managed_services_and_ports.return_value = (['s1'], ['p1'])
        services.return_value = 's1'
        REQUIRED_INTERFACES.copy.return_value = {'int': ['test 1']}
        get_optional_interfaces.return_value = {'opt': ['test 2']}
        determine_ports.return_value = 'p1'
        utils.assess_status_func('test-config')
        # ports=None whilst port checks are disabled.
        make_assess_status_func.assert_called_once_with(
            'test-config',
            {'int': ['test 1'], 'opt': ['test 2']},
            charm_func=check_optional_relations, services=['s1'],
            ports=None)

        make_assess_status_func.reset_mock()
        compare_releases.return_value = 'train'
        utils.assess_status_func('test-config')
        make_assess_status_func.assert_called_once_with(
            'test-config',
            {'int': ['test 1'], 'placement': ['placement'], 'opt': ['test 2']},
            charm_func=check_optional_relations, services=['s1'],
            ports=None)

    def test_pause_unit_helper(self):
        with patch.object(utils, '_pause_resume_helper') as prh:
            utils.pause_unit_helper('random-config')
            prh.assert_called_once_with(utils.ch_utils.pause_unit,
                                        'random-config')
        with patch.object(utils, '_pause_resume_helper') as prh:
            utils.resume_unit_helper('random-config')
            prh.assert_called_once_with(utils.ch_utils.resume_unit,
                                        'random-config')

    @patch.object(utils.ch_cluster, 'get_managed_services_and_ports')
    @patch.object(utils, 'services')
    @patch.object(utils, 'determine_ports')
    def test_pause_resume_helper(self, determine_ports, services,
                                 get_managed_services_and_ports):
        f = MagicMock()
        get_managed_services_and_ports.return_value = (['s1'], ['p1'])
        services.return_value = ['s1']
        determine_ports.return_value = ['p1']
        with patch.object(utils, 'assess_status_func') as asf:
            asf.return_value = 'assessor'
            utils._pause_resume_helper(f, 'some-config')
            asf.assert_called_once_with('some-config')
            # ports=None whilst port checks are disabled.
            f.assert_called_once_with('assessor', services=['s1'], ports=None)

    @patch('charmhelpers.fetch.filter_installed_packages')
    def test_disable_aws_compat_services_uninstalled(
            self, filter_installed_packages,):
        filter_installed_packages.return_value = utils.AWS_COMPAT_SERVICES
        utils.update_aws_compat_services()
        self.config.assert_not_called()
        self.service_pause.assert_not_called()
        self.service_resume.assert_not_called()

    @patch('charmhelpers.fetch.filter_installed_packages')
    def test_disable_aws_compat_services_true(self, filter_installed_packages):
        filter_installed_packages.return_value = []
        self.test_config.set('disable-aws-compat', True)
        utils.update_aws_compat_services()

        self.service_resume.assert_not_called()
        self.service_pause.assert_has_calls(
            [call(s) for s in utils.AWS_COMPAT_SERVICES])

    @patch('charmhelpers.fetch.filter_installed_packages')
    def test_disable_aws_compat_services_false(
            self, filter_installed_packages):
        filter_installed_packages.return_value = []
        self.test_config.set('disable-aws-compat', False)
        utils.update_aws_compat_services()

        self.service_resume.assert_has_calls(
            [call(s) for s in utils.AWS_COMPAT_SERVICES])
        self.service_pause.assert_not_called()

    @patch('subprocess.check_output')
    def test_get_cell_uuid(self, mock_check_call):
        mock_check_call.return_value = NM_CELLS_LIST
        expected = '7a8a0e58-e127-4056-bb98-99d9579ca08b'
        self.assertEqual(expected, utils.get_cell_uuid('cell1'))

    @patch.object(utils, 'get_cell_uuid')
    @patch('subprocess.Popen')
    def test_map_instances(self, mock_popen, mock_get_cell_uuid):
        cell_uuid = 'c83121db-f1c7-464a-b657-38c28fac84c6'
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_value': 0}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        mock_get_cell_uuid.return_value = cell_uuid
        expectd_calls = [
            call([
                'nova-manage',
                'cell_v2',
                'map_instances',
                '--cell_uuid', 'c83121db-f1c7-464a-b657-38c28fac84c6',
                '--max-count', '50000'], stdout=-1),
            call().communicate(),
            call().wait()]

        utils.map_instances()
        mock_popen.assert_has_calls(expectd_calls, any_order=False)

    @patch.object(utils, 'get_cell_uuid')
    @patch('subprocess.Popen')
    def test_map_instances_multi_batch(self, mock_popen, mock_get_cell_uuid):
        cell_uuid = 'c83121db-f1c7-464a-b657-38c28fac84c6'
        process_mock = MagicMock()
        rcs = [0, 1]
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.side_effect': lambda: rcs.pop()}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        mock_get_cell_uuid.return_value = cell_uuid
        expectd_calls = [
            call([
                'nova-manage',
                'cell_v2',
                'map_instances',
                '--cell_uuid', 'c83121db-f1c7-464a-b657-38c28fac84c6',
                '--max-count', '50000'], stdout=-1),
            call().communicate(),
            call().wait(),
            call([
                'nova-manage',
                'cell_v2',
                'map_instances',
                '--cell_uuid', 'c83121db-f1c7-464a-b657-38c28fac84c6',
                '--max-count', '50000'], stdout=-1),
            call().communicate(),
            call().wait()]

        utils.map_instances()
        self.assertEqual(mock_popen.mock_calls, expectd_calls)

    @patch.object(utils, 'get_cell_uuid')
    @patch('subprocess.Popen')
    def test_map_instances_error(self, mock_popen, mock_get_cell_uuid):
        cell_uuid = 'c83121db-f1c7-464a-b657-38c28fac84c6'
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_code': 127}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        mock_get_cell_uuid.return_value = cell_uuid
        with self.assertRaises(Exception):
            utils.map_instances()

    @patch('subprocess.Popen')
    def test_archive_deleted_rows(self, mock_popen):
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_value': 0}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        expectd_calls = [
            call([
                'nova-manage',
                'db',
                'archive_deleted_rows',
                '--verbose'], stdout=-1),
            call().communicate(),
            call().wait()]

        utils.archive_deleted_rows()
        self.assertEqual(mock_popen.mock_calls, expectd_calls)

    @patch('subprocess.Popen')
    def test_archive_deleted_rows_exception(self, mock_popen):
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_value': 123}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        with self.assertRaises(Exception):
            utils.archive_deleted_rows()

    @patch('subprocess.Popen')
    def test_purge_stale_soft_deleted_rows(self, mock_popen):
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_value': 0}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        expectd_calls = [
            call([
                'nova-manage',
                'db',
                'purge',
                '--verbose',
                '--all'], stdout=-1),
            call().communicate(),
            call().wait()]
        utils.purge_stale_soft_deleted_rows()
        self.assertEqual(mock_popen.mock_calls, expectd_calls)

    @patch('subprocess.Popen')
    def test_purge_stale_soft_deleted_rows_no_data(self, mock_popen):
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_value': 3}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        expectd_calls = [
            call([
                'nova-manage',
                'db',
                'purge',
                '--verbose',
                '--all'], stdout=-1),
            call().communicate(),
            call().wait()]
        msg = utils.purge_stale_soft_deleted_rows()
        self.assertEqual(mock_popen.mock_calls, expectd_calls)
        self.assertEqual(
            msg, 'Purging stale soft-deleted rows and no data was deleted')

    @patch('subprocess.Popen')
    def test_purge_stale_soft_deleted_rows_with_before(self, mock_popen):
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_value': 0}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        expectd_calls = [
            call([
                'nova-manage',
                'db',
                'purge',
                '--verbose',
                '--before',
                '2024-06-06'], stdout=-1),
            call().communicate(),
            call().wait()]
        utils.purge_stale_soft_deleted_rows(before='2024-06-06')
        self.assertEqual(mock_popen.mock_calls, expectd_calls)

    @patch('subprocess.Popen')
    def test_purge_stale_soft_deleted_rows_exception(self, mock_popen):
        process_mock = MagicMock()
        attrs = {
            'communicate.return_value': ('output', 'error'),
            'wait.return_value': 123}
        process_mock.configure_mock(**attrs)
        mock_popen.return_value = process_mock
        with self.assertRaises(Exception):
            utils.purge_stale_soft_deleted_rows()

    def test_is_serial_console_enabled_on_juno(self):
        self.os_release.return_value = 'juno'
        self.test_config.set('enable-serial-console', True)
        self.assertTrue(
            utils.is_serial_console_enabled())

    def test_is_serial_console_enabled_off_juno(self):
        self.os_release.return_value = 'juno'
        self.test_config.set('enable-serial-console', False)
        self.assertFalse(
            utils.is_serial_console_enabled())

    def test_is_serial_console_enabled_on_icehouse(self):
        self.os_release.return_value = 'icehouse'
        self.test_config.set('enable-serial-console', True)
        self.assertFalse(
            utils.is_serial_console_enabled())

    @patch.object(utils, 'is_serial_console_enabled')
    def test_is_consoleauth_enabled(self, is_serial_console_enabled):
        self.os_release.return_value = 'mitaka'
        is_serial_console_enabled.return_value = True
        self.test_config.set('console-access-protocol', 'vnc')
        self.assertTrue(
            utils.is_consoleauth_enabled())
        self.os_release.return_value = 'train'
        self.assertFalse(
            utils.is_consoleauth_enabled())

    @patch.object(utils, 'is_serial_console_enabled')
    def test_is_consoleauth_enabled_no_serial(self,
                                              is_serial_console_enabled):
        self.os_release.return_value = 'mitaka'
        is_serial_console_enabled.return_value = False
        self.test_config.set('console-access-protocol', 'vnc')
        self.assertTrue(
            utils.is_consoleauth_enabled())

    @patch.object(utils, 'is_serial_console_enabled')
    def test_is_consoleauth_enabled_no_serial_no_console(
            self,
            is_serial_console_enabled):
        self.os_release.return_value = 'mitaka'
        is_serial_console_enabled.return_value = False
        self.test_config.set('console-access-protocol', None)
        self.assertFalse(
            utils.is_consoleauth_enabled())

    @patch.object(utils, 'get_cell_uuid')
    @patch('subprocess.check_output')
    def test_add_hosts_to_cell(self, mock_check_output, mock_get_cell_uuid):
        cell_uuid = 'c83121db-f1c7-464a-b657-38c28fac84c6'
        mock_get_cell_uuid.return_value = cell_uuid
        utils.add_hosts_to_cell()
        mock_check_output.assert_called_with(
            ['nova-manage', 'cell_v2', 'discover_hosts', '--cell_uuid',
             'c83121db-f1c7-464a-b657-38c28fac84c6', '--verbose'])

    @patch('hooks.nova_cc_context.NovaCellV2SharedDBContext')
    @patch('charmhelpers.contrib.openstack.context.AMQPContext')
    def test_is_cellv2_init_ready_mitaka(self, amqp, shared_db):
        self.os_release.return_value = 'mitaka'
        utils.is_cellv2_init_ready()
        self.os_release.assert_called_once_with('nova-common')
        amqp.assert_called_once()
        shared_db.assert_called_once()
        self.log.assert_called_once()

    @patch('hooks.nova_cc_context.NovaCellV2SharedDBContext')
    @patch('charmhelpers.contrib.openstack.context.AMQPContext')
    def test_is_cellv2_init_ready_ocata(self, amqp, shared_db):
        self.os_release.return_value = 'ocata'
        utils.is_cellv2_init_ready()
        self.os_release.assert_called_once_with('nova-common')
        amqp.assert_called_once()
        shared_db.assert_called_once()
        self.log.assert_not_called()

    @patch('charmhelpers.core.hookenv.relation_ids')
    def test_placement_api_enabled(self, rids):
        self.os_release.return_value = 'ocata'
        rids.return_value = []
        self.assertTrue(utils.placement_api_enabled())
        self.os_release.return_value = 'mitaka'
        rids.return_value = []
        self.assertFalse(utils.placement_api_enabled())
        self.os_release.return_value = 'train'
        rids.return_value = ['placement:1']
        self.assertFalse(utils.placement_api_enabled())

    def test_enable_metadata_api(self):
        self.os_release.return_value = 'pike'
        self.assertFalse(utils.enable_metadata_api())
        self.os_release.return_value = 'rocky'
        self.assertTrue(utils.enable_metadata_api())

    def test_get_shared_metadatasecret(self):
        self.leader_get.return_value = 'auuid'
        self.assertEqual(utils.get_shared_metadatasecret(), 'auuid')

    def test_set_shared_metadatasecret(self):
        self.uuid1.return_value = 'auuid'
        utils.set_shared_metadatasecret()
        self.leader_set.assert_called_once_with({
            'shared-metadata-secret': 'auuid'})

    @patch.object(utils, 'get_shared_metadatasecret')
    def test_get_metadata_settings(self, mock_get_shared_metadatasecret):
        self.os_release.return_value = 'rocky'
        self.canonical_url.return_value = 'http://someaddr'
        mock_get_shared_metadatasecret.return_value = 'auuid'
        self.assertEqual(
            utils.get_metadata_settings('configs'),
            {
                'nova-metadata-host': 'someaddr',
                'nova-metadata-port': 8775,
                'nova-metadata-protocol': 'http',
                'shared-metadata-secret': 'auuid'})

    def test_get_metadata_settings_pike(self):
        self.os_release.return_value = 'pike'
        self.assertEqual(
            utils.get_metadata_settings('configs'),
            {})

    @patch.object(utils.ch_context, 'SharedDBContext')
    @patch('charmhelpers.core.hookenv.relation_id')
    def test_get_cell_db_context(self, mock_relation_id, mock_SharedDBContext):
        mock_relation_id.return_value = 'dbid'
        utils.get_cell_db_context('mysql-cell2')
        mock_SharedDBContext.assert_called_once_with(
            relation_id='dbid',
            relation_prefix='nova',
            ssl_dir='/etc/nova')
        mock_relation_id.assert_called_once_with(
            relation_name='shared-db-cell',
            service_or_unit='mysql-cell2')

    @patch.object(utils.ch_context, 'AMQPContext')
    @patch('charmhelpers.core.hookenv.relation_id')
    def test_get_cell_amqp_context(self, mock_relation_id, mock_AMQPContext):
        mock_relation_id.return_value = 'amqpid'
        utils.get_cell_amqp_context('rabbitmq-server-cell2')
        mock_AMQPContext.assert_called_once_with(
            relation_id='amqpid',
            ssl_dir='/etc/nova')
        mock_relation_id.assert_called_once_with(
            relation_name='amqp-cell',
            service_or_unit='rabbitmq-server-cell2')

    def test_get_sql_uri(self):
        base_ctxt = {
            'database_type': 'mysql',
            'database_user': 'nova',
            'database_password': 'novapass',
            'database_host': '10.0.0.10',
            'database': 'novadb'}
        self.assertEqual(
            utils.get_sql_uri(base_ctxt),
            'mysql://nova:novapass@10.0.0.10/novadb')
        sslca_ctxt = {'database_ssl_ca': 'myca'}
        sslca_ctxt.update(base_ctxt)
        self.assertEqual(
            utils.get_sql_uri(sslca_ctxt),
            'mysql://nova:novapass@10.0.0.10/novadb?ssl_ca=myca')
        ssl_cert_ctxt = {
            'database_ssl_cert': 'mycert',
            'database_ssl_key': 'mykey'}
        ssl_cert_ctxt.update(sslca_ctxt)
        self.assertEqual(
            utils.get_sql_uri(ssl_cert_ctxt),
            ('mysql://nova:novapass@10.0.0.10/novadb?ssl_ca=myca&'
             'ssl_cert=mycert&ssl_key=mykey'))

    def test_get_sql_uri_with_port(self):
        base_ctxt = {
            'database_type': 'mysql',
            'database_user': 'nova',
            'database_password': 'novapass',
            'database_host': '10.0.0.10',
            'database_port': 3316,
            'database': 'novadb'}
        self.assertEqual(
            utils.get_sql_uri(base_ctxt),
            'mysql://nova:novapass@10.0.0.10:3316/novadb')
        sslca_ctxt = {'database_ssl_ca': 'myca'}
        sslca_ctxt.update(base_ctxt)
        self.assertEqual(
            utils.get_sql_uri(sslca_ctxt),
            'mysql://nova:novapass@10.0.0.10:3316/novadb?ssl_ca=myca')
        ssl_cert_ctxt = {
            'database_ssl_cert': 'mycert',
            'database_ssl_key': 'mykey'}
        ssl_cert_ctxt.update(sslca_ctxt)
        self.assertEqual(
            utils.get_sql_uri(ssl_cert_ctxt),
            ('mysql://nova:novapass@10.0.0.10:3316/novadb?ssl_ca=myca&'
             'ssl_cert=mycert&ssl_key=mykey'))

    @patch.object(utils, 'is_db_initialised')
    @patch.object(utils, 'get_cell_details')
    @patch.object(utils, 'get_cell_db_context')
    @patch.object(utils, 'get_cell_amqp_context')
    @patch.object(utils, 'get_sql_uri')
    @patch.object(utils.subprocess, 'check_output')
    def test_update_child_cell(self,
                               mock_check_output,
                               mock_get_sql_uri,
                               mock_get_cell_amqp_context,
                               mock_get_cell_db_context,
                               mock_get_cell_details,
                               mock_is_db_initialised):
        mock_is_db_initialised.return_value = True
        mock_get_cell_details.return_value = {'cell1': 'cell1uuid'}
        mock_get_cell_db_context.return_value = {'ctxt': 'a full context'}
        mock_get_cell_amqp_context.return_value = {'transport_url': 'amqp-uri'}
        mock_get_sql_uri.return_value = 'db-uri'
        utils.update_child_cell('cell2', 'mysql-cell2', 'amqp-cell2')
        mock_get_cell_amqp_context.assert_called_once_with('amqp-cell2')
        mock_get_cell_db_context.assert_called_once_with('mysql-cell2')
        mock_check_output.assert_called_once_with([
            'nova-manage',
            'cell_v2',
            'create_cell',
            '--verbose',
            '--name', 'cell2',
            '--transport-url', 'amqp-uri',
            '--database_connection', 'db-uri'])
        self.service_restart.assert_called_once_with('nova-scheduler')

    @patch.object(utils, 'is_db_initialised')
    @patch.object(utils.subprocess, 'check_output')
    def test_update_child_cell_no_local_db(self,
                                           mock_check_output,
                                           mock_is_db_initialised):
        mock_is_db_initialised.return_value = False
        utils.update_child_cell('cell2', 'mysql-cell2', 'amqp-cell2')
        mock_check_output.assert_not_called()
        self.service_restart.assert_not_called()

    @patch.object(utils, 'get_cell_details')
    @patch.object(utils, 'is_db_initialised')
    @patch.object(utils.subprocess, 'check_output')
    def test_update_child_cell_api_cell_not_registered(self,
                                                       mock_check_output,
                                                       mock_is_db_initialised,
                                                       mock_get_cell_details):
        mock_is_db_initialised.return_value = True
        mock_get_cell_details.return_value = {}
        utils.update_child_cell('cell2', 'mysql-cell2', 'amqp-cell2')
        mock_get_cell_details.assert_called_once_with()
        mock_check_output.assert_not_called()
        self.service_restart.assert_not_called()

    @patch.object(utils.subprocess, 'check_output')
    @patch.object(utils, 'get_cell_details')
    @patch.object(utils, 'is_db_initialised')
    @patch.object(utils, 'get_cell_db_context')
    def test_update_child_cell_no_cell_db(self, mock_get_cell_db_context,
                                          mock_is_db_initialised,
                                          mock_get_cell_details,
                                          mock_check_output):
        mock_is_db_initialised.return_value = True
        mock_get_cell_details.return_value = {'cell1': 'uuid4cell1'}
        mock_get_cell_db_context.return_value = {}
        utils.update_child_cell('cell2', 'mysql-cell2', 'amqp-cell2')
        mock_check_output.assert_not_called()
        self.service_restart.assert_not_called()

    @patch.object(utils, 'get_cell_amqp_context')
    @patch.object(utils, 'get_sql_uri')
    @patch.object(utils.subprocess, 'check_output')
    @patch.object(utils, 'get_cell_details')
    @patch.object(utils, 'is_db_initialised')
    @patch.object(utils, 'get_cell_db_context')
    def test_update_child_cell_no_cell_amqp(self, mock_get_cell_db_context,
                                            mock_is_db_initialised,
                                            mock_get_cell_details,
                                            mock_check_output,
                                            mock_get_sql_uri,
                                            mock_get_cell_amqp_context):
        mock_is_db_initialised.return_value = True
        mock_get_cell_details.return_value = {'cell1': 'uuid4cell1'}
        mock_get_cell_db_context.return_value = {'ctxt': 'a full context'}
        mock_get_cell_amqp_context.return_value = {}
        utils.update_child_cell('cell2', 'mysql-cell2', 'amqp-cell2')
        mock_check_output.assert_not_called()
        self.service_restart.assert_not_called()

    @patch('os.remove')
    @patch('os.path.exists')
    def test_disable_deprecated_nova_placement_apache_site(self, exists,
                                                           remove):
        self.os_release.return_value = 'stein'
        exists.return_value = True
        utils.disable_deprecated_nova_placement_apache_site()
        remove.assert_called()

    @patch.object(utils.ch_context, 'SharedDBContext')
    @patch.object(utils, 'get_cell_details')
    @patch.object(utils, 'get_sql_uri')
    @patch.object(utils.subprocess, 'check_output')
    def test_update_cell_database(self,
                                  mock_check_output,
                                  mock_get_sql_uri,
                                  mock_get_cell_details,
                                  mock_SharedDBContext):
        mock_get_cell_details.return_value = {
            'cell0': {'uuid': 'cell0uuid',
                      'amqp': 'none:///'},
            'cell1': {'uuid': 'cell1uuid'},
        }
        mock_get_sql_uri.return_value = 'db-uri'
        utils.update_cell_database()
        mock_SharedDBContext.assert_called_once_with(
            database='nova_cell0',
            relation_prefix='novacell0',
            ssl_dir='/etc/nova')
        mock_check_output.assert_has_calls([
            call(['nova-manage', 'cell_v2', 'update_cell',
                  '--cell_uuid', 'cell0uuid', '--transport-url', 'none:///',
                  '--database_connection', 'db-uri']),
            call(['nova-manage', 'cell_v2', 'update_cell',
                  '--cell_uuid', 'cell1uuid']),
        ])

    @patch('charmhelpers.core.hookenv.relation_ids')
    def test_check_optional_relations(self, relation_ids):
        self.get_os_codename_install_source.return_value = 'ussuri'
        self.os_release.return_value = 'ussuri'

        fake_relation_ids = {'placement': ['placement:0'],
                             'ha': ['ha:1'],
                             'dashboard': []}
        relation_ids.side_effect = fake_relation_ids.get
        self.test_config.set('enable-serial-console', True)
        (status, workload_msg) = utils.check_optional_relations(None)

        self.assertEqual('blocked', status)
        self.assertEqual(('hacluster missing configuration: vip, vip_iface, '
                          'vip_cidr'),
                         workload_msg)
        with patch.object(utils.ch_cluster,
                          'get_hacluster_config') as get_hacluster_config:  # noqa
            (status, workload_msg) = utils.check_optional_relations(None)
            self.assertEqual('blocked', status)
            self.assertEqual(("Required relation 'dashboard' needed when "
                              "enable-serial-console is set to True"),
                             workload_msg)
            fake_relation_ids['dashboard'] = ['dashboard:2']
            (status, workload_msg) = utils.check_optional_relations(None)
            self.assertEqual('unknown', status)
            self.assertEqual(None, workload_msg)
