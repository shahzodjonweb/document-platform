"""Every AI feature must be able to ask the provider and accept its answer.

This exercises the request/response contract for all provider-dependent
features without calling a model: a live check can only ever cover a handful of
features before the cost becomes silly, and a broken schema or an unreachable
pack slot is a deterministic bug that deserves a deterministic test.

What a live call adds on top of this is narrow but real: that the credentials
work, that the configured model name is accepted, and that the model actually
follows the instructions. Those are checked separately.
"""
import json

import pytest

from apps.studio.domain import GENERATION_IDS
from apps.studio.packs import slots
from apps.studio.provider import SCHEMA, _validate, request_body, schema_for, writing_guidance

CONFIG = {'model': 'gpt-5.6-luna', 'api_key': 'not-used-offline'}


def draft(options=None, sections=2):
    return {
        'output_locale': 'en',
        'prompt': 'A short briefing about tide tables.',
        'source_text': '',
        'excerpts': [],
        'options': {'question_count': 2, **(options or {})},
        'content': {
            'title': 'Tide tables',
            'sections': [
                {'id': f's{i + 1}', 'heading': f'Heading {i + 1}', 'body': 'Body.', 'notes': ''}
                for i in range(sections)
            ],
            'questions': [],
            'citations': [],
        },
    }


def model_answer(feature):
    """A minimal response that satisfies the schema the feature asks for."""
    section = {'id': 's1', 'heading': 'Heading 1', 'body': 'Body text.', 'notes': ''}
    question = {
        'id': 'q1', 'stem': 'What is a spring tide?', 'options': ['A', 'B'],
        'answer': 'A', 'explanation': 'Because.', 'topic': 'Tides', 'marks': 1,
    }
    answer = {
        'title': 'Tide tables', 'answer_supported': True, 'citations': [],
        'sections': [section], 'questions': [question],
    }
    rows = slots(feature)
    if rows:
        answer['materials'] = [
            {'key': row[0], 'title': f'{row[0]} material',
             'sections': [section], 'questions': [question] if row[4] else []}
            for row in rows
        ]
    return answer


@pytest.mark.parametrize('feature', sorted(GENERATION_IDS))
def test_every_ai_feature_can_build_a_request_and_accept_an_answer(feature):
    body = request_body(CONFIG, draft(), feature)

    assert body['model'] == CONFIG['model']
    assert body['store'] is False, 'provider must not retain customer content'
    assert body['text']['format']['strict'] is True
    payload = json.loads(body['input'])
    assert payload['task'] == feature
    assert payload['max_sections'] >= 1

    # The response contract the model is handed must accept a well-formed answer.
    _validate(model_answer(feature), schema_for(feature))


@pytest.mark.parametrize('feature', sorted(f for f in GENERATION_IDS if slots(f)))
def test_pack_features_publish_every_slot_they_require(feature):
    payload = json.loads(request_body(CONFIG, draft(), feature)['input'])
    published = {row['key'] for row in payload['material_slots']}
    assert published == {row[0] for row in slots(feature)}, 'slot list must match the renderer'
    # The schema must only accept the keys the renderer knows how to draw.
    enum = schema_for(feature)['properties']['materials']['items']['properties']['key']['enum']
    assert set(enum) == published


def test_writing_guidance_reaches_every_feature_that_asks_for_prose():
    for feature in sorted(GENERATION_IDS):
        payload = json.loads(request_body(CONFIG, draft({'density': 'rich'}), feature)['input'])
        assert 'writing_guidance' in payload, feature
        assert 'words of body text' in payload['writing_guidance']


def test_a_response_missing_a_required_field_is_refused():
    broken = model_answer('ai.pdf_text')
    del broken['questions']
    with pytest.raises(ValueError):
        _validate(broken, SCHEMA)

    extra = model_answer('ai.pdf_text')
    extra['unexpected'] = 'value'
    with pytest.raises(ValueError):
        _validate(extra, SCHEMA)


def test_guidance_never_asks_for_more_prose_than_the_response_can_hold():
    from apps.studio.provider import BODY_WORD_BUDGET
    for sections in (1, 5, 20, 50):
        text = writing_guidance({'density': 'rich'}, sections)
        words = int(text.split(' words')[0].split()[-1].split('-')[-1])
        assert words * sections <= BODY_WORD_BUDGET * 1.05, (sections, text)
