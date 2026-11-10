"""The proxy guard permits new hosts but rejects changes to the existing site."""
import copy
import tempfile
import unittest
from pathlib import Path
from proxy_setup import PREVIOUS_SITES, SITES, ensure_ours, without_new_routes


class RoutePreservationTests(unittest.TestCase):
    def setUp(self):
        self.old = {'apps': {
            'http': {'servers': {'srv0': {'listen': [':443'], 'routes': [
                {'match': [{'host': ['admin.orderdesk.live']}], 'handle': [
                    {'handler': 'reverse_proxy', 'upstreams': [{'dial': 'app:3000'}]}]}
            ]}}},
            'tls': {'automation': {'policies': [{'subjects': ['admin.orderdesk.live'],
                                                'issuers': [{'module': 'acme'}]}]}}
        }}
        self.added = copy.deepcopy(self.old)
        for host, target in [('pdfmaster.orderdesk.live', 'pdfmaster-web-gateway:8080'),
                             ('pdfmaster-admin.orderdesk.live', 'pdfmaster-platform-gateway:8080')]:
            self.added['apps']['http']['servers']['srv0']['routes'].append({
                'match': [{'host': [host]}], 'handle': [{'handler': 'reverse_proxy',
                                                       'upstreams': [{'dial': target}]}]})
            self.added['apps']['tls']['automation']['policies'][0]['subjects'].append(host)

    def test_allows_only_the_new_routes_and_certificate_subjects(self):
        self.assertEqual(without_new_routes(self.added), self.old)
        self.assertEqual(len(self.added['apps']['http']['servers']['srv0']['routes']), 3)

    def test_rejects_existing_upstream_changes(self):
        self.added['apps']['http']['servers']['srv0']['routes'][0]['handle'][0]['upstreams'][0]['dial'] = 'other:3000'
        self.assertNotEqual(without_new_routes(self.added), self.old)

    def test_rejects_existing_certificate_policy_changes(self):
        self.added['apps']['tls']['automation']['policies'][0]['issuers'] = [{'module': 'internal'}]
        self.assertNotEqual(without_new_routes(self.added), self.old)

    def test_rejects_removing_existing_certificate_subject(self):
        self.added['apps']['tls']['automation']['policies'][0]['subjects'].remove('admin.orderdesk.live')
        self.assertNotEqual(without_new_routes(self.added), self.old)


class OwnSitesFileTests(unittest.TestCase):
    """Our sites file may move from the reviewed previous version to this one, never from anything else."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'sites.caddy'

    def tearDown(self):
        self.folder.cleanup()

    def test_adds_docmaster_and_keeps_the_old_hosts(self):
        self.assertTrue(SITES.startswith(PREVIOUS_SITES))
        self.assertIn('docmaster.live {', SITES)

    def test_writes_when_absent(self):
        ensure_ours(self.path, SITES, PREVIOUS_SITES)
        self.assertEqual(self.path.read_text(), SITES)

    def test_replaces_the_previous_version(self):
        self.path.write_text(PREVIOUS_SITES)
        ensure_ours(self.path, SITES, PREVIOUS_SITES)
        self.assertEqual(self.path.read_text(), SITES)

    def test_leaves_the_current_version(self):
        self.path.write_text(SITES)
        ensure_ours(self.path, SITES, PREVIOUS_SITES)
        self.assertEqual(self.path.read_text(), SITES)

    def test_refuses_anything_else(self):
        self.path.write_text('example.com {\n}\n')
        with self.assertRaises(RuntimeError):
            ensure_ours(self.path, SITES, PREVIOUS_SITES)
        self.assertEqual(self.path.read_text(), 'example.com {\n}\n')


if __name__ == '__main__':
    unittest.main()
