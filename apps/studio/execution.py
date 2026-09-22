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
    reviewed_export=job.parameters.get('stage')=='export'
    if job.parameters.get('stage')=='outline':
        from .outlines import execute_outline
        return execute_outline(job,draft,data,original,cfg,output_dir)
    if job.feature_id=='ai.images':
        from .illustrations import execute_illustration
        return execute_illustration(job,data,cfg,output_dir)
    if reviewed_export:
        warnings.append('handwriting_reviewed_export')
    elif cfg['mode']=='openai':
        from .provider import generate
        try:
            if job.feature_id=='study.handwriting':
                from .handwriting import generate as transcribe
                raw,usage=transcribe(cfg,data,job.account,job.id,job.quote.policy['generation_bounds']['input_tokens'])
                warnings.append('handwriting_review_required')
            else:raw,usage=generate(cfg,data,job.feature_id,job.id,token_limit=job.quote.policy['generation_bounds']['input_tokens'])
            from .revisions import preserve_unselected
            content=validate_content(job.account,preserve_unselected(data,raw,provider=True),data['output_format'])
            references=[]
            for ref in raw.get('citations',[]):
                source=next((s for s in data['excerpts'] if s['asset_id']==ref.get('asset_id') and s['page']==ref.get('page')),None)
                if not source or not ref.get('quote') or ref['quote'] not in source['text']:raise DomainError('invalid_source_citation')
                references.append({k:ref[k] for k in ('asset_id','page','quote')})
            content['citations']=references
            if job.feature_id=='study.pdf_qa' and (not raw.get('answer_supported') or not references):
                labels={'en':'No supporting answer was found in the supplied source pages.','uz':'Berilgan manba sahifalarida tasdiqlovchi javob topilmadi.','ru':'На предоставленных страницах источника подтверждающий ответ не найден.'}
                content['sections']=[{'id':'not_found','heading':'—','body':labels[data['output_locale']],'notes':''}]
                content['questions']=[];content['citations']=[];warnings.append('source_answer_not_found')
            ProviderUsage.objects.create(job=job,provider='openai',model=cfg['model'],input_tokens=usage.get('input_tokens',0),output_tokens=usage.get('output_tokens',0),outcome='succeeded')
        except Exception:
            ProviderUsage.objects.create(job=job,provider='openai',model=cfg['model'],outcome='failed')
            raise
    else:
        warnings.append('local_fixture_not_ai_generated')
        if not any(s['body'].strip() for s in content['sections']) and not content['questions']:
            raise DomainError('content_required')
    from .packs import slots,local_materials,validate_materials,render as render_pack
    teacher=job.feature_id.startswith('teacher.')
    bounds=job.quote.policy.get('generation_bounds',{})
    if len(content['questions'])>bounds.get('question_cap',limits(job.account)['questions']):raise DomainError('generation_limit')
    if cfg['mode']=='openai' and not reviewed_export and len(content['sections'])>len(data['content']['sections']):raise DomainError('generation_limit')
    from .branding import render_style
    style=render_style(job.account,data,feature_id=job.feature_id)
    if job.feature_id in ('study.flashcards','study.answer_key'):
        if not content['questions']:raise DomainError('content_required')
        style={**style,'content_layout':'flashcards' if job.feature_id=='study.flashcards' else 'answer_key'}
    if slots(job.feature_id):
        materials=raw.get('materials',[]) if cfg['mode']=='openai' else local_materials(job.feature_id,content,data['output_locale'])
        materials=validate_materials(job.account,job.feature_id,materials,bounds['question_cap'])
        for material in materials:material['citations']=content['citations']
        artifacts=render_pack(job.feature_id,materials,output_dir,data['output_locale'],style,limits(job.account))
        content['materials']=materials
        question_count=sum(len(material['questions']) for material in materials)
        warnings.append('review_each_pack_and_paired_answer_key')
        if cfg['mode']=='local_fixture':warnings.append('local_pack_uses_supplied_questions_and_scaffolding')
    else:
        from .privacy import artifact_role
        role=artifact_role(job.feature_id)
        if role=='teacher_key' and not content['questions']:raise DomainError('content_required')
        fn=render_pptx if data['output_format']=='pptx' else render_pdf
        ext=data['output_format'];artifacts=[fn(content,output_dir/f'document.{ext}',data['output_locale'],role,style=style)]
        if any(a['page_count']>limits(job.account)['slides' if data['output_format']=='pptx' else 'sections'] for a in artifacts):raise DomainError('generation_limit')
        if teacher and role!='teacher_key' and content['questions']:
            key=render_pdf(content,output_dir/'teacher-key.pdf',data['output_locale'],'teacher_key',style=style)
            if key['page_count']>bounds.get('key_pages',limits(job.account)['sections']):raise DomainError('generation_limit')
            artifacts.append(key)
        question_count=len(content['questions'])
    actual=dict(job.meters)
    if cfg['mode']=='openai' and not reviewed_export:
        import math
        from apps.core.policy import SEED
        tariff=bounds.get('tariff',SEED['tariff_v0_staging'])
        if question_count>bounds['question_cap']:raise DomainError('generation_limit')
        from .metering import generation_credits
        output_credits=sum(a['page_count']*(tariff['pptx_output_credits_per_slide'] if a['name'].endswith('.pptx') else tariff['pdf_output_credits_per_started_page']) for a in artifacts)
        actual['ai_credits']=generation_credits(job.feature_id,len(data['excerpts']),question_count,output_credits,tariff)
    if any(actual.get(m,0)>job.meters.get(m,0) for m in actual):raise DomainError('quote_exceeded',409)
    data['content']=content
    if job.feature_id=='study.handwriting' and not reviewed_export:
        from .handwriting import completed_state
        data['_transcription']=completed_state(job.account,data,job.id)
    # A customer may edit while the provider is running. Never overwrite that
    # newer draft with the completed response for the prior confirmed version.
    GenerationDraft.objects.filter(pk=draft.pk,version=draft.version,encrypted_data=original).update(encrypted_data=pack(data),version=F('version')+1)
    return {'artifacts':artifacts,'actual_meters':actual,'metadata':{'engine':'reviewed-transcription-export' if reviewed_export else 'structured-'+cfg['mode'],'warnings':warnings}}
