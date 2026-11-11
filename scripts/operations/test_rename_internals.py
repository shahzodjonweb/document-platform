"""The rename migration's rewrites, against the repositories' real files."""
import json
from pathlib import Path
import unittest
from rename_internals import Stop, rewrite_env, rewrite_override, rewrite_stack, rewrite_state

ROOT = Path(__file__).resolve().parents[2]


class StackTests(unittest.TestCase):
    def test_platform_compose_renames_completely(self):
        text = rewrite_stack((ROOT / 'infra/production/compose.yaml').read_text())
        self.assertIn('name: docmaster-platform', text)
        self.assertIn('${DOCMASTER_IMAGE:', text)
        self.assertIn('${DOCMASTER_ENV_FILE:', text)
        self.assertIn('${DOCMASTER_HTTP_PORT:', text)
        self.assertIn('postgresql://docmaster:', text)
        self.assertIn('@db:5432/docmaster', text)
        self.assertIn('pg_isready -U docmaster -d docmaster', text)

    def test_web_style_compose(self):
        text = rewrite_stack('name: pdfmaster-web\nservices:\n  web:\n    image: ${PDFMASTER_IMAGE:?x}\n'
                             '  gateway:\n    ports: ["127.0.0.1:${PDFMASTER_HTTP_PORT:-8310}:8080"]\n')
        self.assertNotIn('pdfmaster', text.lower())

    def test_refuses_what_it_cannot_rename(self):
        with self.assertRaises(Stop):
            rewrite_stack('name: pdfmaster-platform\nx: ${PDFMASTER_SOMETHING_NEW}\n')

    def test_comments_may_keep_the_old_name(self):
        rewrite_stack('# formerly pdfmaster\nname: pdfmaster-web\n')


class EnvTests(unittest.TestCase):
    def test_port_and_domain(self):
        text = rewrite_env('A=1\nPUBLIC_DOMAIN=pdfmaster-admin.orderdesk.live\nPDFMASTER_HTTP_PORT=8311\n# c\n', 'platform')
        self.assertEqual(text, 'A=1\nPUBLIC_DOMAIN=api.docmaster.live\nDOCMASTER_HTTP_PORT=8311\n# c\n')
        text = rewrite_env('PUBLIC_DOMAIN=pdfmaster.orderdesk.live\nPDFMASTER_HTTP_PORT=8310\n', 'web')
        self.assertIn('PUBLIC_DOMAIN=docmaster.live', text)

    def test_unexpected_domain_or_missing_keys(self):
        with self.assertRaises(Stop):
            rewrite_env('PUBLIC_DOMAIN=example.com\nPDFMASTER_HTTP_PORT=1\n', 'web')
        with self.assertRaises(Stop):
            rewrite_env('PUBLIC_DOMAIN=docmaster.live\n', 'web')


class StateAndOverrideTests(unittest.TestCase):
    def test_images_renamed(self):
        state = {'active': {'image': 'pdfmaster-web:abc-1-1'}, 'previous': {'image': 'pdfmaster-web:def-2-1'},
                 'pending': None, 'last_run': [2, 1]}
        state, tags = rewrite_state(json.loads(json.dumps(state)), 'web')
        self.assertEqual(state['active']['image'], 'docmaster-web:abc-1-1')
        self.assertEqual(tags, [('pdfmaster-web:abc-1-1', 'docmaster-web:abc-1-1'),
                                ('pdfmaster-web:def-2-1', 'docmaster-web:def-2-1')])

    def test_override_keeps_both_aliases(self):
        text = (ROOT / 'infra/production/proxy-network.example.yaml').read_text().replace(
            '${PDFMASTER_PROXY_NETWORK:?Set the existing proxy network}', 'orderdesk_default')
        new = rewrite_override(text, 'platform')
        self.assertIn('aliases: [docmaster-platform-gateway, pdfmaster-platform-gateway]', new)
        self.assertEqual(rewrite_override(new, 'platform'), new)


if __name__ == '__main__':
    unittest.main()
