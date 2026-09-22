"""Forked revisions bind an owned draft and preserve unselected sections exactly."""
import copy
import uuid
from django.utils import timezone
from apps.core.errors import DomainError
from .models import GenerationDraft

REVISION_IDS={'ai.rewrite','ai.regenerate_slide'}


def prepare_revision(account,feature_id,payload):
    if feature_id not in REVISION_IDS:return payload
    from .domain import unpack,validate_content
    options=payload['options'];identifier=options.get('source_draft_id')
    if not identifier:raise DomainError('source_required')
    try:identifier=uuid.UUID(str(identifier))
    except (ValueError,TypeError):raise DomainError('invalid_parameters') from None
    source=GenerationDraft.objects.filter(account=account,id=identifier,expires_at__gt=timezone.now()).first()
    if not source:raise DomainError('not_found',404)
    source_version=options.get('source_draft_version',source.version)
    if type(source_version) is not int or source_version!=source.version:raise DomainError('version_conflict',409)
    original=unpack(source.encrypted_data)
    if original['output_format'] not in ('pdf','pptx'):raise DomainError('invalid_parameters')
    if feature_id=='ai.regenerate_slide' and original['output_format']!='pptx':raise DomainError('invalid_parameters')
    selected=options.get('selected_section_ids')
    sections=original['content']['sections'];known={s['id'] for s in sections}
    if not isinstance(selected,list) or not selected or any(not isinstance(s,str) for s in selected) or len(set(selected))!=len(selected) or not set(selected)<=known:
        raise DomainError('invalid_parameters')
    # A revision cannot turn a teacher-only artifact into a public learner export.
    if source.feature_id.startswith(('teacher.','school.')):raise DomainError('invalid_parameters')
    payload=copy.deepcopy(payload)
    payload['options']['source_draft_version']=source.version
    payload.update(output_format=original['output_format'],source_ids=original['source_ids'],excerpts=original['excerpts'])
    payload['content']=validate_content(account,original['content'],original['output_format'])
    payload['title']=payload['content']['title']
    payload['revision']={'source_draft_id':str(source.id),'source_version':source.version,'selected_section_ids':selected,'base_content':copy.deepcopy(payload['content'])}
    return payload


def provider_content(data):
    if 'revision' not in data:return data['content']
    selected=set(data['revision']['selected_section_ids'])
    return {'title':data['content']['title'],'sections':[s for s in data['content']['sections'] if s['id'] in selected],'questions':[],'citations':data['content'].get('citations',[])}


def preserve_unselected(data,content,*,provider=False):
    if 'revision' not in data:return content
    revision=data['revision'];selected=set(revision['selected_section_ids']);base=revision['base_content']
    incoming={s['id']:s for s in content['sections']}
    if not selected<=set(incoming) or provider and (set(incoming)!=selected or content.get('questions')):
        raise DomainError('invalid_parameters')
    value=copy.deepcopy(base)
    value['sections']=[copy.deepcopy(incoming[s['id']] if s['id'] in selected else s) for s in base['sections']]
    if provider:value['citations']=content.get('citations',[])
    return value
