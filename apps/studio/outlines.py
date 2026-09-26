"""Separately confirmed outline authoring before the full document generation."""
import copy
import json
import math
from django.db.models import F
from apps.core.errors import DomainError
from apps.core.policy import SEED,plan_limits
from operations.integrations import ai_config
from .models import GenerationDraft,ProviderUsage
from .domain import generation_quote,unpack,pack,validate_content



def _payload(data):
    value=copy.deepcopy(data)
    value['prompt']='Create a concise reviewable outline, not the full document. Each section body must be at most 500 characters describing what to cover. No questions or speaker notes. Preserve section IDs. Original request: '+data['prompt']
    value['options']={'question_count':0,'length':len(data['content']['sections']),'outline_only':True}
    value['content']['questions']=[]
    value.pop('revision',None)
    return value


def create_outline_quote(account,draft_id,version):
    from .domain import allowed
    plan_limits(account)
    if not allowed(account,'ai.outline'):raise DomainError('feature_not_in_plan',403)
    # No reservation exists yet; the final immutable object is returned only after
    # the stage, source costs and bounds have been set.
    from django.db import transaction
    with transaction.atomic():
        quote=generation_quote(account,draft_id,version)
        draft=GenerationDraft.objects.get(id=draft_id,account=account);data=unpack(draft.encrypted_data)
        cfg=ai_config()
        if cfg['mode']!=quote.policy['provider_mode'] or cfg['model']!=quote.policy['provider_model']:raise DomainError('provider_changed',409)
        if cfg['mode']=='openai':
            from .provider import enforce_input_budget
            enforce_input_budget(cfg,_payload(data),'ai.outline',plan_limits(account)['max_ai_input_tokens'])
        tariff=quote.policy['generation_bounds']['tariff']
        credits=0 if cfg['mode']=='local_fixture' else tariff['outline_credits']+math.ceil(len(data['excerpts'])/5)*tariff['source_ingestion_credits_per_started_5_pages']
        quote.parameters={**quote.parameters,'stage':'outline'}
        quote.meters={'file_tasks':0,'file_page_units':0,'ai_credits':credits}
        quote.policy={**quote.policy,'tariff_version':'outline-draft-staging-v1'}
        quote.save(update_fields=['parameters','meters','policy'])
        return quote


def execute_outline(job,draft,data,original,config,output_dir):
    from .provider import generate
    warnings=[]
    if config['mode']=='openai':
        try:
            raw,usage=generate(config,_payload(data),'ai.outline',job.id,token_limit=job.policy['generation_bounds']['input_tokens'])
            content=validate_content(job.account,raw,data['output_format'])
            # An outline is headings and a sentence each. A model that writes more
            # than that, or adds questions nobody asked for, is cut back to the
            # shape of an outline — it does not cost the customer the job.
            expected=data['content']['sections']
            if content['questions']:content['questions']=[];warnings.append('questions_trimmed')
            if len(content['sections'])>len(expected):
                content['sections']=content['sections'][:len(expected)];warnings.append('sections_trimmed')
            content['sections']=[{**s,'body':s['body'][:500],'notes':''} for s in content['sections']]
            # Identity is not negotiable: a confirmed outline's sections may be
            # rewritten but never replaced, reordered or dropped.
            if [s['id'] for s in content['sections']]!=[s['id'] for s in expected]:raise DomainError('invalid_parameters')
            for ref in content['citations']:
                source=next((s for s in data['excerpts'] if s['asset_id']==ref.get('asset_id') and s['page']==ref.get('page')),None)
                if not source or not ref.get('quote') or ref['quote'] not in source['text']:raise DomainError('invalid_source_citation')
            ProviderUsage.objects.create(job=job,provider='openai_outline',model=config['model'],outcome='succeeded',**usage)
        except Exception:
            ProviderUsage.objects.create(job=job,provider='openai_outline',model=config['model'],outcome='failed')
            raise
    else:
        content={'title':data['content']['title'],'sections':[{**s,'body':s['body'][:500],'notes':''} for s in data['content']['sections']],'questions':[],'citations':data['content'].get('citations',[])}
        warnings.append('local_fixture_not_ai_generated')
    path=output_dir/'outline.json';path.write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf-8')
    data['content']={**content,'questions':data['content']['questions']}
    GenerationDraft.objects.filter(pk=draft.pk,version=draft.version,encrypted_data=original).update(encrypted_data=pack(data),version=F('version')+1)
    return {'artifacts':[{'path':str(path),'name':path.name,'mime_type':'application/json','page_count':1,'role':'user_document','metadata':{'kind':'text'}}], 'actual_meters':dict(job.meters),'metadata':{'engine':'outline-'+config['mode'],'warnings':warnings}}
