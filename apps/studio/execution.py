from django.utils import timezone
from django.db import transaction
from django.db.models import F
from apps.core.errors import DomainError
from operations.integrations import ai_config
from .models import GenerationDraft,ProviderUsage
from .domain import unpack,pack,validate_content,validate_generation_quote,limits
from .rendering import render_pdf,render_pptx

def execute_generation(job,output_dir):
    with transaction.atomic():
        draft=GenerationDraft.objects.select_for_update().get(id=job.parameters['generation_draft_id'],account=job.account)
        validate_generation_quote(job.account,job.quote)
        original=bytes(draft.encrypted_data)
        data=unpack(original)
    content=data['content'];cfg=ai_config();warnings=[]
    if job.parameters.get('stage')=='outline':
        from .outlines import execute_outline
        return execute_outline(job,draft,data,original,cfg,output_dir)
    if cfg['mode']=='openai':
        from .provider import generate
        # Finish the provider calls while the worker still holds the job: work
        # completed after the lease lapses is thrown away by the reclaim sweep.
        import time
        deadline=time.monotonic()+max(60,(job.lease_expires_at-timezone.now()).total_seconds()-120) if job.lease_expires_at else None
        try:
            raw,usage=generate(cfg,data,job.feature_id,job.id,token_limit=job.quote.policy['generation_bounds']['input_tokens'],deadline=deadline)
            content=validate_content(job.account,raw,data['output_format'])
            references=[]
            for ref in raw.get('citations',[]):
                source=next((s for s in data['excerpts'] if s['asset_id']==ref.get('asset_id') and s['page']==ref.get('page')),None)
                if not source or not ref.get('quote') or ref['quote'] not in source['text']:raise DomainError('invalid_source_citation')
                references.append({k:ref[k] for k in ('asset_id','page','quote')})
            content['citations']=references
            ProviderUsage.objects.create(job=job,provider='openai',model=cfg['model'],input_tokens=usage.get('input_tokens',0),output_tokens=usage.get('output_tokens',0),outcome='succeeded')
        except Exception:
            ProviderUsage.objects.create(job=job,provider='openai',model=cfg['model'],outcome='failed')
            raise
    else:
        warnings.append('local_fixture_not_ai_generated')
        if not any(s['body'].strip() for s in content['sections']) and not content['questions']:
            raise DomainError('content_required')
    bounds=job.quote.policy.get('generation_bounds',{})
    # Everything from here on trims the response to what was quoted instead of
    # rejecting it. The customer chose a page count, it was clamped to their plan
    # before the model was asked, and they are owed that document: a model that
    # returns an extra section, or a question nobody asked for, is our estimate
    # being off by a little, not a reason to destroy a paid job.
    question_cap=bounds.get('question_cap',limits(job.account)['questions'])
    if len(content['questions'])>question_cap:
        content['questions']=content['questions'][:question_cap];warnings.append('questions_trimmed')
    quoted_sections=len(data['content']['sections'])
    if cfg['mode']=='openai' and len(content['sections'])>quoted_sections:
        content['sections']=content['sections'][:quoted_sections];warnings.append('sections_trimmed')
    from .branding import render_style
    style=render_style(job.account,data,feature_id=job.feature_id)
    fn=render_pptx if data['output_format']=='pptx' else render_pdf
    ext=data['output_format']
    artifacts=[fn(content,output_dir/f'document.{ext}',data['output_locale'],'user_document',style=style)]
    # A document that renders longer than the estimate is still the document that
    # was asked for. It is delivered, said out loud, and charged at the quote.
    allowance=bounds.get('output_pages',limits(job.account)['slides' if data['output_format']=='pptx' else 'sections'])
    if any(a['page_count']>allowance for a in artifacts):warnings.append('longer_than_quoted')
    question_count=len(content['questions'])
    actual=dict(job.meters)
    if cfg['mode']=='openai':
        import math
        from apps.core.policy import SEED
        tariff=bounds.get('tariff',SEED['tariff_v0_staging'])
        from .metering import generation_credits
        # Never more than the pages that were quoted, and never more than were
        # produced: the customer pays for what they agreed to or less, so a long
        # render cannot turn into a surprise charge or a `quote_exceeded` failure.
        output_credits=sum(min(a['page_count'],allowance)*(tariff['pptx_output_credits_per_slide'] if a['name'].endswith('.pptx') else tariff['pdf_output_credits_per_started_page']) for a in artifacts)
        actual['ai_credits']=generation_credits(job.feature_id,len(data['excerpts']),question_count,output_credits,tariff)
    if any(actual.get(m,0)>job.meters.get(m,0) for m in actual):raise DomainError('quote_exceeded',409)
    data['content']=content
    # A customer may edit while the provider is running. Never overwrite that
    # newer draft with the completed response for the prior confirmed version.
    GenerationDraft.objects.filter(pk=draft.pk,version=draft.version,encrypted_data=original).update(encrypted_data=pack(data),version=F('version')+1)
    return {'artifacts':artifacts,'actual_meters':actual,'metadata':{'engine':'structured-'+cfg['mode'],'warnings':warnings}}
