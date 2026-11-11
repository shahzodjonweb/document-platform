"""The PdfCraft binary reaches the image pinned, whole and unpacked safely."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('fetch_pdfcraft', ROOT / 'scripts/fetch_pdfcraft.py')
fetch_pdfcraft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_pdfcraft)
spec = importlib.util.spec_from_file_location('pdfcraft_container_smoke', ROOT / 'scripts/deploy/container_smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
spec = importlib.util.spec_from_file_location('processors_env', ROOT / 'processors/env.py')
processors_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(processors_env)
env_names = processors_env.names
BINARY = b'\x7fELF pretend binary'
NORMAL = (('pdfcraft-cli-0.16.1-linux-x86_64/pdfcraft-cli', BINARY), ('pdfcraft-cli-0.16.1-linux-x86_64/LICENSE-MIT', b'mit'),
          ('pdfcraft-cli-0.16.1-linux-x86_64/LICENSE-APACHE', b'apache'), ('pdfcraft-cli-0.16.1-linux-x86_64/NOTICE', b'notice'),
          ('pdfcraft-cli-0.16.1-linux-x86_64/OFL-noto-sans-thai.txt', b'ofl'), ('pdfcraft-cli-0.16.1-linux-x86_64/README.md', b'readme'))


def archive_of(*members, links=()):
    """Bytes of a .tar.gz with these (name, bytes) files, and these (name, kind, target) links."""
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as bundle:
        for name, data in members:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            bundle.addfile(item, io.BytesIO(data))
        for name, kind, target in links:
            item = tarfile.TarInfo(name)
            item.type, item.linkname = kind, target
            bundle.addfile(item)
    return stream.getvalue()


class Fetching(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name).resolve()
        self.dest = self.folder / 'opt' / 'pdfcraft'
        self.addCleanup(lambda: self.dest.exists() and self.dest.chmod(0o755))
        slept = mock.patch.object(fetch_pdfcraft.time, 'sleep')
        self.sleep = slept.start()
        self.addCleanup(slept.stop)

    def serve(self, data, *, machine='x86_64', **changes):
        """A manifest whose archive for this machine is a local file; returns its path."""
        source = self.folder / 'archive.tar.gz'
        source.write_bytes(data)
        entry = {'url': source.as_uri(), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), **changes}
        manifest = self.folder / 'manifest.json'
        manifest.write_text(json.dumps({'version': '0.16.1', 'archives': {machine: entry}}))
        return manifest

    def fetch(self, manifest, machine='x86_64'):
        with mock.patch.object(fetch_pdfcraft.platform, 'machine', return_value=machine), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            code = fetch_pdfcraft.main(['--dest', str(self.dest), '--manifest', str(manifest)])
        return code, errors.getvalue()

    def installed(self):
        return sorted(path.name for path in self.dest.iterdir()) if self.dest.exists() else []

    def test_the_committed_manifest_pins_both_architectures_on_our_mirror(self):
        manifest = json.loads((ROOT / 'processors/pdfcraft/manifest.json').read_text())
        self.assertEqual((manifest['version'], manifest['license'], manifest['source']), ('0.16.1', 'Apache-2.0 OR MIT', 'https://github.com/storytold/pdfcraft'))
        self.assertEqual(set(manifest['archives']), {'x86_64', 'aarch64'})
        for machine, bytes_, digest in (('x86_64', 41975181, '5d4e64a13863d3540043a5544ded933c93ee4e700afe5021fca6425fa42a99eb'),
                                        ('aarch64', 40384274, 'f93eb3927fa6c0126d8efd1bbf4b661a38e32d3b12fb5ccecdb85f463cc4258c')):
            archive = fetch_pdfcraft.pick_archive(manifest, machine)
            self.assertEqual((archive['bytes'], archive['sha256']), (bytes_, digest))
            self.assertEqual(archive['url'], f'https://github.com/shahzodjonweb/document-platform/releases/download/pdfcraft-cli-0.16.1/pdfcraft-cli-0.16.1-linux-{machine}.tar.gz')

    def test_the_archive_is_picked_by_machine(self):
        manifest = {'archives': {'x86_64': {'url': 'amd'}, 'aarch64': {'url': 'arm'}}}
        self.assertEqual(fetch_pdfcraft.pick_archive(manifest, 'x86_64')['url'], 'amd')
        self.assertEqual(fetch_pdfcraft.pick_archive(manifest, 'aarch64')['url'], 'arm')
        with self.assertRaises(fetch_pdfcraft.Mismatch):
            fetch_pdfcraft.pick_archive(manifest, 'riscv64')

    def test_a_machine_without_an_archive_exits_non_zero(self):
        code, errors = self.fetch(self.serve(archive_of(*NORMAL)), machine='riscv64')
        self.assertEqual(code, 1)
        self.assertIn('riscv64', errors)
        self.assertEqual(self.installed(), [])

    def test_only_the_binary_and_its_licences_are_unpacked_flat_and_read_only(self):
        code, _ = self.fetch(self.serve(archive_of(*NORMAL)))
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), sorted(('.installed.json', 'LICENSE-APACHE', 'LICENSE-MIT', 'NOTICE', 'OFL-noto-sans-thai.txt', 'pdfcraft-cli')))
        self.assertEqual((self.dest / 'pdfcraft-cli').read_bytes(), BINARY)
        self.assertEqual(stat.S_IMODE((self.dest / 'pdfcraft-cli').stat().st_mode), 0o555)
        self.assertEqual(stat.S_IMODE((self.dest / 'NOTICE').stat().st_mode), 0o444)
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o555)

    def test_the_machine_decides_which_archive_is_downloaded(self):
        code, _ = self.fetch(self.serve(archive_of(*NORMAL), machine='aarch64'), machine='aarch64')
        self.assertEqual(code, 0)
        self.assertIn('pdfcraft-cli', self.installed())

    def test_a_bad_digest_is_refused_at_once_and_nothing_is_installed(self):
        code, errors = self.fetch(self.serve(archive_of(*NORMAL), sha256='0' * 64))
        self.assertEqual(code, 1)
        self.assertIn('sha256', errors)
        self.assertEqual(self.installed(), [])
        self.sleep.assert_not_called()

    def test_more_bytes_than_pinned_are_refused_at_once(self):
        data = archive_of(*NORMAL)
        code, errors = self.fetch(self.serve(data, bytes=len(data) - 1))
        self.assertEqual(code, 1)
        self.assertIn('more than the pinned', errors)
        self.assertEqual(self.installed(), [])
        self.sleep.assert_not_called()

    def test_a_short_download_is_retried_and_then_fails(self):
        data = archive_of(*NORMAL)
        code, errors = self.fetch(self.serve(data, bytes=len(data) + 1))
        self.assertEqual(code, 1)
        self.assertIn('incomplete download', errors)
        self.assertEqual(self.sleep.call_count, fetch_pdfcraft.ATTEMPTS - 1)
        self.assertEqual(self.installed(), [])

    def test_a_connection_cut_mid_body_is_retried(self):
        manifest = self.serve(archive_of(*NORMAL))
        real = fetch_pdfcraft.urllib.request.urlopen
        calls = []

        def flaky(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                response = mock.MagicMock()
                response.__enter__.return_value.read.side_effect = fetch_pdfcraft.http.client.IncompleteRead(b'')
                return response
            return real(request, timeout=timeout)
        with mock.patch.object(fetch_pdfcraft.urllib.request, 'urlopen', flaky):
            code, _ = self.fetch(manifest)
        self.assertEqual((code, len(calls)), (0, 2))
        self.assertIn('pdfcraft-cli', self.installed())

    def test_path_traversal_refuses_the_whole_archive(self):
        for bad in ('../pdfcraft-cli', 'folder/../../evil', '/etc/pdfcraft-cli', 'folder\\..\\evil'):
            with self.subTest(name=bad):
                code, errors = self.fetch(self.serve(archive_of(*NORMAL, (bad, b'evil'))))
                self.assertEqual(code, 1)
                self.assertIn('unsafe member name', errors)
                self.assertEqual(self.installed(), [])
                self.assertFalse((self.folder / 'opt' / 'pdfcraft-cli').exists())
                self.assertFalse((self.folder / 'opt' / 'evil').exists())

    def test_links_and_other_special_members_refuse_the_whole_archive(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            for name in ('folder/pdfcraft-cli', 'folder/innocent'):
                with self.subTest(kind=kind, name=name):
                    members = [member for member in NORMAL if not member[0].endswith('/pdfcraft-cli') or name != 'folder/pdfcraft-cli']
                    code, errors = self.fetch(self.serve(archive_of(*members, links=[(name, kind, '/bin/sh')])))
                    self.assertEqual(code, 1)
                    self.assertIn('neither a file nor a folder', errors)
                    self.assertEqual(self.installed(), [])

    def test_an_archive_without_the_binary_or_a_licence_or_with_two_binaries_is_refused(self):
        without_binary = [member for member in NORMAL if not member[0].endswith('/pdfcraft-cli')]
        without_licence = [member for member in NORMAL if 'LICENSE' not in member[0]]
        for members, expected in ((without_binary, 'no pdfcraft-cli'), (without_licence, 'no licence'), ((*NORMAL, ('other/pdfcraft-cli', b'x')), 'two members')):
            with self.subTest(expected=expected):
                code, errors = self.fetch(self.serve(archive_of(*members)))
                self.assertEqual(code, 1)
                self.assertIn(expected, errors)
                self.assertEqual(self.installed(), [])

    def test_something_that_is_not_an_archive_exits_non_zero(self):
        code, _ = self.fetch(self.serve(b'not a tar file at all'))
        self.assertEqual(code, 1)
        self.assertEqual(self.installed(), [])

    def test_a_correct_install_is_skipped_and_a_changed_one_replaced(self):
        manifest = self.serve(archive_of(*NORMAL))
        self.assertEqual(self.fetch(manifest)[0], 0)
        with mock.patch.object(fetch_pdfcraft.urllib.request, 'urlopen', side_effect=AssertionError('downloaded again')):
            self.assertEqual(self.fetch(manifest)[0], 0)
        binary = self.dest / 'pdfcraft-cli'
        self.dest.chmod(0o755)
        binary.chmod(0o755)
        binary.write_bytes(b'tampered')
        self.assertEqual(self.fetch(manifest)[0], 0)
        self.assertEqual(binary.read_bytes(), BINARY)
        self.assertEqual(stat.S_IMODE(binary.stat().st_mode), 0o555)

    def test_another_archive_replaces_what_an_older_one_installed(self):
        self.assertEqual(self.fetch(self.serve(archive_of(*NORMAL)))[0], 0)
        newer = [(name, b'newer' if name.endswith('/pdfcraft-cli') else data) for name, data in NORMAL]
        self.assertEqual(self.fetch(self.serve(archive_of(*newer)))[0], 0)
        self.assertEqual((self.dest / 'pdfcraft-cli').read_bytes(), b'newer')

    def test_the_script_runs_isolated_with_the_standard_library_alone(self):
        data = archive_of(*NORMAL)
        manifest = self.serve(data, machine=fetch_pdfcraft.platform.machine())
        done = subprocess.run([sys.executable, '-I', '-S', str(ROOT / 'scripts/fetch_pdfcraft.py'), '--dest', str(self.dest), '--manifest', str(manifest)],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('pdfcraft-cli', self.installed())


class Image(unittest.TestCase):
    def test_the_dockerfile_fetches_it_in_its_own_layer_after_the_scanner(self):
        text = (ROOT / 'infra/Dockerfile').read_text()
        order = [text.index(line) for line in ('ENV SCANNER_MODELS=', 'COPY processors/pdfcraft/manifest.json /tmp/pdfcraft/', 'COPY scripts/fetch_pdfcraft.py /tmp/pdfcraft/',
                                               'python -I /tmp/pdfcraft/fetch_pdfcraft.py', 'ENV DOCMASTER_PDFCRAFT_BIN=/opt/docmaster/pdfcraft/pdfcraft-cli', 'COPY requirements.lock', 'USER docmaster')]
        self.assertEqual(order, sorted(order))

    def test_the_deck_fonts_are_never_installed_system_wide(self):
        # Installed, these move LibreOffice's stand-ins for Calibri, Cambria and Arial, which reflows
        # the Word and deck conversions customers get today and can change an upload's page count, and
        # CI's apt line would not show it. Decks get them from processors/assets/fonts (processors/deck_fonts.py).
        text = (ROOT / 'infra/Dockerfile').read_text() + (ROOT / '.github/workflows/ci.yml').read_text()
        for package in ('fonts-crosextra-carlito', 'fonts-crosextra-caladea', 'fonts-liberation'):
            self.assertNotIn(package, text)

    def test_the_image_never_takes_the_old_liberation_series(self):
        # bookworm's fonts-liberation is 1.07.4 and its fonts-liberation2 is 2.1.5. Noble's fonts-liberation
        # is 2.1.5, so a run on CI's packages would not show the difference.
        self.assertNotRegex((ROOT / 'infra/Dockerfile').read_text(), r'fonts-liberation(?!2)')

    def test_the_build_context_keeps_the_manifest_and_the_scripts(self):
        rules = [line.strip() for line in (ROOT / '.dockerignore').read_text().splitlines() if line.strip() and not line.startswith('#')]
        for rule in rules:
            self.assertFalse(rule.startswith(('processors/pdfcraft', 'scripts', '*.json', '*.py')), rule)

    def test_no_font_setting_can_reach_the_processor_child_from_outside(self):
        # A deck's conversion sets its own for that one soffice, and every other conversion is left alone.
        text = (ROOT / 'processors/sandbox.py').read_text()
        self.assertNotIn('FONTCONFIG', text)

    def test_the_processor_child_may_see_the_binary_path(self):
        text = (ROOT / 'processors/sandbox.py').read_text()
        allowed = text[text.index("environment = {key: os.environ[key] for key in"):text.index("if key in os.environ}")]
        self.assertIn("*names('PDFCRAFT_BIN')", allowed)
        # Both spellings, so a deployment still on the pre-rename name keeps working.
        self.assertEqual(env_names('PDFCRAFT_BIN'), ('DOCMASTER_PDFCRAFT_BIN', 'PDFMASTER_PDFCRAFT_BIN'))


class Smoke(unittest.TestCase):
    def docker(self, state):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:2] == ['docker', 'inspect']:
                return subprocess.CompletedProcess(command, 0, stdout=state)
            return subprocess.CompletedProcess(command, 0, stdout='c' * 64 + '\n')
        return commands, run

    def test_the_check_runs_in_the_worker_and_compiles(self):
        compile(smoke.PDFCRAFT_CHECK, 'PDFCRAFT_CHECK', 'exec')
        compose = ['docker', 'compose', '-p', 'docmaster-ci-test-only']
        commands, run = self.docker('false 0 true\n')
        with mock.patch.object(smoke, 'run', run):
            smoke.check_pdfcraft(compose, {})
        self.assertEqual(commands[0][:len(compose) + 4], [*compose, 'exec', '-T', 'worker', 'python'])
        self.assertIn('PDFCRAFT_BIN', commands[0][-1])

    def test_an_oom_killed_or_restarted_worker_fails_the_smoke(self):
        _, run = self.docker('true 1 false\n')
        with mock.patch.object(smoke, 'run', run), self.assertRaisesRegex(RuntimeError, 'OOM-killed'):
            smoke.check_pdfcraft(['docker', 'compose'], {})

    def report_of(self, script):
        """The check's own report reader, on a stand-in binary that runs this shell script."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name).resolve()
        binary = root / 'pdfcraft-cli'
        binary.write_text('#!/bin/sh\n' + script)
        binary.chmod(0o755)
        source = smoke.PDFCRAFT_CHECK
        space = {'binary': str(binary), 'json': json, 'subprocess': subprocess}
        exec(source[source.index('def report_of'):source.index('with tempfile.TemporaryDirectory')], space)
        return lambda: space['report_of'](root, {'PATH': os.environ['PATH']}, [{'tool': 'doc_open', 'args': {}}])

    def test_a_crash_in_the_run_shows_its_exit_code_and_stderr(self):
        for output in ('', 'echo \'{"ok": tr\'\n', 'echo Aborted\n'):
            with self.subTest(output=output), self.assertRaises(AssertionError) as caught:
                self.report_of(output + 'echo "memory allocation of 1048576 bytes failed" >&2\nexit 134\n')()
            self.assertIn('134', str(caught.exception))
            self.assertIn('memory allocation of 1048576 bytes failed', str(caught.exception))

    def test_a_step_that_failed_shows_why_and_the_good_steps_stay_out(self):
        report = {'ok': False, 'steps': [{'step': 1, 'tool': 'doc_open', 'status': 'ok', 'result': 'the whole document'},
                                         {'step': 2, 'tool': 'text_edit', 'status': 'error', 'error': 'paragraph 9 is out of range'},
                                         {'step': 3, 'tool': 'doc_save', 'status': 'skipped'}]}
        with self.assertRaises(AssertionError) as caught:
            self.report_of(f"echo '{json.dumps(report)}'\nexit 1\n")()
        message = str(caught.exception)
        self.assertIn('paragraph 9 is out of range', message)
        self.assertIn('doc_save', message)
        self.assertNotIn('the whole document', message)

    def test_a_report_of_nothing_done_or_marked_not_ok_fails_and_a_good_one_returns(self):
        good = {'ok': True, 'steps': [{'step': 1, 'tool': 'doc_open', 'status': 'ok'}]}
        for report in ({'ok': True, 'steps': []}, {'ok': True}, {**good, 'ok': False}):
            with self.subTest(report=report), self.assertRaises(AssertionError):
                self.report_of(f"echo '{json.dumps(report)}'\n")()
        self.assertEqual(self.report_of(f"echo '{json.dumps(good)}'\n")(), good)
        with self.assertRaises(AssertionError):
            self.report_of(f"echo '{json.dumps(good)}'\nexit 1\n")()

    def test_a_failing_check_fails_the_smoke(self):
        def run(command, **kwargs):
            raise subprocess.CalledProcessError(1, command)
        with mock.patch.object(smoke, 'run', run), self.assertRaises(subprocess.CalledProcessError):
            smoke.check_pdfcraft(['docker', 'compose'], {})


if __name__ == '__main__':
    unittest.main()
