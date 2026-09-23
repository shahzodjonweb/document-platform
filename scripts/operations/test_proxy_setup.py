"""The proxy guard permits new hosts but rejects changes to the existing site."""
import copy
import unittest
from proxy_setup import without_new_routes


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


if __name__ == '__main__':
    unittest.main()
