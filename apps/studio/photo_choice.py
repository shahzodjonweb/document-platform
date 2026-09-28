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
    return {'model': config['model'], 'store': False, 'instructions': INSTRUCTIONS,
            'input': [{'role': 'user', 'content': content}],
            # Room for a reasoning model to think; the answer itself is tiny.
            'max_output_tokens': 3000 + 50 * len(slides),
            'text': {'format': {'type': 'json_schema', 'name': 'photo_picks', 'strict': True,
                                'schema': SCHEMA}}}


def _post(request, timeout):
    """Every byte of this call goes through here, so tests can stop it."""
    from .provider import _NoRedirect
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def choose(config, title, slides, *, timeout, job=None):
    """{slide id: 1-based photo number, or 0 for none} for the slides given.

    A slide the model left out, or answered with a number it was not shown,
    gets 0: the model's silence is not a vote for the most popular photo.
    Raises on any failure of the call itself.
    """
    from . import provider_usage
    from .domain import SLIDES
    from .provider import _validate
    body = request_body(config, title, slides)
    key = f'{job.id}-photos' if job is not None else f'photos-{time.time_ns()}'
    attempt = provider_usage.start_attempt(key, SLIDES, config['model'], stage='photo_pick', job=job)
    started, received = time.monotonic(), False
    try:
        request = urllib.request.Request(
            API, data=json.dumps(body, separators=(',', ':')).encode(),
            headers={'Authorization': 'Bearer ' + config['api_key'], 'Content-Type': 'application/json'})
        with _post(request, timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('too_large')
        result = json.loads(raw)
        provider_usage.received(attempt, result, round((time.monotonic() - started) * 1000))
        received = True
        if not isinstance(result, dict) or result.get('status') != 'completed':
            raise ValueError('status')
        text = ''.join(part.get('text', '') for output in result.get('output', [])
                       if isinstance(output, dict) and output.get('type') == 'message'
                       for part in output.get('content', [])
                       if isinstance(part, dict) and part.get('type') == 'output_text')
        answer = json.loads(text)
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
    except Exception:
        provider_usage.finish(attempt, 'rejected' if received else 'failed',
                              elapsed_ms=round((time.monotonic() - started) * 1000))
        raise
