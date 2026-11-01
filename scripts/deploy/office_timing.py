#!/usr/bin/env python3
"""LibreOffice timings for the deck editor's slide previews, for the CI log only.

On a pull request, container_smoke.py runs this inside the read-only worker after
every check that can fail the build, and nothing here can fail it: each step has
its own deadline and try/except, says what happened and kills every soffice it
started, and the whole probe stays within BUDGET seconds. `grep OFFICE-TIMING`
finds the table.

Three decks (one slide; 12 text slides; 60 slides with a 1600 px JPEG on each)
go through these modes, under the processor child's limits and environment:

    cold      a fresh profile, what _office_pdf does for every job today
    warm      a profile that has run before
    resident  `soffice --accept` holding that profile, then `soffice --convert-to`
              with the same profile: does the second process hand the file over,
              does it exit, does the PDF appear, does the instance outlive it?
    held      the same with a document open in the instance, tried only when the
              resident ends with its conversion, which LibreOffice's dispatcher
              does to an office that a conversion leaves with no open document

The small decks come first, so a slow 60-slide conversion costs only its own
numbers. It is converted once in each mode and again while the budget lasts.
"""
from collections import namedtuple
import glob
import os
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback

BUDGET = 170
STEP_SECONDS = 45
READY_SECONDS = 30
VERSION_SECONDS = 30
# A client still there this long after its PDF is reported as one that stays.
GRACE_SECONDS = 10
# And the second a client gets to hand over before it counts as gone with no PDF.
LEFT_SECONDS = 1
SURVIVAL_SECONDS = 1.5
SAMPLE_SECONDS = 0.05
# RLIMIT_CPU is per process, and a resident adds up every conversion it does.
CPU_SECONDS = 600
PIPE = 'pdfmaster_probe'
# The acceptor's socket: LibreOffice's pipes ignore TMPDIR.
SOCKET_FOLDERS = ('/tmp', '/var/tmp')
PROC = '/proc'
# processors/engine.py _office_pdf
CONVERT = ('--headless', '--nologo', '--nodefault', '--nofirststartwizard', '--convert-to', 'pdf', '--outdir')
Deck = namedtuple('Deck', 'name path')
LINES = (('Corbel', 'Покажите две группы счётными предметами и посчитайте общее количество.'),
         ('Calibri', 'Объясните результат полным предложением, Ikki va uchta donani birlashtiring.'),
         ('Arial', 'Bu qator lotin yozuvida: o‘quvchilar g‘oyani muhokama qiladi.'),
         ('Cambria', 'Заголовок и обычный текст на одном слайде.'))


def say(*parts):
    print(*parts, flush=True)


def find_soffice():
    return os.environ.get('PDFMASTER_SOFFICE_BIN') or shutil.which('libreoffice') or shutil.which('soffice')


def sockets():
    return [path for folder in SOCKET_FOLDERS for path in glob.glob(f'{folder}/OSL_PIPE_*{PIPE}*')]


def clear_sockets():
    for path in sockets():
        try:
            os.unlink(path)
        except OSError:
            pass


def finished(path):
    """A whole PDF: the trailer is written last."""
    try:
        with open(path, 'rb') as stream:
            stream.seek(max(0, os.fstat(stream.fileno()).st_size - 1024))
            return b'%%EOF' in stream.read()
    except OSError:
        return False


def kill(process):
    """The whole group: the launcher, oosplash and soffice.bin share it."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def text_deck(path, slides):
    """Our decks' fonts by name, in Cyrillic and Uzbek Latin, on python-pptx's plain template."""
    from pptx import Presentation
    deck = Presentation()
    for number in range(1, slides + 1):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = f'Слайд {number}: Самарканд и Ташкент'
        slide.shapes.title.text_frame.paragraphs[0].runs[0].font.name = 'Cambria'
        body = slide.placeholders[1].text_frame
        for index, (font, line) in enumerate(LINES):
            paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
            paragraph.add_run().text = line
            paragraph.runs[0].font.name = font
    deck.save(path)


def photo_deck(path, slides, folder):
    """One distinct 1600 px JPEG of about 400 KB, the size the deck pipeline prepares, on every slide."""
    from PIL import Image, ImageChops
    from pptx import Presentation
    size = (1600, 1000)
    grain = Image.effect_noise(size, 32)
    deck = Presentation()
    for number in range(1, slides + 1):
        bands = [ImageChops.add(Image.effect_noise((80, 50), 70).resize(size, Image.Resampling.BICUBIC),
                                ImageChops.offset(grain, number * 7 + shift, number * 3), scale=2) for shift in (0, 11, 23)]
        picture = Path(folder) / f'photo-{number}.jpg'
        Image.merge('RGB', bands).save(picture, 'JPEG', quality=76)
        slide = deck.slides.add_slide(deck.slide_layouts[5])
        slide.shapes.title.text = f'Слайд {number}'
        slide.shapes.add_picture(str(picture), 0, deck.slide_height // 4, height=deck.slide_height // 2)
        picture.unlink()
    deck.save(path)


def build_decks(folder):
    one, text, photos = folder / 'one.pptx', folder / 'text.pptx', folder / 'photos.pptx'
    text_deck(one, 1)
    text_deck(text, 12)
    photo_deck(photos, 60, folder)
    return Deck('1 slide', one), Deck('12 text', text), Deck('60 photos', photos)


def say_fonts(path):
    """The fonts LibreOffice put in place of the deck's, as the PDF names them."""
    try:
        from pypdf import PdfReader
        names = set()
        for page in PdfReader(path).pages:
            for font in page['/Resources']['/Font'].values():
                names.add(str(font.get_object()['/BaseFont']).split('+')[-1])
        say('OFFICE-TIMING fonts in the 1-slide PDF:', ', '.join(sorted(names)) or 'none')
    except Exception as error:
        say('OFFICE-TIMING fonts in the 1-slide PDF not read:', type(error).__name__)


class Usage(threading.Thread):
    """Resident and virtual memory and CPU of process groups, from /proc; nothing where there is no /proc."""

    def __init__(self, *groups):
        super().__init__(daemon=True)
        self.groups = set(groups)
        self.halt = threading.Event()
        self.peak = self.virtual = self.last = None
        self.first, self.latest, self.office_groups = {}, {}, set()
        self.ticks = os.sysconf('SC_CLK_TCK') if 'SC_CLK_TCK' in os.sysconf_names else 100

    def run(self):
        while True:
            self.sample()
            if self.halt.wait(SAMPLE_SECONDS):
                return

    def sample(self):
        if not os.path.isdir(PROC):
            return
        total = 0
        for pid in filter(str.isdigit, os.listdir(PROC)):
            try:
                with open(f'{PROC}/{pid}/stat') as stream:
                    stat = stream.read()
                fields = stat[stat.rindex(')') + 2:].split()  # state ppid pgrp ... utime stime; a name can hold anything
                if int(fields[2]) not in self.groups:
                    continue
                with open(f'{PROC}/{pid}/status') as stream:
                    status = stream.read()
            except (OSError, ValueError, IndexError):
                continue  # gone between the listing and the read
            cpu = (int(fields[11]) + int(fields[12])) / self.ticks
            self.first.setdefault(pid, cpu)
            self.latest[pid] = cpu
            if stat[stat.index('(') + 1:stat.rindex(')')] == 'soffice.bin':
                self.office_groups.add(int(fields[2]))
            found = re.search(r'VmRSS:\s+(\d+)', status)
            total += int(found.group(1)) if found else 0
            found = re.search(r'VmPeak:\s+(\d+)', status)
            self.virtual = max(self.virtual or 0, int(found.group(1)) // 1024 if found else 0)
        self.last = total // 1024
        self.peak = max(self.peak or 0, self.last)

    def finish(self):
        self.halt.set()
        self.join(timeout=5)

    def cpu(self):
        """The CPU seconds used since each process was first seen."""
        return sum(self.latest[pid] - self.first[pid] for pid in self.latest) if self.latest else None


class Probe:
    def __init__(self, soffice, scratch, limits, deadline):
        self.soffice, self.scratch, self.limits, self.deadline = soffice, Path(scratch), limits, deadline
        self.rows, self.started, self.profile, self.held = [], [], None, None
        self.env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL') if key in os.environ}
        for name, folder in (('HOME', 'home'), ('TMPDIR', 'tmp')):
            self.env[name] = str(self.scratch / folder)
            os.makedirs(self.env[name], exist_ok=True)
        # sandbox._run gives the processors child this, and LibreOffice inherits it.
        self.env['MALLOC_ARENA_MAX'] = '2'

    def left(self):
        return self.deadline - time.monotonic()

    def spawn(self, command, log):
        """In a session of its own, so its whole tree can be killed. No Usage thread runs during this fork."""
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=self.env,
                                   cwd=self.scratch, start_new_session=True, preexec_fn=self.limits)
        self.started.append(process)
        return process

    def stop_all(self):
        for process in self.started:
            kill(process)
        self.started.clear()
        clear_sockets()

    def record(self, **row):
        self.rows.append(row)
        say('office-timing:', ' '.join(f'{key}={round(value, 2) if isinstance(value, float) else value}' for key, value in row.items() if value is not None))

    def version(self):
        output = self.scratch / 'version.txt'
        with open(output, 'wb') as log:
            process = self.spawn([self.soffice, '--version'], log)
        try:
            process.wait(timeout=VERSION_SECONDS)
        finally:
            self.stop_all()
        return output.read_text(errors='replace').strip()

    def fresh_profile(self):
        profile = Path(tempfile.mkdtemp(prefix='profile-', dir=self.scratch))
        profile.rmdir()  # like _office_pdf, a folder that does not exist yet
        return profile

    def convert(self, mode, deck, profile, until, instance=None, on_pdf=None):
        """One soffice --convert-to, timed to the client's exit and to the finished PDF."""
        out = Path(tempfile.mkdtemp(prefix='out-', dir=self.scratch))
        target, log_path = out / (deck.path.stem + '.pdf'), out / 'log.txt'
        began, left_at, pdf_at, returncode = time.monotonic(), None, None, None
        with open(log_path, 'wb') as log:
            client = self.spawn([self.soffice, '-env:UserInstallation=' + profile.as_uri(), *CONVERT, str(out), str(deck.path)], log)
        usage = Usage(client.pid, *([instance.pid] if instance else []))
        usage.start()
        try:
            while (now := time.monotonic()) < until:
                if left_at is None and client.poll() is not None:
                    left_at, returncode = now, client.returncode
                if pdf_at is None and finished(target):
                    pdf_at = now
                    if on_pdf:
                        on_pdf(target)
                if left_at is not None and pdf_at is not None:
                    break
                # A client that stays after its PDF gets a while to leave. One that
                # left cleanly with no PDF may have handed the file to a running
                # instance, which gets a few times what the deck takes without one.
                if pdf_at is not None and now - pdf_at > GRACE_SECONDS:
                    break
                if left_at is not None and now - left_at > (self.patience(deck) if instance and not returncode and instance.poll() is None else LEFT_SECONDS):
                    break
                time.sleep(0.02)
            alive = None
            if instance is not None:
                time.sleep(min(SURVIVAL_SECONDS, max(0, self.left())))
                alive = instance.poll() is None
            kill(client)
            self.started.remove(client)
        finally:
            usage.finish()
        note = []
        if left_at is None:
            note.append('client did not exit')
        elif returncode:
            note.append(f'client exit code {returncode}')
        if pdf_at is None:
            note.append('no PDF: ' + log_path.read_bytes()[-120:].decode('utf-8', 'replace').replace('\n', ' '))
        self.record(mode=mode, deck=deck.name, exit=None if left_at is None else left_at - began, pdf=None if pdf_at is None else pdf_at - began,
                    peak=usage.peak, end=usage.last if instance is not None else None, virtual=usage.virtual, cpu=usage.cpu(),
                    handoff=None if instance is None or usage.peak is None else client.pid not in usage.office_groups,
                    alive=alive, note='; '.join(note) or None)
        shutil.rmtree(out, ignore_errors=True)

    def patience(self, deck):
        return 3 * max((row['pdf'] for row in self.rows if row['deck'] == deck.name and row.get('pdf')), default=10) + 5

    def another_run(self, number, mode, deck, until, reserve):
        """The first run always. Another when the last one worked and it fits, with room for that many runs of another mode after it."""
        if not number:
            return True
        last = next((row for row in reversed(self.rows) if row['mode'] == mode and row['deck'] == deck.name), {})
        if not last.get('pdf') or last.get('exit') is None:
            return False
        cost = max(last['exit'], last['pdf'])
        return time.monotonic() + cost * 1.3 + 1 < until and self.left() > cost * (1.3 + reserve) + 5

    def cold(self, deck, runs, until, reserve=0):
        for number in range(runs):
            if not self.another_run(number, 'cold', deck, until, reserve):
                return
            profile = self.fresh_profile()
            # The first cold run's profile is the one the warm and resident runs reuse.
            self.profile = self.profile or profile
            self.convert('cold', deck, profile, until, on_pdf=say_fonts if deck.name == '1 slide' else None)

    def warm(self, deck, runs, until, reserve=0):
        self.profile = self.profile or self.fresh_profile()
        for number in range(runs):
            if not self.another_run(number, 'warm', deck, until, reserve):
                return
            self.convert('warm', deck, self.profile, until)

    def instance(self, mode, deck, runs, until, reserve, documents=()):
        self.profile = self.profile or self.fresh_profile()
        running = None
        for number in range(runs):
            if not self.another_run(number, mode, deck, until, reserve):
                return
            if running is None or running.poll() is not None:
                running = self.start_instance(mode, documents)
            self.convert(mode, deck, self.profile, until, instance=running)

    def start_instance(self, mode, documents):
        """Started, and timed until its acceptor's socket exists."""
        clear_sockets()
        began = time.monotonic()
        with open(self.scratch / 'instance.log', 'ab') as log:
            running = self.spawn([self.soffice, '-env:UserInstallation=' + self.profile.as_uri(), '--headless', '--invisible', '--norestore',
                                  f'--accept=pipe,name={PIPE};urp;', *map(str, documents)], log)
        ready = None
        while time.monotonic() - began < min(READY_SECONDS, max(0, self.left())) and running.poll() is None:
            if sockets():
                ready = time.monotonic() - began
                break
            time.sleep(0.02)
        tail = (self.scratch / 'instance.log').read_bytes()[-120:].decode('utf-8', 'replace').replace('\n', ' ')
        self.record(mode=mode, deck='start', exit=ready, alive=running.poll() is None, note=None if ready is not None else f'no socket: {tail}')
        return running

    def resident(self, deck, runs, until, reserve=0):
        self.instance('resident', deck, runs, until, reserve)

    def held_open(self, deck, runs, until, reserve=0):
        self.instance('held', deck, runs, until, reserve, documents=(self.held,))

    def step(self, mode, deck, runs=1, seconds=None, reserve=0):
        """One mode on one deck: its own deadline and try/except, and nothing of it left running."""
        if self.left() < 3:
            self.record(mode=mode, deck=deck.name, note='skipped: out of budget')
            return
        action = {'cold': self.cold, 'warm': self.warm, 'resident': self.resident, 'held': self.held_open}[mode]
        try:
            action(deck, runs, time.monotonic() + min(seconds or STEP_SECONDS, self.left()), reserve=reserve)
        except Exception:
            self.record(mode=mode, deck=deck.name, note='failed: ' + traceback.format_exc(limit=1).replace('\n', ' ')[-300:])
        finally:
            self.stop_all()

    def run_all(self, one, text, photos):
        self.step('cold', one)
        self.step('warm', one)
        self.step('resident', one)
        self.step('cold', text)
        self.step('warm', text, runs=3)
        self.step('resident', text, runs=3)
        keeper = 'resident'
        if any(row['mode'] == 'resident' and row.get('alive') is False for row in self.rows):
            keeper = 'held'
            self.held = self.scratch / 'held.pptx'
            shutil.copyfile(one.path, self.held)
            self.step('held', one)
            self.step('held', text, runs=3)
        self.step('cold', photos, seconds=80)
        if any(row['mode'] == keeper and row.get('pdf') for row in self.rows):
            self.step(keeper, photos, runs=3, seconds=100, reserve=1)
        else:
            self.record(mode=keeper, deck=photos.name, note='skipped: no PDF on the small decks')
        self.step('warm', photos, runs=3, seconds=70)


def seconds(value):
    if value is None:
        return '-'
    return f'{value:.2f}' if value < 10 else f'{value:.1f}'


def table(rows):
    """One line per mode and deck, with each run's seconds in order."""
    groups = {}
    for row in rows:
        groups.setdefault((row['mode'], row['deck']), []).append(row)
    lines = [f'{"mode":<9}{"deck":<11}{"runs":<5}{"exit_s":<21}{"pdf_s":<21}{"peak_mb":<8}{"end_mb":<7}{"vm_mb":<7}{"cpu_s":<6}{"handoff":<8}{"alive":<7}note']
    for (mode, deck), runs in groups.items():
        def values(key):
            return [run[key] for run in runs if run.get(key) is not None]

        def flags(key):
            return '/'.join('-' if run.get(key) is None else 'y' if run[key] else 'n' for run in runs)
        lines.append(f'{mode:<9}{deck:<11}{len(runs):<5}'
                     f'{"/".join(seconds(run.get("exit")) for run in runs):<21}{"/".join(seconds(run.get("pdf")) for run in runs):<21}'
                     f'{max(values("peak"), default="-"):<8}{(values("end") or ["-"])[-1]:<7}{max(values("virtual"), default="-"):<7}'
                     f'{seconds(statistics.median(values("cpu"))) if values("cpu") else "-":<6}{flags("handoff"):<8}{flags("alive"):<7}'
                     + '; '.join(dict.fromkeys(values('note'))))
    return lines


def machine():
    """What the numbers were measured on, as far as the container can tell."""
    facts = [f'{os.cpu_count()} cores']
    for name in ('cpu.max', 'memory.max', 'memory.peak'):
        try:
            facts.append(f'{name} {Path("/sys/fs/cgroup", name).read_text().strip()}')
        except OSError:
            pass
    return ', '.join(facts)


def main(soffice=None, limits=None, build=build_decks, budget=BUDGET):
    began = time.monotonic()
    scratch, probe = None, None
    try:
        soffice = soffice or find_soffice()
        if not soffice:
            say('OFFICE-TIMING no LibreOffice in this image')
            return 0
        if limits is None:
            # A child's limits, except the CPU a resident adds up. Imported this late because it loads the engines.
            os.environ['PDFMASTER_CPU_SECONDS'] = str(CPU_SECONDS)
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from processors.__main__ import apply_limits as limits
        root = Path(os.environ.get('PRIVATE_STORAGE_ROOT') or tempfile.gettempdir()).resolve() / 'scratch'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        scratch = Path(tempfile.mkdtemp(prefix='office-timing-', dir=root))
        probe = Probe(soffice, scratch, limits, began + budget)
        say('OFFICE-TIMING', probe.version(), f'({seconds(time.monotonic() - began)} s so far)')
        decks = build(scratch)
        say('OFFICE-TIMING decks:', ', '.join(f'{deck.name} {deck.path.stat().st_size // 1024} KB' for deck in decks), f'({seconds(time.monotonic() - began)} s so far)')
        probe.run_all(*decks)
    except Exception:
        say('OFFICE-TIMING stopped early:', traceback.format_exc(limit=2).replace('\n', ' ')[-400:])
    finally:
        if probe:
            probe.stop_all()
            say('OFFICE-TIMING', machine(), f'used {seconds(time.monotonic() - began)} s of {budget}')
            for line in table(probe.rows):
                say('OFFICE-TIMING', line)
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
