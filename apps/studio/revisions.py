"""Server-owned source provenance and exact, explicitly scoped revisions."""
from copy import deepcopy
import hashlib
import json

from apps.core.errors import DomainError


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _sources(data):
    return {'source_text': data.get('source_text', ''), 'excerpts': data.get('excerpts', [])}


def source_seed(data):
    """Mark only server-created source copies, before the author can edit them."""
    if not data.get('source_text') and not data.get('excerpts'):
        return None
    return {'sources': _fingerprint(_sources(data)),
            'sections': {s['id']: _fingerprint(s) for s in data['content']['sections'] if s.get('body')}}


def provider_content(data):
    """Remove a repeated seed only with exact server provenance; legacy content stays."""
    content = deepcopy(data['content'])
    seed = data.get('_source_seed')
    if not isinstance(seed, dict) or seed.get('sources') != _fingerprint(_sources(data)):
        return content
    fingerprints = seed.get('sections', {})
    if not isinstance(fingerprints, dict):
        return content
    for section in content['sections']:
        if fingerprints.get(section['id']) == _fingerprint(section):
            section['body'] = ''
    return content


def selected_ids(options, content, version):
    """Selection is opt-in and belongs to one exact version of an owned draft."""
    ids = options.get('revise_section_ids')
    if ids is None:
        if 'revise_base_version' in options:
            raise DomainError('invalid_parameters')
        return []
    if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids)
            or len(set(ids)) != len(ids)):
        raise DomainError('invalid_parameters')
    if type(options.get('revise_base_version')) is not int:
        raise DomainError('invalid_parameters')
    if options['revise_base_version'] != version:
        raise DomainError('version_conflict', 409)
    known = [s['id'] for s in content['sections']]
    if set(ids) - set(known):
        raise DomainError('invalid_parameters')
    # Document order, rather than click order, is stable for batching and merging.
    return [i for i in known if i in ids]


def merge_patch(data, patch):
    """Accept exactly the selected sections; keep everything else byte-for-byte."""
    revision = data.get('revision', {})
    ids = revision.get('selected_section_ids')
    base = revision.get('base_content')
    if not ids or not isinstance(base, dict) or not isinstance(patch, dict):
        raise DomainError('invalid_parameters')
    if set(patch) - {'sections', 'citations', 'answer_supported'}:
        raise DomainError('invalid_parameters')
    sections = patch.get('sections')
    if (not isinstance(sections, list) or any(not isinstance(s, dict) for s in sections)
            or [s.get('id') for s in sections] != ids):
        raise DomainError('invalid_parameters')
    citations = patch.get('citations', [])
    if not isinstance(citations, list) or any(not isinstance(c, dict) for c in citations):
        raise DomainError('invalid_parameters')
    replacements = {s['id']: deepcopy(s) for s in sections}
    # The quoted draft may contain subsequent manual edits; they are authoritative.
    result = deepcopy(data['content'])
    result['sections'] = [replacements.get(s['id'], s) for s in result['sections']]
    # A source-seeded draft has page-location placeholders before any model has
    # supplied a quote. Those are input metadata, not verified citations. Drop
    # only the exact baseline placeholder shape for an actual supplied page;
    # keep quoted references and malformed/forged references for the caller's
    # citation validation instead of silently making bad references disappear.
    def source_placeholder(reference):
        return (set(reference) == {'asset_id', 'page'} and type(reference['page']) is int
                and reference in base.get('citations', [])
                and any(reference['asset_id'] == excerpt.get('asset_id')
                        and reference['page'] == excerpt.get('page') for excerpt in data.get('excerpts', [])))
    result['citations'] = [reference for reference in result.get('citations', [])
                           if not source_placeholder(reference)]
    for reference in citations:
        if reference not in result['citations']:
            result['citations'].append(deepcopy(reference))
    if 'answer_supported' in patch:
        result['answer_supported'] = patch['answer_supported']
    return result
