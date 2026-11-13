"""The model looks at the candidate photos for each slide and picks one, or none.

A search matches words, not meaning: "team meeting" finds a meeting, and also a
football team. So before a photo goes into a deck the model sees the few best
candidates as small previews, beside the slide's own text, and says which one
shows what the slide is about — or that none does, in which case the slide is
drawn as text. A loosely related photo is worse than no photo.

The previews are sent as data, never as Pixabay URLs, so the provider does not
fetch Pixabay itself. The call is accounted like every other provider call, and
any failure of it is the caller's cue to fall back, never a failed job.
"""
import base64
import json
import time
import urllib.request

API = 'https://api.openai.com/v1/responses'
MAX_RESPONSE = 200_000

SCHEMA = {
    'type': 'object',
    'properties': {'picks': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'slide': {'type': 'string'}, 'photo': {'type': 'integer'}},
        'required': ['slide', 'photo'], 'additionalProperties': False}}},
    'required': ['picks'], 'additionalProperties': False,
}

INSTRUCTIONS = (
    'You choose stock photos for the slides of a presentation. For each slide you are given its '
    'text and a few numbered candidate photos. Pick the photo that most clearly shows what that '
    'slide is about, so the audience sees the connection at a glance. Answer 0 when none of them '
    'clearly fits: an unrelated or only loosely related photo is worse than no photo. Never pick a '
    'photo with visible text, a logo or a watermark, or one that would be out of place in a '
    'professional presentation. Use each photo at most once. Answer every slide, by its id.'
)


def request_body(config, title, slides):
    content = [{'type': 'input_text', 'text': f'Presentation: {title}'[:300]}]
    for slide in slides:
        content.append({'type': 'input_text',
                        'text': f'Slide {slide["id"]}: {slide["text"]}\nCandidates for slide {slide["id"]}:'})
        for number, jpeg in enumerate(slide['photos'], 1):
            content.append({'type': 'input_text', 'text': f'Slide {slide["id"]}, photo {number}:'})
            content.append({'type': 'input_image', 'detail': 'low',
                            'image_url': 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()})
    body = {'model': config['model'], 'store': False, 'instructions': INSTRUCTIONS,
            'input': [{'role': 'user', 'content': content}],
            # Room for a reasoning model to think; the answer itself is tiny.
            'max_output_tokens': 3000 + 50 * len(slides),
            'text': {'format': {'type': 'json_schema', 'name': 'photo_picks', 'strict': True,
                                'schema': SCHEMA}}}
    # Low effort unless the admin says otherwise: most of this call's time was
    # its reasoning, for an answer of a dozen tokens a slide (tuning.py).
    from . import tuning
    return tuning.apply(body, config, 'photos')


def _post(request, timeout):
    """Every byte of this call goes through here, so tests can stop it."""
    from .provider import _NoRedirect
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def choose(config, title, slides, *, timeout, job=None, account=None):
    """{slide id: 1-based photo number, or 0 for none} for the slides given.

    A slide the model left out, or answered with a number it was not shown,
    gets 0: the model's silence is not a vote for the most popular photo.
    Raises on any failure of the call itself.
    """
    from . import provider_usage
    from .domain import SLIDES
    from .provider import _CutOff, _Rejected, _close, _reply_text, _validate
    body = request_body(config, title, slides)
    key = f'{job.id}-photos' if job is not None else f'photos-{time.time_ns()}'
    attempt = provider_usage.start_attempt(key, SLIDES, config['model'], stage='photo_pick', job=job, account=account)
    started, received = time.monotonic(), False
    try:
        def post(sent):
            request = urllib.request.Request(
                API, data=json.dumps(sent, separators=(',', ':')).encode(),
                headers={'Authorization': 'Bearer ' + config['api_key'], 'Content-Type': 'application/json'})
            with _post(request, timeout) as response:
                return response.read(MAX_RESPONSE + 1)
        from . import tuning
        raw = tuning.send(post, body)
        # A refused reply raises its code (provider_usage.REJECTIONS), so its row says why, as in provider._call.
        if len(raw) > MAX_RESPONSE:
            raise _Rejected('oversized')
        result = json.loads(raw)
        provider_usage.received(attempt, result, round((time.monotonic() - started) * 1000))
        received = True
        if not isinstance(result, dict):
            raise _Rejected('no_output')
        if result.get('status') == 'incomplete':
            raise _CutOff()
        if result.get('status') != 'completed':
            raise _Rejected('not_completed')
        try:
            answer = json.loads(_reply_text(result))
        except json.JSONDecodeError:
            raise _Rejected('not_json') from None
        _validate(answer, SCHEMA)
        shown = {slide['id']: len(slide['photos']) for slide in slides}
        picks = dict.fromkeys(shown, 0)
        answered = set()
        for entry in answer['picks']:
            sid, number = entry['slide'], entry['photo']
            if sid in shown and sid not in answered and 0 <= number <= shown[sid]:
                picks[sid] = number
                answered.add(sid)
        provider_usage.finish(attempt, 'succeeded')
        return picks
    except Exception as failure:
        _close(attempt, failure, received, started)
        raise


# ---------------------------------------------------------------- naming


NAMING_SCHEMA = {
    'type': 'object',
    'properties': {'queries': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'slide': {'type': 'string'}, 'query': {'type': 'string'}},
        'required': ['slide', 'query'], 'additionalProperties': False}}},
    'required': ['queries'], 'additionalProperties': False,
}

NAMING_INSTRUCTIONS = (
    'You name a stock photo for each slide of a presentation, for a photo search. For each slide you '
    'are given its id and text. ')


def name_queries(config, title, slides, *, timeout, account=None):
    """{slide id: search words} for slides that have no photo subject yet, as the slide editor's fill asks.

    The deck's own words go to the model, as they do when it is written; only
    the cleaned English words it answers (layouts.clean_query) go on to Pixabay.
    A slide it leaves out, or names with nothing usable, is absent. Raises on
    any failure of the call itself.
    """
    from . import provider_usage, tuning
    from .domain import SLIDES
    from .layouts import _naming, clean_query
    from .provider import _CutOff, _Rejected, _close, _reply_text, _validate
    text = f'Presentation: {title}'[:300] + '\n' + '\n'.join(f'Slide {slide["id"]}: {slide["text"]}' for slide in slides)
    body = tuning.apply({'model': config['model'], 'store': False,
                         'instructions': NAMING_INSTRUCTIONS + _naming() + 'Answer every slide, by its id.',
                         'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}],
                         'max_output_tokens': 2000 + 40 * len(slides),
                         'text': {'format': {'type': 'json_schema', 'name': 'photo_queries', 'strict': True,
                                             'schema': NAMING_SCHEMA}}}, config, 'photos')
    attempt = provider_usage.start_attempt(f'photo-names-{time.time_ns()}', SLIDES, config['model'], stage='photo_pick',
                                           account=account)
    started, received = time.monotonic(), False
    try:
        def post(sent):
            request = urllib.request.Request(
                API, data=json.dumps(sent, separators=(',', ':')).encode(),
                headers={'Authorization': 'Bearer ' + config['api_key'], 'Content-Type': 'application/json'})
            with _post(request, timeout) as response:
                return response.read(MAX_RESPONSE + 1)
        raw = tuning.send(post, body)
        if len(raw) > MAX_RESPONSE:
            raise _Rejected('oversized')
        result = json.loads(raw)
        provider_usage.received(attempt, result, round((time.monotonic() - started) * 1000))
        received = True
        if not isinstance(result, dict):
            raise _Rejected('no_output')
        if result.get('status') == 'incomplete':
            raise _CutOff()
        if result.get('status') != 'completed':
            raise _Rejected('not_completed')
        try:
            answer = json.loads(_reply_text(result))
        except json.JSONDecodeError:
            raise _Rejected('not_json') from None
        _validate(answer, NAMING_SCHEMA)
        asked, named = {slide['id'] for slide in slides}, {}
        for entry in answer['queries']:
            query = clean_query(entry['query'])
            if entry['slide'] in asked and entry['slide'] not in named and query:
                named[entry['slide']] = query
        provider_usage.finish(attempt, 'succeeded')
        return named
    except Exception as failure:
        _close(attempt, failure, received, started)
        raise
