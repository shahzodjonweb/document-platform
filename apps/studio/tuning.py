"""How a provider call is tuned: reasoning effort and processing tier (Admin → Integrations).

A call's time is about one second plus 9.5 ms per output token, and the model's
reasoning counts as output: in November 2026 it was 31% of all output tokens,
and about 85% of the photo choice's, whose answer is a dozen tokens a slide.
So the effort is a time setting as much as a quality one.

Nothing is sent that is not set, except the photo choice's effort, which is
`low` unless the admin chooses otherwise: the tag ranking already stands in
when its answer is unusable. A writing call keeps the model's own effort until
one is chosen, because a weaker answer there costs the customer the document.

A model that does not take a setting answers 400 and names it. The call is
then sent once more without it, and the setting is left out of every later
call in this process, so a wrong choice in the admin never fails a job.
"""
import json
import urllib.error

EFFORTS = ('none', 'minimal', 'low', 'medium', 'high')
# Priority processing is faster and dearer; 'default' is the account's own.
# Flex is slower and is not offered: these settings exist to save time.
TIERS = ('default', 'priority')
PHOTO_EFFORT = 'low'
_PARAMETERS = ('reasoning', 'service_tier')
# The settings a model refused in this process: never sent again until a restart.
_refused = set()


def settings(config, kind):
    """{'reasoning': ..., 'service_tier': ...} for a `kind` of call ('writing' or 'photos'), or empty."""
    effort = config.get('photo_effort', PHOTO_EFFORT) if kind == 'photos' else config.get('writing_effort', '')
    tier = config.get('service_tier', '')
    extra = {}
    if effort in EFFORTS and 'reasoning' not in _refused:
        extra['reasoning'] = {'effort': effort}
    if tier in TIERS and 'service_tier' not in _refused:
        extra['service_tier'] = tier
    return extra


def apply(body, config, kind):
    """The request body with its tuning added; the body itself is changed and returned."""
    body.update(settings(config, kind))
    return body


def refused(error, body):
    """The tuning parameter a provider's 400 refuses, if this body carried it; else None."""
    if not isinstance(error, urllib.error.HTTPError) or error.code != 400:
        return None
    carried = [name for name in _PARAMETERS if name in body]
    if not carried:
        return None
    try:
        raw = error.read(65536)
    except Exception:
        raw = b''
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw or '')
    try:
        detail = json.loads(text).get('error') or {}
    except (ValueError, AttributeError):
        detail = {}
    named = str(detail.get('param') or '') if isinstance(detail, dict) else ''
    message = (str(detail.get('message') or '') if isinstance(detail, dict) else '') or text
    for name in carried:
        if named.split('.')[0] == name or name in message:
            return name
    return None


def send(post, body):
    """`post(body)` once, and once more without a tuning setting the model refused.

    `post` sends a body and returns what it read; any other failure is the
    caller's, exactly as before.
    """
    try:
        return post(body)
    except urllib.error.HTTPError as error:
        name = refused(error, body)
        if name is None:
            raise
        _refused.add(name)
        return post({key: value for key, value in body.items() if key != name})


def forget():
    """Tests: let refused settings be sent again."""
    _refused.clear()
