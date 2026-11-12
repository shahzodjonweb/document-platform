"""DocMaster's own proxy: the published files, the gateway override, and what OrderDesk's removal picks."""
from pathlib import Path
import re
import unittest
from own_proxy import (CADDYFILE, COMPOSE, IMAGE, NETWORK, Stop, gateway_override, old_images, shared_override,
                       status_line, without_old_lines)

ROOT = Path(__file__).resolve().parents[2]


class PublishedFileTests(unittest.TestCase):
    def test_the_script_carries_the_repository_files(self):
        self.assertEqual(CADDYFILE, (ROOT / 'infra/production/proxy/Caddyfile').read_text())
        self.assertEqual(COMPOSE, (ROOT / 'infra/production/proxy/compose.yaml').read_text())

    def test_only_docmaster_hosts_are_served(self):
        sites = re.findall(r'^(\S+) \{$', CADDYFILE, re.M)
        self.assertEqual(sites, ['docmaster.live', 'www.docmaster.live', 'api.docmaster.live'])
        self.assertNotIn('orderdesk', CADDYFILE)
        self.assertIn('redir https://docmaster.live{uri} permanent', CADDYFILE)

    def test_compose_pins_the_image_and_uses_the_external_network(self):
        self.assertIn('image: ' + IMAGE + '\n', COMPOSE)
        self.assertRegex(IMAGE, r'@sha256:[0-9a-f]{64}$')
        self.assertIn('external: true\n    name: ' + NETWORK + '\n', COMPOSE)
        for port in ('"80:80"', '"443:443"', '"443:443/udp"'):
            self.assertIn(port, COMPOSE)
        self.assertNotIn('orderdesk', COMPOSE)


class OverrideTests(unittest.TestCase):
    def test_gateways_join_only_the_docmaster_network(self):
        for component in ('platform', 'web'):
            text = gateway_override(component)
            self.assertIn(f'aliases: [docmaster-{component}-gateway]', text)
            self.assertIn('name: docmaster-proxy', text)
            self.assertNotIn('orderdesk', text)
            self.assertNotIn('pdfmaster', text)

    def test_the_replaced_override_is_the_one_on_the_server(self):
        # As proxy_setup.gateway_override wrote it for OrderDesk's shared Caddy.
        self.assertEqual(shared_override('web'), '''services:
  gateway:
    networks:
      default:
      proxy:
        aliases: [docmaster-web-gateway, pdfmaster-web-gateway]
networks:
  proxy:
    external: true
    name: orderdesk_default
''')


class ResponseTests(unittest.TestCase):
    def test_status_line(self):
        self.assertEqual(status_line(b'HTTP/1.1 301 Moved Permanently\r\nLocation: x\r\n'), 301)
        self.assertEqual(status_line(b'HTTP/2 200\r\n'), 200)
        for junk in (b'', b'garbage', b'HTTP/1.1 abc\r\n'):
            with self.assertRaises(Stop):
                status_line(junk)


class RemovalTargetTests(unittest.TestCase):
    def test_images_of_orderdesk_containers_and_its_repositories(self):
        rows = ['aaa111 ghcr.io/shahzodjonweb/obunachi-qoshish-bot:latest',
                'bbb222 ghcr.io/shahzodjonweb/obunachi-qoshish-bot:<none>',
                'ccc333 postgres:16-alpine',
                'ddd444 postgres:17-alpine',
                'eee555 caddy:2-alpine',
                'fff666 docmaster-platform:abc-1-1',
                'ggg777 chrislusf/seaweedfs:4.47',
                'hhh888 <none>:<none>']
        containers = ['sha256:ccc333', 'sha256:eee555', 'sha256:aaa111']
        self.assertEqual(old_images(rows, containers), [
            'ghcr.io/shahzodjonweb/obunachi-qoshish-bot:latest', 'bbb222', 'postgres:16-alpine',
            'caddy:2-alpine', 'chrislusf/seaweedfs:4.47'])

    def test_crontab_lines(self):
        text, dropped = without_old_lines('0 3 * * * /opt/orderdesk/backup.sh\n# keep\n5 * * * * other\n')
        self.assertEqual((text, dropped), ('# keep\n5 * * * * other\n', 1))
        self.assertEqual(without_old_lines('@daily /opt/OrderDesk/x\n'), ('', 1))
        self.assertEqual(without_old_lines(''), ('', 0))


if __name__ == '__main__':
    unittest.main()
