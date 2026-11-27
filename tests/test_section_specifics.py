"""A new document's sections list their concrete material (specifics) before the body; it never reaches the document.

Measured 2026-11-26 on gpt-6-luna (five briefs in Uzbek, Russian and English, two
runs each, blind judges): documents written around names, dates and mechanisms
were preferred 9 times of 9 over the general text the old prompts gave. The note
is the model's own, so a reply that leaves it out or writes it in another shape
is still the document the customer paid for.
"""
import json

import pytest

from apps.studio import prompting, provider
from apps.studio.domain import DOCUMENT, SLIDES

pytestmark = pytest.mark.django_db
CONFIG = {'mode': 'openai', 'model': 'gpt-offline', 'api_key': 'sk-offline-test-only'}


def draft(sections=3, fmt='pdf', **extra):
    return {'output_locale': 'en', 'prompt': 'Explain how tide tables are read, for a general audience.',
            'source_text': '', 'excerpts': [], 'output_format': fmt,
            'options': {'question_count': 0, 'length': sections},
            'content': {'title': 'Reading tide tables', 'questions': [], 'citations': [],
                        'sections': [{'id': f's{n + 1}', 'heading': '', 'body': '', 'notes': ''}
                                     for n in range(sections)]},
            **extra}


def section_fields(data, feature=DOCUMENT):
    body = prompting.request_body(CONFIG, data, feature)
    return list(body['text']['format']['schema']['properties']['sections']['items']['properties'])


def test_a_new_document_asks_for_specifics_right_before_the_body():
    fields = section_fields(draft())
    assert fields[:4] == ['id', 'heading', 'specifics', 'body']
    assert 'specifics field' in prompting.request_body(CONFIG, draft(), DOCUMENT)['instructions']


@pytest.mark.parametrize('case', ['deck', 'outline', 'plan', 'change', 'repair'])
def test_only_a_new_document_is_asked_for_specifics(case):
    if case == 'deck':
        fields = section_fields(draft(fmt='pptx'), SLIDES)
    elif case == 'outline':
        fields = section_fields(draft(), 'ai.outline')
    elif case == 'plan':
        fields = section_fields(draft(_stage='plan'))
    else:
        written = draft()
        for section in written['content']['sections']:
            section.update(heading='Tides', body='High water comes twice a day.')
        revision = {'request': 'Make it shorter', 'original_prompt': written['prompt']}
        fields = section_fields({**written, 'revision': revision, **({'_stage': 'repair'} if case == 'repair' else {})})
    assert 'specifics' not in fields


class Opener:
    """Answers every call with the sections asked for, each given `specifics` as `note` says."""

    def __init__(self, note):self.note = note

    def open(self, request, timeout):
        body = json.loads(request.data)
        ids = [s['id'] for s in json.loads(body['input'])['outline']['sections']]
        sections = []
        for number, section_id in enumerate(ids, 1):
            section = {'id': section_id, 'heading': f'Part {number}', 'body': f'Body {number}.'}
            if self.note != 'missing':
                section['specifics'] = ['Spring tides', 'Chart datum'] if self.note == 'list' else 'not a list'
            sections.append(section)
        reply = {'title': 'Reading tide tables', 'answer_supported': True, 'sections': sections}
        payload = {'status': 'completed', 'usage': {'input_tokens': 100, 'output_tokens': 50},
                   'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(reply)}]}]}

        class Response:
            def __enter__(self):return self
            def __exit__(self, *args):return False
            def read(self, limit):return json.dumps(payload).encode()
        return Response()


@pytest.mark.parametrize('note', ['list', 'missing', 'malformed'])
def test_the_document_is_read_with_or_without_specifics_and_never_keeps_them(monkeypatch, note):
    monkeypatch.setattr(provider.urllib.request, 'build_opener', lambda *args: Opener(note))
    answer, usage = provider.generate(CONFIG, draft(), DOCUMENT, 'offline-specifics', token_limit=120000)
    assert [s['body'] for s in answer['sections']] == ['Body 1.', 'Body 2.', 'Body 3.']
    assert all('specifics' not in s for s in answer['sections'])
    assert usage == {'input_tokens': 100, 'output_tokens': 50}
