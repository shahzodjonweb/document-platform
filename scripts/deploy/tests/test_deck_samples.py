#!/usr/bin/env python3
"""The pull request's deck samples: printed, uploaded, and never able to fail a build."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/deploy'))
import container_smoke as smoke  # noqa: E402

spec = importlib.util.spec_from_file_location('deck_samples', ROOT / 'scripts/deploy/deck_samples.py')
deck_samples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deck_samples)


class Expected(unittest.TestCase):
    def test_a_deck_with_no_design_is_carlito_and_caladea_with_noto_serif_only_for_cyrillic(self):
        good = ['Caladea-Bold', 'Caladea', 'Carlito', 'LiberationSans']
        self.assertEqual(deck_samples.problems(good, None, 'en', True), [])
        self.assertEqual(deck_samples.problems(good, None, 'uz', True), [])
        self.assertEqual(deck_samples.problems([*good, 'NotoSerif-Bold'], None, 'ru', True), [])
        self.assertEqual(deck_samples.problems(good, None, 'ru', True), ['Noto Serif missing from Cyrillic headings'])
        self.assertEqual(deck_samples.problems([*good, 'NotoSerif'], None, 'en', True), ['Noto Serif with no Cyrillic'])
        self.assertEqual(deck_samples.problems(['NotoSans'], None, 'en', True), ['no Carlito', 'no Caladea'])

    def test_a_system_font_in_a_deck_is_reported_and_a_design_may_use_any_of_ours(self):
        self.assertEqual(deck_samples.problems(['DejaVuSans', 'Carlito'], 'boardroom', 'en', True), ['DejaVuSans is not ours'])
        self.assertEqual(deck_samples.problems(['NotoSerif', 'Carlito'], 'boardroom', 'en', True), [])

    def test_a_customers_path_must_not_see_the_deck_faces(self):
        self.assertEqual(deck_samples.problems(['NotoSans', 'NotoSerif'], None, 'ru', False), [])
        self.assertEqual(deck_samples.problems(['Carlito', 'NotoSans-Bold', 'NotoSerif'], None, 'ru', False), ["Carlito reached a customer's path"])

    def test_any_other_change_on_a_customers_path_is_reported_too(self):
        self.assertEqual(deck_samples.problems(['DejaVuSans', 'NotoSans', 'NotoSerif'], None, 'en', False), ["DejaVuSans is new on a customer's path"])
        self.assertEqual(deck_samples.problems(['NotoSans'], None, 'en', False), ["NotoSerif is gone from a customer's path"])
        self.assertEqual(deck_samples.problems(['DejaVuSans', 'LiberationSerif'], None, 'en', False),
                         ["DejaVuSans is new on a customer's path", "LiberationSerif is new on a customer's path",
                          "NotoSans is gone from a customer's path", "NotoSerif is gone from a customer's path"])

    def test_no_fonts_at_all_is_reported(self):
        self.assertEqual(deck_samples.problems([], None, 'en', True), ['no fonts'])

    def test_the_family_is_read_from_how_a_pdf_names_it(self):
        self.assertEqual(deck_samples.family('NotoSerif-Bold'), 'NotoSerif')
        self.assertEqual(deck_samples.family('Liberation Sans'), 'LiberationSans')


class Runs(unittest.TestCase):
    def run_main(self, folder, *, budget=200, convert=None):
        calls = []

        def draw(design, locale, path):
            path.write_bytes(b'pptx')

        def fake(source, target, seconds, deck_faces):
            calls.append((Path(source).stem, deck_faces, seconds))
            pdf = Path(target) / 'converted.pdf'
            pdf.write_bytes(b'pdf')
            return pdf
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = deck_samples.main(folder, budget, draw=draw, convert=convert or fake, fonts_in=lambda path: ['Carlito', 'Caladea', 'NotoSerif'])
        return code, calls, output.getvalue()

    def test_the_first_deck_goes_both_ways_in_each_language_and_every_file_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            code, calls, output = self.run_main(folder)
            kept = sorted(path.name for path in (Path(folder) / 'scratch' / 'deck-samples').iterdir())
        self.assertEqual(code, 0)
        self.assertEqual(calls[:6], [(f'no-design-{locale}', way, 60) for locale in ('en', 'ru', 'uz') for way in (True, False)])
        self.assertEqual(len(calls), 6 + 3 * (len(deck_samples.DESIGNS) - 1))
        for name in ('no-design-ru.pptx', 'no-design-ru.pdf', 'no-design-ru-customer-path.pdf', 'grotesk-uz.pdf'):
            self.assertIn(name, kept)
        self.assertIn('as expected', output)
        self.assertIn('UNEXPECTED', output)

    def test_a_conversion_that_fails_is_said_and_the_rest_still_run(self):
        def broken(source, target, seconds, deck_faces):
            raise RuntimeError('no soffice')
        with tempfile.TemporaryDirectory() as folder:
            code, _, output = self.run_main(folder, convert=broken)
        self.assertEqual(code, 0)
        self.assertIn('failed', output)
        self.assertIn('0 of ', output)

    def test_it_stops_while_there_is_budget_to_stop_in(self):
        with tempfile.TemporaryDirectory() as folder:
            code, calls, output = self.run_main(folder, budget=10)
        self.assertEqual((code, calls), (0, []))
        self.assertIn('out of budget', output)


class Smoke(unittest.TestCase):
    pull_request = {'GITHUB_EVENT_NAME': 'pull_request', 'DECK_SAMPLES_DIR': '/tmp/out'}

    def test_it_runs_in_the_worker_with_a_limit_and_copies_the_files_out(self):
        seen = []
        with mock.patch.object(smoke, 'run', lambda command, **kwargs: seen.append((command, kwargs['timeout']))):
            smoke.deck_samples(['docker', 'compose'], self.pull_request)
        self.assertEqual(seen[0][0], ['docker', 'compose', 'exec', '-T', 'worker', 'python', 'scripts/deploy/deck_samples.py'])
        self.assertLess(deck_samples.BUDGET + 20, seen[0][1])
        self.assertEqual(seen[1][0], ['docker', 'compose', 'cp', 'worker:/data/private/scratch/deck-samples/.', '/tmp/out'])

    def test_nothing_that_happens_to_it_fails_the_build(self):
        for error in (subprocess.CalledProcessError(1, 'docker'), subprocess.TimeoutExpired('docker', 190), OSError('no docker'), ValueError('anything')):
            with self.subTest(error=type(error).__name__), mock.patch.object(smoke, 'run', side_effect=error), contextlib.redirect_stdout(io.StringIO()) as output:
                smoke.deck_samples(['docker', 'compose'], self.pull_request)
                self.assertIn('DECK-FONTS', output.getvalue())

    def test_only_a_pull_request_runs_it_so_no_deploy_waits_for_it(self):
        for env in ({'GITHUB_EVENT_NAME': 'push'}, {'GITHUB_EVENT_NAME': 'workflow_dispatch'}, {}):
            with self.subTest(env=env), mock.patch.object(smoke, 'run') as run:
                smoke.deck_samples(['docker', 'compose'], env)
                run.assert_not_called()

    def test_it_runs_after_every_check_that_can_fail_the_build(self):
        text = (ROOT / 'scripts/deploy/container_smoke.py').read_text()
        self.assertLess(text.index('wait_for_cleanup_cycle(compose, env)\n                office_timings'), text.index('office_timings(compose, env)\n                deck_samples(compose, env)'))

    def test_the_artifact_is_for_pull_requests_and_short_lived(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        step = text[text.index('name: deck-samples') - 200:text.index('name: deck-samples') + 160]
        self.assertIn("if: github.event_name == 'pull_request'", step)
        self.assertIn('continue-on-error: true', step)
        self.assertIn('retention-days: 3', step)


if __name__ == '__main__':
    unittest.main()
