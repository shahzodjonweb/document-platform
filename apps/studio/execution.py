from django.utils import timezone
from django.db import transaction
from django.db.models import F
from apps.core.errors import DomainError
from operations.integrations import ai_config
from .models import GenerationDraft,ProviderUsage
from .domain import unpack,pack,validate_content,validate_generation_quote,limits,ensure_selected_preservation
from .rendering import render_pdf
from .slides import render_pptx

def _photos(job,sections,warnings,style='photo'):
    """Stock photos for the slides that asked for one, or none — never a failure.

    The allowance is the plan's at the time the quote was made. Whatever goes
    wrong here — the provider, the network, the bytes, this code — the slides
    that wanted a photo are drawn as text and the customer is told. `style` is
    'illustration' when the customer asked for drawings, not photographs.
    """
    from . import photos as stock
    try:
        cap=int((job.quote.policy.get('limits') or {}).get('max_deck_images',0) or 0)
        left=(job.lease_expires_at-timezone.now()).total_seconds()-60 if job.lease_expires_at else stock.BUDGET_SECONDS
        result=stock.fetch_for_deck(sections,style=style,cap=cap,budget=min(stock.BUDGET_SECONDS,left),job=job)
    except Exception:
        result=stock.PhotoResult(failed=len(stock.wanted(sections)))
    warnings.extend(result.warnings)
    if result.wanted or result.failed:
        outcome='succeeded' if not result.failed else 'partial' if result.photos else 'failed'
        ProviderUsage.objects.create(job=job,provider='pixabay',outcome=outcome)
    return result.photos


def execute_generation(job,output_dir):
    with transaction.atomic():
        draft=GenerationDraft.objects.select_for_update().get(id=job.parameters['generation_draft_id'],account=job.account)
        validate_generation_quote(job.account,job.quote)
        original=bytes(draft.encrypted_data)
        data=unpack(original)
    content=data['content'];cfg=ai_config();warnings=[]
    if data.get('revision',{}).get('selected_section_ids'):
        # Recheck mutable plan bounds before any paid provider request. The
        # original quote cannot authorize losing untouched pages after a cap
        # change or subscription expiry while the job waited in the queue.
        ensure_selected_preservation(data,validate_content(job.account,content,data['output_format']))
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
            # The look the model chose is kept with the draft, so a later change
            # request redraws the same deck rather than picking again. Only a
            # change asking for a new look replaces the one the document has:
            # "Test tuz" on a designed document once came back plain. A design
            # picked on the review screen is the customer's, and stays.
            from . import deck_designs,doc_designs
            revision=data.get('revision') or {}
            redesign=bool((revision.get('edit') or {}).get('redesign')) and not revision.get('selected_section_ids')
            if data['output_format']=='pptx':
                picked=(data.get('options') or {}).get('deck_design') not in (None,'auto')
                deck_designs.remember(data,raw,replace=redesign and not picked)
            else:doc_designs.remember(data,raw,replace=redesign)
            # The whole document is checked before it is drawn: every field in
            # its language's alphabet, and a section in the wrong language, empty
            # or repeating another sent back to the model once (quality.py).
            from . import quality
            # A change request is checked against the model's own plan of it:
            # a part it planned and left undone goes into the one repair.
            content,_=quality.finish(cfg,data,content,job=job,deadline=deadline,plan=raw.get('edit_plan'))
            # Bounds can also change while the provider is running. Deliver
            # only a result that still preserves everything outside its scope,
            # exactly as it was: quality.finish never retouches those pages.
            ensure_selected_preservation(data,content)
            # A reference has to point at a real page of a real supplied source and
            # quote it word for word. What an unusable one means depends on whether
            # the customer supplied anything to cite: against their own sources it
            # is a fabricated attribution and the document is not what they asked
            # for, so the job fails. With nothing uploaded there is nothing to
            # ground and the reference is only decoration, so it is dropped — it
            # used to destroy the document instead.
            references=[]
            for ref in raw.get('citations',[]):
                source=next((s for s in data['excerpts'] if s['asset_id']==ref.get('asset_id') and s['page']==ref.get('page')),None)
                if not source or not ref.get('quote') or ref['quote'] not in source['text']:
                    if data['excerpts']:raise DomainError('invalid_source_citation')
                    if 'citations_dropped' not in warnings:warnings.append('citations_dropped')
                    continue
                references.append({k:ref[k] for k in ('asset_id','page','quote')})
            content['citations']=references
            ProviderUsage.objects.create(job=job,provider='openai',model=cfg['model'],input_tokens=usage.get('input_tokens',0),output_tokens=usage.get('output_tokens',0),outcome='succeeded')
        except Exception:
            ProviderUsage.objects.create(job=job,provider='openai',model=cfg['model'],outcome='failed')
            raise
    else:
        warnings.append('local_fixture_not_ai_generated')
        if not any(s['body'].strip() or s.get('items') for s in content['sections']) and not content['questions']:
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
    ext=data['output_format']
    photo_style=(data.get('options') or {}).get('photo_style') or 'photo'
    if ext=='pptx':
        photos=_photos(job,content['sections'],warnings,photo_style)
        artifacts=[render_pptx(content,output_dir/'document.pptx',data['output_locale'],'user_document',style=style,photos=photos)]
    else:
        # A document only has photos when its description asked for pictures.
        photos=_photos(job,content['sections'],warnings,photo_style) if any(s.get('layout')=='image' for s in content['sections']) else {}
        artifacts=[render_pdf(content,output_dir/'document.pdf',data['output_locale'],'user_document',style=style,photos=photos)]
        # A document that came out short of the pages asked for is written
        # further, once, and drawn again; the renderer still holds the count.
        if cfg['mode']=='openai':
            from .filling import top_up
            longer=top_up(cfg,data,content,len(data['content']['sections']),artifacts[0]['page_count'],job=job,deadline=deadline)
            if longer is not content:
                from . import quality
                content=quality.normalise(longer,data['output_locale'])
                artifacts=[render_pdf(content,output_dir/'document.pdf',data['output_locale'],'user_document',style=style,photos=photos)]
    if cfg['mode']=='openai':
        # The file itself, as delivered: no Cyrillic in an Uzbek or English
        # document but the customer's own brand name. Never sent if it fails.
        from .scripts import artifact_violations,fields
        own=style.get('brand_name','')
        selected=data.get('revision',{}).get('selected_section_ids')
        if selected:
            # A change to selected pages delivers the others as they were, with
            # whatever the customer or an older version wrote on them; only the
            # rewritten pages are held to the alphabet.
            kept={**content,'sections':[s for s in content['sections'] if s['id'] not in selected]}
            own='\n'.join([own]+[text for _,text in fields(kept) if isinstance(text,str)])
        for artifact in artifacts:
            if artifact_violations(artifact['path'],data['output_locale'],own):
                import logging
                logging.getLogger(__name__).error('Job %s: rendered %s has Cyrillic in a %s document',job.id,artifact['name'],data['output_locale'])
                raise DomainError('script_policy',500)
    # A document that renders longer than the estimate is still the document that
    # was asked for. It is delivered, said out loud, and charged at the quote.
    allowance=bounds.get('output_pages',limits(job.account)['slides' if data['output_format']=='pptx' else 'sections'])
    if any(a['page_count']>allowance for a in artifacts):warnings.append('longer_than_quoted')
    # The renderer holds each section to its own page. When it had to shorten one
    # to do that, the customer is told rather than left to notice.
    if any(a.get('shortened') for a in artifacts):warnings.append('shortened_to_fit')
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
    data.pop('_source_seed',None)
    # A customer may edit while the provider is running. Never overwrite that
    # newer draft with the completed response for the prior confirmed version.
    GenerationDraft.objects.filter(pk=draft.pk,version=draft.version,encrypted_data=original).update(encrypted_data=pack(data),version=F('version')+1)
    return {'artifacts':artifacts,'actual_meters':actual,'metadata':{'engine':'structured-'+cfg['mode'],'warnings':warnings}}
