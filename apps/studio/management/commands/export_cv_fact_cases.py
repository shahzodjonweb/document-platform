"""Export the CV fact parity corpus: the server's answer for every description of apps/studio/cv/fact_cases.py.

contracts/cv_fact_cases.json is what the web's mirror of the detectors
(document-web useCvSources.ts, the Studio's live ticks) is checked against:
for each text, whether the server finds a name in a draft made from it
(found_name) and whether it gives a contact and a background (facts).
tests/test_cv_facts.py and scripts/verify_contract.py fail when the
committed file is not what this command writes now; export it again, and
copy it to the web, whenever the detectors or the cases change.
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand


def cases():
    """[{text, name, contact, background}] for every text of fact_cases, in the order of the texts."""
    from apps.studio.cv.content import facts, found_name
    from apps.studio.cv.fact_cases import texts
    rows = []
    for text in texts():
        found = facts(text)
        rows.append({'text': text, 'name': bool(found_name({'prompt': text})), 'contact': found['contact'],
                     'background': found['background']})
    return rows


def payload():
    """The file as it is written: a JSON list with one case a line, so a change shows as the lines it changes."""
    return '[\n' + ',\n'.join(json.dumps(row, ensure_ascii=False) for row in cases()) + '\n]\n'


class Command(BaseCommand):
    help = "Export contracts/cv_fact_cases.json: the server's CV facts for every case of apps/studio/cv/fact_cases.py."

    def handle(self, *args, **options):
        target = settings.BASE_DIR / 'contracts' / 'cv_fact_cases.json'
        text = payload()
        target.write_text(text, encoding='utf-8')
        self.stdout.write(f'{target}: {len(json.loads(text))} cases, {len(text.encode())} bytes')
