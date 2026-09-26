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
        try:
            raw,usage=generate(cfg,data,job.feature_id,job.id,token_limit=job.quote.policy['generation_bounds']['input_tokens'])
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
    if len(content['questions'])>bounds.get('question_cap',limits(job.account)['questions']):raise DomainError('generation_limit')
    if cfg['mode']=='openai' and len(content['sections'])>len(data['content']['sections']):raise DomainError('generation_limit')
    from .branding import render_style
    style=render_style(job.account,data,feature_id=job.feature_id)
    fn=render_pptx if data['output_format']=='pptx' else render_pdf
    ext=data['output_format']
    artifacts=[fn(content,output_dir/f'document.{ext}',data['output_locale'],'user_document',style=style)]
    # Against the quoted page allowance, not the plan ceiling: a section written
    # to fill its page may spill, and the quote already reserved for that.
    allowance=bounds.get('output_pages',limits(job.account)['slides' if data['output_format']=='pptx' else 'sections'])
    if any(a['page_count']>allowance for a in artifacts):raise DomainError('generation_limit')
    question_count=len(content['questions'])
    actual=dict(job.meters)
    if cfg['mode']=='openai':
        import math
        from apps.core.policy import SEED
        tariff=bounds.get('tariff',SEED['tariff_v0_staging'])
        if question_count>bounds['question_cap']:raise DomainError('generation_limit')
        from .metering import generation_credits
        output_credits=sum(a['page_count']*(tariff['pptx_output_credits_per_slide'] if a['name'].endswith('.pptx') else tariff['pdf_output_credits_per_started_page']) for a in artifacts)
        actual['ai_credits']=generation_credits(job.feature_id,len(data['excerpts']),question_count,output_credits,tariff)
    if any(actual.get(m,0)>job.meters.get(m,0) for m in actual):raise DomainError('quote_exceeded',409)
    data['content']=content
    # A customer may edit while the provider is running. Never overwrite that
    # newer draft with the completed response for the prior confirmed version.
    GenerationDraft.objects.filter(pk=draft.pk,version=draft.version,encrypted_data=original).update(encrypted_data=pack(data),version=F('version')+1)
    return {'artifacts':artifacts,'actual_meters':actual,'metadata':{'engine':'structured-'+cfg['mode'],'warnings':warnings}}
