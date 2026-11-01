"""The LibreOffice probe reports whatever happens, leaves nothing running and never fails the build."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('office_timing', ROOT / 'scripts/deploy/office_timing.py')
office_timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(office_timing)
spec = importlib.util.spec_from_file_location('timing_container_smoke', ROOT / 'scripts/deploy/container_smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
# A stand-in for soffice, in shell because it must fork like the real launcher:
# a child in the same group that only a kill of the whole group can reach.
# `behaviour` names what it does; every process it leaves is noted in `pids`.
FAKE = r"""#!/bin/sh
here=@HERE@
behaviour=$(cat "$here/behaviour")
echo $$ >> "$here/pids"
outdir=''; document=''; accept=''; convert=''; next=''
for arg in "$@"; do
    case "$next" in outdir) outdir=$arg; next=''; continue;; skip) next=''; continue;; esac
    case "$arg" in
        --version) echo 'LibreOffice 7.4.7.2 fake'; exit 0;;
        --accept=*) accept=1;;
        --convert-to) convert=1; next=skip;;
        --outdir) next=outdir;;
        -*) ;;
        *) document=$arg;;
    esac
done
linger() { sleep 300 & echo $! >> "$here/pids"; wait; }
if [ -n "$accept" ]; then
    : > "$here/OSL_PIPE_501_pdfmaster_probe"
    if [ "$behaviour" = ends ] && [ -z "$document" ]; then
        while [ ! -e "$here/converted" ]; do sleep 0.02; done
        rm -f "$here/converted"
        exit 0
    fi
    linger
fi
if [ -n "$convert" ]; then
    case "$behaviour" in
        hangs) linger;;
        fails) echo 'Error: source file could not be loaded'; exit 3;;
        loses) [ -e "$here/OSL_PIPE_501_pdfmaster_probe" ] && exit 0;;
    esac
    name=$(basename "$document"); name=${name%.pptx}
    printf '%%PDF-1.7\nfake\n%%%%EOF\n' > "$outdir/$name.pdf"
    [ -e "$here/OSL_PIPE_501_pdfmaster_probe" ] && touch "$here/converted"
    [ "$behaviour" = stays ] && linger
    exit 0
fi
"""


class Probe(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.here = Path(folder.name).resolve()
        self.soffice = self.here / 'soffice'
        self.soffice.write_text(FAKE.replace('@HERE@', shlex.quote(str(self.here))))
        self.soffice.chmod(self.soffice.stat().st_mode | stat.S_IEXEC)
        self.storage = self.here / 'storage'
        patches = (mock.patch.object(office_timing, 'SOCKET_FOLDERS', (str(self.here),)), mock.patch.object(office_timing, 'SURVIVAL_SECONDS', 0.1),
                   mock.patch.object(office_timing, 'GRACE_SECONDS', 0.2), mock.patch.object(office_timing, 'LEFT_SECONDS', 0.1), mock.patch.object(office_timing, 'SAMPLE_SECONDS', 0.01),
                   mock.patch.dict(os.environ, {'PRIVATE_STORAGE_ROOT': str(self.storage)}))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def build(self, folder):
        decks = []
        for name, stem in (('1 slide', 'one'), ('12 text', 'text'), ('60 photos', 'photos')):
            path = folder / f'{stem}.pptx'
            path.write_bytes(b'deck')
            decks.append(office_timing.Deck(name, path))
        return decks

    def probe(self, behaviour, budget=30):
        (self.here / 'behaviour').write_text(behaviour)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = office_timing.main(str(self.soffice), lambda: None, self.build, budget)
        self.assertEqual(code, 0)
        return output.getvalue()

    def table(self, output):
        return [line for line in output.splitlines() if line.startswith('OFFICE-TIMING ')]

    def row(self, output, mode, deck):
        rows = [line for line in self.table(output) if line.startswith(f'OFFICE-TIMING {mode:<9}{deck} ')]
        self.assertEqual(len(rows), 1, output)
        return rows[0]

    def seconds(self, output, mode, deck, column):
        """Each run's seconds in the exit_s (0) or pdf_s (1) column."""
        return self.row(output, mode, deck).removeprefix(f'OFFICE-TIMING {mode:<9}{deck} ').split()[1 + column].split('/')

    def assert_nothing_left(self):
        pids = [int(line) for line in (self.here / 'pids').read_text().split()]
        self.assertTrue(pids)
        deadline = time.monotonic() + 3
        for pid in pids:
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                except PermissionError:  # macOS: a zombie waiting for launchd
                    break
                self.assertLess(time.monotonic(), deadline, f'{pid} of {pids} is still running')
                time.sleep(0.02)
        self.assertEqual(list(self.here.glob('OSL_PIPE_*')), [])
        self.assertEqual(list((self.storage / 'scratch').iterdir()), [])

    def test_every_mode_is_timed_on_every_deck_and_nothing_is_left_running(self):
        output = self.probe('normal')
        runs = {('cold', '1 slide'): 1, ('warm', '1 slide'): 1, ('resident', '1 slide'): 1, ('cold', '12 text'): 1, ('warm', '12 text'): 3, ('resident', '12 text'): 3,
                ('cold', '60 photos'): 1, ('warm', '60 photos'): 3, ('resident', '60 photos'): 3}
        for (mode, deck), count in runs.items():
            for column in (0, 1):
                values = self.seconds(output, mode, deck, column)
                self.assertEqual(len(values), count, (mode, deck))
                self.assertTrue(all(float(value) >= 0 for value in values))
        self.assertTrue(self.row(output, 'resident', 'start'))
        self.assertNotIn('no PDF', output)
        self.assertNotIn('OFFICE-TIMING held', output)
        self.assertIn('LibreOffice 7.4.7.2 fake', output)
        self.assert_nothing_left()

    def test_an_instance_that_ends_with_its_conversion_is_seen_and_a_held_one_is_tried(self):
        output = self.probe('ends')
        self.assertIn('/n', self.row(output, 'resident', '12 text'))
        self.assertIn('y/y/y', self.row(output, 'held', '12 text'))
        self.assertIn('y/y/y', self.row(output, 'held', '60 photos'))
        self.assert_nothing_left()

    def test_a_client_that_stays_after_its_pdf_is_killed_and_reported(self):
        output = self.probe('stays')
        self.assertIn('client did not exit', self.row(output, 'cold', '1 slide'))
        self.assertNotIn('no PDF', self.row(output, 'cold', '1 slide'))
        self.assert_nothing_left()

    def test_a_conversion_that_hangs_costs_only_its_own_deadline(self):
        with mock.patch.object(office_timing, 'STEP_SECONDS', 0.2):
            began = time.monotonic()
            output = self.probe('hangs', budget=4)
        self.assertLess(time.monotonic() - began, 20)
        row = self.row(output, 'cold', '1 slide')
        self.assertIn('client did not exit', row)
        self.assertIn('no PDF', row)
        self.assert_nothing_left()

    def test_a_client_that_hands_over_a_file_nobody_converts_is_not_repeated(self):
        with mock.patch.object(office_timing, 'STEP_SECONDS', 0.5):
            output = self.probe('loses', budget=8)
        self.assertEqual(len(self.seconds(output, 'resident', '12 text', 0)), 1)
        self.assertIn('no PDF', self.row(output, 'resident', '12 text'))
        self.assertIn('skipped: no PDF on the small decks', self.row(output, 'resident', '60 photos'))
        self.assertNotIn('no PDF', self.row(output, 'warm', '12 text'))
        self.assert_nothing_left()

    def test_a_failed_conversion_is_reported_with_the_end_of_its_output(self):
        output = self.probe('fails')
        row = self.row(output, 'warm', '12 text')
        self.assertIn('client exit code 3', row)
        self.assertIn('could not be loaded', row)
        self.assert_nothing_left()

    def test_the_budget_ends_the_probe_with_what_it_has(self):
        output = self.probe('hangs', budget=0)
        self.assertIn('skipped: out of budget', output)
        self.assertIn('used', output)
        self.assert_nothing_left()

    def test_a_mode_that_raises_does_not_stop_the_others(self):
        real = office_timing.Probe.cold

        def broken(self_, deck, runs, until, reserve=0):
            if deck.name == '12 text':
                raise RuntimeError('boom')
            return real(self_, deck, runs, until, reserve)
        with mock.patch.object(office_timing.Probe, 'cold', broken):
            output = self.probe('normal')
        self.assertIn('boom', self.row(output, 'cold', '12 text'))
        self.assertNotIn('boom', self.row(output, 'warm', '12 text'))
        self.assert_nothing_left()

    def test_decks_that_cannot_be_built_end_it_quietly(self):
        (self.here / 'behaviour').write_text('normal')

        def build(folder):
            raise ValueError('no decks today')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(office_timing.main(str(self.soffice), lambda: None, build, 10), 0)
        self.assertIn('stopped early', output.getvalue())
        self.assertIn('no decks today', output.getvalue())

    def test_an_image_without_libreoffice_is_said_and_is_not_a_failure(self):
        output = io.StringIO()
        with mock.patch.object(office_timing, 'find_soffice', return_value=None), contextlib.redirect_stdout(output):
            self.assertEqual(office_timing.main(limits=lambda: None), 0)
        self.assertIn('no LibreOffice', output.getvalue())

    def test_the_limits_reach_soffice_and_the_env_is_an_allowlist_at_scratch(self):
        seen = {}
        real = office_timing.subprocess.Popen

        def spying(command, **kwargs):
            seen.setdefault('env', kwargs['env'])
            seen.setdefault('preexec_fn', kwargs['preexec_fn'])
            seen.setdefault('session', kwargs['start_new_session'])
            return real(command, **kwargs)
        limits = lambda: None
        (self.here / 'behaviour').write_text('normal')
        with mock.patch.object(office_timing.subprocess, 'Popen', spying), mock.patch.dict(os.environ, {'DATABASE_URL': 'postgresql://secret', 'TELEGRAM_BOT_TOKEN': 'secret'}), contextlib.redirect_stdout(io.StringIO()):
            office_timing.main(str(self.soffice), limits, self.build, 30)
        self.assertIs(seen['preexec_fn'], limits)
        self.assertTrue(seen['session'])
        self.assertLessEqual(set(seen['env']), {'PATH', 'LANG', 'LC_ALL', 'HOME', 'TMPDIR', 'MALLOC_ARENA_MAX'})
        self.assertTrue(seen['env']['HOME'].startswith(str(self.storage)) and seen['env']['TMPDIR'].startswith(str(self.storage)))

    @unittest.skipUnless(importlib.util.find_spec('pptx') and importlib.util.find_spec('PIL'), 'needs python-pptx and Pillow')
    def test_the_decks_have_the_slides_and_the_pictures_asked_for(self):
        import zipfile
        from PIL import Image
        from pptx import Presentation
        with tempfile.TemporaryDirectory() as folder:
            one, text, photos = office_timing.build_decks(Path(folder))
            self.assertEqual([len(Presentation(deck.path).slides) for deck in (one, text, photos)], [1, 12, 60])
            with zipfile.ZipFile(photos.path) as bundle:
                pictures = [item for item in bundle.infolist() if '/media/' in item.filename]
                self.assertEqual(len(pictures), 60)
                self.assertLess(max(item.file_size for item in pictures), 450 * 1024)
                with bundle.open(pictures[0]) as stream:
                    self.assertEqual(Image.open(stream).size[0], 1600)
            self.assertEqual(sorted(path.name for path in Path(folder).iterdir()), ['one.pptx', 'photos.pptx', 'text.pptx'])


class Usage(unittest.TestCase):
    def process(self, proc, pid, name, group, utime, rss, peak):
        folder = proc / str(pid)
        folder.mkdir()
        fields = ['S', '1', str(group), str(group), '0', '-1', '4194304', '1', '0', '0', '0', str(utime), '50', '0', '0', '20', '0', '1', '0']
        (folder / 'stat').write_text(f'{pid} ({name}) ' + ' '.join(fields) + '\n')
        (folder / 'status').write_text(f'Name:\t{name}\nVmPeak:\t  {peak} kB\nVmRSS:\t  {rss} kB\nThreads:\t3\n')

    def test_memory_and_cpu_add_up_over_the_process_groups_only(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(office_timing, 'PROC', folder):
            proc = Path(folder)
            (proc / 'self').mkdir()
            (proc / 'cpuinfo').write_text('not a process')
            self.process(proc, 10, 'oosplash', 10, 100, 10240, 20480)
            self.process(proc, 11, 'soffice.bin', 10, 200, 204800, 1048576)
            self.process(proc, 20, 'odd) (name', 20, 10, 1024, 2048)
            self.process(proc, 30, 'runworker', 30, 900, 512000, 900000)
            usage = office_timing.Usage(10, 20)
            usage.sample()
            self.assertEqual((usage.peak, usage.virtual, usage.office_groups), (211, 1024, {10}))
            # A later sample: the instance's CPU counts from the first time it was seen.
            (proc / '20' / 'stat').unlink()
            (proc / '11' / 'stat').write_text('11 (soffice.bin) S 10 10 10 0 -1 4194304 1 0 0 0 450 50 0 0 20 0 1 0\n')
            (proc / '11' / 'status').write_text('VmPeak:\t 1048576 kB\nVmRSS:\t 102400 kB\n')
            usage.sample()
            self.assertEqual((usage.peak, usage.last), (211, 110))
            self.assertAlmostEqual(usage.cpu(), 250 / usage.ticks)

    def test_a_machine_without_proc_leaves_it_blank(self):
        with mock.patch.object(office_timing, 'PROC', '/nonexistent/proc'):
            usage = office_timing.Usage(10)
            usage.sample()
        self.assertIsNone(usage.peak)
        self.assertIsNone(usage.cpu())


class Table(unittest.TestCase):
    def test_a_row_shows_each_run_and_the_worst_memory(self):
        rows = [{'mode': 'warm', 'deck': '12 text', 'exit': 2.5, 'pdf': 2.4, 'peak': 300, 'cpu': 2.0},
                {'mode': 'warm', 'deck': '12 text', 'exit': 12.25, 'pdf': None, 'peak': 320, 'cpu': 2.0, 'note': 'no PDF'}]
        header, line = office_timing.table(rows)
        self.assertTrue(header.startswith('mode'))
        self.assertIn('2.50/12.2', line)
        self.assertIn('2.40/-', line)
        self.assertIn('320', line)
        self.assertTrue(line.endswith('no PDF'))

    def test_the_unknown_stays_blank(self):
        _, line = office_timing.table([{'mode': 'cold', 'deck': '1 slide', 'note': 'skipped: out of budget'}])
        self.assertIn('skipped', line)
        self.assertEqual(office_timing.seconds(None), '-')


class Smoke(unittest.TestCase):
    pull_request = {'GITHUB_EVENT_NAME': 'pull_request'}

    def test_the_probe_runs_in_the_worker_with_a_limit(self):
        seen = {}

        def run(command, **kwargs):
            seen.update(command=command, **kwargs)
        with mock.patch.object(smoke, 'run', run):
            smoke.office_timings(['docker', 'compose'], self.pull_request)
        self.assertEqual(seen['command'], ['docker', 'compose', 'exec', '-T', 'worker', 'python', 'scripts/deploy/office_timing.py'])
        self.assertLessEqual(seen['timeout'], 240)
        self.assertLess(office_timing.BUDGET, seen['timeout'])

    def test_nothing_that_happens_to_the_probe_fails_the_build(self):
        for error in (subprocess.CalledProcessError(1, 'docker'), subprocess.TimeoutExpired('docker', 210), OSError('no docker'), ValueError('anything')):
            with self.subTest(error=type(error).__name__), mock.patch.object(smoke, 'run', side_effect=error), contextlib.redirect_stdout(io.StringIO()) as output:
                smoke.office_timings(['docker', 'compose'], self.pull_request)
                self.assertIn('OFFICE-TIMING', output.getvalue())

    def test_only_a_pull_request_runs_it_so_no_deploy_waits_for_it(self):
        for env in ({'GITHUB_EVENT_NAME': 'push'}, {'GITHUB_EVENT_NAME': 'workflow_dispatch'}, {}):
            with self.subTest(env=env), mock.patch.object(smoke, 'run') as run:
                smoke.office_timings(['docker', 'compose'], env)
                run.assert_not_called()

    def test_it_runs_after_every_check_that_can_fail_the_build(self):
        text = (ROOT / 'scripts/deploy/container_smoke.py').read_text()
        order = [text.index(name) for name in ('check_scanner(compose, env)\n                check_pdfcraft', 'check_pdfcraft(compose, env)\n                check_reader', 'check_reader(compose, env)\n                wait_for', 'wait_for_cleanup_cycle(compose, env)\n                office_timings')]
        self.assertEqual(order, sorted(order))


if __name__ == '__main__':
    unittest.main()
