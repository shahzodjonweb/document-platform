import hashlib
import logging
import uuid
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from apps.core import storage
from apps.core.errors import DomainError
from apps.core.models import FileAsset,Job,Quote
from operations.integrations import ai_config
from .models import GenerationDraft,ProviderUsage
from .domain import unpack,pack,validate_content,validate_generation_quote,limits,ensure_selected_preservation,render_data
from .rendering import render_pdf
from .slides import question_sections,render_pptx

logger=logging.getLogger(__name__)

def _photos(job,sections,warnings,style='photo',candidates=None):
    """Stock photos for the slides that asked for one, or none — never a failure.

    The allowance is the plan's at the time the quote was made. Whatever goes
    wrong here — the provider, the network, the bytes, this code — the slides
    that wanted a photo are drawn as text and the customer is told. `style` is
    'illustration' when the customer asked for drawings, not photographs. Given
    `candidates`, each slide's shortlist goes there (PhotoResult.candidates).
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
    if candidates is not None:candidates.update(result.candidates)
    return result.photos


class _EarlyPhotos:
    """A deck's photos fetched from its plan while its slides are written (provider.generate's on_plan).

    Its own thread, closing its own database connections; with LOCAL_SYNC_JOBS
    (development and tests) it runs on the spot. Whatever goes wrong, the deck
    falls back to fetching its photos after writing, as it always did.
    """
    def __init__(self,job,style):
        self.job,self.style,self.started,self.future,self.pool=job,style,False,None,None

    def _fetch(self,sections):
        warnings,candidates=[],{}
        try:return _photos(self.job,sections,warnings,self.style,candidates),warnings,candidates
        finally:
            from django.conf import settings
            if not settings.LOCAL_SYNC_JOBS:
                from django.db import connections
                connections.close_all()

    def start(self,sections):
        from concurrent.futures import Future,ThreadPoolExecutor
        from django.conf import settings
        self.started=True
        if settings.LOCAL_SYNC_JOBS:
            self.future=Future()
            try:self.future.set_result(self._fetch(sections))
            except Exception as exc:self.future.set_exception(exc)
            return
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.future=self.pool.submit(self._fetch,sections)

    def result(self,warnings,candidates):
        """The photos, with their warnings and shortlists added; None when they could not be had."""
        try:
            photos,found,offered=self.future.result()
        except Exception:
            return None
        finally:
            if self.pool:self.pool.shutdown(wait=False)
        warnings.extend(found);candidates.update(offered)
        return photos

    def abandon(self):
        if self.pool:self.pool.shutdown(wait=False,cancel_futures=True)


def _keep_picture(job,draft_id,section_id,source,jpeg,**facts):
    """One picture of a deck as a file of the account's, so a later redraw needs no network.

    It expires by its own clock (cleanup_expired); settle_job moves that with
    the deck while the pins name it. `later`: a job with sixty of these never
    waits on the bucket.
    """
    name=uuid.uuid4().hex
    key=f'inputs/{job.account_id}/{name}.jpg'
    with transaction.atomic():
        storage.write(key,jpeg,'image/jpeg',later=True)
        return str(FileAsset.objects.create(account=job.account,name=f'deck-photo-{name[:12]}.jpg',object_key=key,mime_type='image/jpeg',sha256=hashlib.sha256(jpeg).hexdigest(),size_bytes=len(jpeg),page_count=1,metadata={'kind':'deck_photo','mime_type':'image/jpeg','draft_id':str(draft_id),'section_id':section_id,'provider':source['provider'],'id':source['id'],'page_url':source['page_url'],**facts},expires_at=timezone.now()+timedelta(hours=24)).pk)


def _deck_pins(job,draft_id,content,locale,artifact,photos,candidates):
    """What draws this deck again exactly (`_render`), with its pictures kept as files; None if it cannot be had.

    Never fails the job, which has a finished deck to deliver: a picture that
    cannot be kept is simply not pinned, and the failure is logged by its code
    alone. The artifact's metadata, which is not encrypted, keeps a copy under
    `render` for when the draft is gone, holding no customer text: the seed
    has the title in it, so the copy carries only its hash.
    """
    try:
        metadata=artifact['metadata']
        seed=metadata.pop('deck_seed')
        # Until the deck editor is on nothing can redraw a deck, so nothing is kept for one.
        from operations.integrations import editor_config
        if not editor_config()['deck_editor']:return None
        failures=[]
        def keep(section_id,source,jpeg,**facts):
            try:return _keep_picture(job,draft_id,section_id,source,jpeg,**facts)
            except Exception as exc:
                failures.append(type(exc).__name__)
                return None
        pictures={}
        for section in content['sections']:
            sid=section['id'];photo=photos.get(sid)
            kept=keep(sid,photo,photo['jpeg'],candidate=False,width=photo['width'],height=photo['height']) if photo else None
            # A candidate with no bytes was never shown to the model: its address is all there is.
            offered=[{'asset_id':keep(sid,hit,hit['jpeg'],candidate=True) if hit.get('jpeg') else None,'url':hit['url'],'id':hit['id'],'page_url':hit['page_url']}
                     for hit in candidates.get(sid) or []]
            if kept or offered:pictures[sid]={'asset_id':kept,'candidates':offered}
        if failures:logger.warning('Job %s: %s deck pictures not kept (%s)',job.id,len(failures),','.join(sorted(set(failures))))
        # metadata['variants'] is in slide order, and question slides are never pinned.
        slides=[*content['sections'],*question_sections(content,locale)]
        from .deck_designs import version
        pins={'design':metadata['design'],'deck_seed':seed,'body_size':metadata['body_size'],'renderer_version':version(),
              'variants':{slide['id']:variant for slide,variant in zip(slides,metadata['variants']) if not slide.get('_questions')},'photos':pictures}
        metadata['render']={**render_data(pins),'deck_seed':hashlib.sha256(seed.encode()).hexdigest(),'renderer_version':pins['renderer_version']}
        return pins
    except Exception as exc:
        logger.warning('Job %s: deck pins not made (%s)',job.id,type(exc).__name__)
        return None


def _write_pins(job,draft_id,pins,version):
    """Put the pins in the draft as it is now, changing nothing else in it, and never failing the job.

    A customer may have edited it during the job: their words stay, as does the
    version their next save will name. Packing changes the bytes a quote is tied
    to, so a quote made on this version, or a job queued on it, moves along with
    them; left behind it would fail with version_conflict over nothing it can see.
    Only a save that rebuilt the outline since `version`, the one the job drew,
    gets none: those are other slides under the same ids, with nothing drawn yet.
    `pins` may be a function that makes them from the ones the draft has now.
    """
    try:
        with transaction.atomic():
            draft=GenerationDraft.objects.select_for_update().filter(pk=draft_id,account=job.account).first()
            if draft is None:return
            before=hashlib.sha256(bytes(draft.encrypted_data)).hexdigest()
            data=unpack(draft.encrypted_data)
            if data.get('_rebuilt_version',0)>version:return
            data['_render']=pins(data['_render']) if callable(pins) else pins
            packed=pack(data)
            GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=packed)
            after=hashlib.sha256(packed).hexdigest()
            for quote in Quote.objects.select_for_update().filter(account=job.account,parameters__generation_draft_id=str(draft.pk),parameters__snapshot=before):
                quote.parameters={**quote.parameters,'snapshot':after}
                quote.save(update_fields=['parameters'])
                Job.objects.filter(quote=quote).update(parameters=quote.parameters)
    except Exception as exc:
        logger.warning('Job %s: deck pins not written (%s)',job.id,type(exc).__name__)


def execute_generation(job,output_dir):
    with transaction.atomic():
        draft=GenerationDraft.objects.select_for_update().get(id=job.parameters['generation_draft_id'],account=job.account)
        validate_generation_quote(job.account,job.quote)
        original=bytes(draft.encrypted_data)
        data=unpack(original)
    content=data['content'];cfg=ai_config();warnings=[]
    from .domain import CV
    cv=job.feature_id==CV
    if data.get('revision',{}).get('selected_section_ids'):
        # Recheck mutable plan bounds before any paid provider request. The
        # original quote cannot authorize losing untouched pages after a cap
        # change or subscription expiry while the job waited in the queue.
        ensure_selected_preservation(data,validate_content(job.account,content,data['output_format'],feature=job.feature_id))
    # Finish the provider calls while the worker still holds the job: work
    # completed after the lease lapses is thrown away by the reclaim sweep. An
    # outline's calls are held to it too, second tries included.
    import time
    deadline=time.monotonic()+max(60,(job.lease_expires_at-timezone.now()).total_seconds()-120) if job.lease_expires_at else None
    if job.parameters.get('stage')=='outline':
        from .outlines import execute_outline
        return execute_outline(job,draft,data,original,cfg,output_dir,deadline=deadline)
    # A deck written in parts side by side has its slides planned first: its
    # photos are fetched from that plan while the slides are written.
    early=_EarlyPhotos(job,(data.get('options') or {}).get('photo_style') or 'photo') if data['output_format']=='pptx' and not cv else None
    if cfg['mode']=='openai':
        from .provider import generate
        try:
            raw,usage=generate(cfg,data,job.feature_id,job.id,token_limit=job.quote.policy['generation_bounds']['input_tokens'],deadline=deadline,
                               **({'on_plan':early.start} if early else {}))
            content=validate_content(job.account,raw,data['output_format'],feature=job.feature_id)
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
            elif cv:
                # A CV's template, the same way: picked on its setup screen, it stays.
                from .cv import templates as cv_templates
                cv_templates.remember(data,raw,replace=redesign and not cv_templates.chosen(data.get('options')))
            else:doc_designs.remember(data,raw,replace=redesign)
            # The whole document is checked before it is drawn: every field in
            # its language's alphabet, and a section in the wrong language, empty
            # or repeating another sent back to the model once (quality.py).
            from . import quality
            # A change request is checked against the model's own plan of it:
            # a part it planned and left undone goes into the one repair. A CV
            # is only tidied and put in its alphabet: a repair could only invent.
            content,_=quality.finish(cfg,data,content,job=job,deadline=deadline,plan=raw.get('edit_plan'),deterministic=cv)
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
            # used to destroy the document instead. A CV cites nothing, and is
            # never failed for it: its files are its facts (prompting.schema).
            references=[]
            for ref in ([] if cv else raw.get('citations',[])):
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
            if early:early.abandon()
            raise
    else:
        warnings.append('local_fixture_not_ai_generated')
        if not any(s['body'].strip() or s.get('items') for s in content['sections']) and not content['questions']:
            raise DomainError('content_required')
    # The lines the customer dictated for a deck's title slide, set on its
    # cover as they wrote them, whatever the model did with them (title_lines.py).
    from . import title_lines
    content=title_lines.apply(data,content)
    bounds=job.quote.policy.get('generation_bounds',{})
    # Everything from here on trims the response to what was quoted instead of
    # rejecting it. The customer chose a page count, it was clamped to their plan
    # before the model was asked, and they are owed that document: a model that
    # returns an extra section, or a question nobody asked for, is our estimate
    # being off by a little, not a reason to throw a finished job away.
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
    if cv:
        # Nothing on a CV the customer did not say: a contact detail or a date
        # the model wrote that is not in their own words is taken out.
        from .cv.content import fact_check,trusted_text
        content,dropped=fact_check(content,trusted_text(data))
        if any(code.startswith('contact:') for code in dropped):warnings.append('cv_contact_dropped')
        if dropped:
            import logging
            logging.getLogger(__name__).info('Job %s: CV facts taken out: %s',job.id,dropped)
        # The portrait is read again and must still be the file that was quoted;
        # one that is not leaves the CV without it rather than failing the job.
        from .cv import portrait
        from .cv.render import render_cv
        photo,unusable=portrait.load(job.account,data)
        artifacts=[render_cv(content,output_dir/'cv.pdf',data['output_locale'],style=style,portrait=photo)]
        for code in [*((data.get('options') or {}).get('cv_warnings') or []),*unusable,
                     *artifacts[0]['metadata'].get('warnings',[])]:
            if code not in warnings:warnings.append(code)
        # Two pages hold any CV the customer can describe; when even the
        # tightest setting needed a third, its least important lines were cut.
        if artifacts[0].get('shortened'):warnings.append('cv_trimmed')
    elif ext=='pptx':
        candidates={}
        photos=early.result(warnings,candidates) if early and early.started else None
        if photos is None:photos=_photos(job,content['sections'],warnings,photo_style,candidates)
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
    # was asked for. It is delivered and said out loud, never refused.
    allowance=bounds.get('output_pages',limits(job.account)['slides' if data['output_format']=='pptx' else 'sections'])
    if any(a['page_count']>allowance for a in artifacts):warnings.append('longer_than_quoted')
    # The renderer holds each section to its own page. When it had to shorten one
    # to do that, the customer is told rather than left to notice.
    if not cv and any(a.get('shortened') for a in artifacts):warnings.append('shortened_to_fit')
    # The file is named when the task settles (apps/core/naming.py): after its
    # title — a CV's is the person's name — or else the first file it was made from.
    source_name=FileAsset.objects.filter(account=job.account,pk__in=data.get('source_ids') or []).order_by('created_at').values_list('name',flat=True).first()
    for artifact in artifacts:artifact.update(title=content.get('title',''),source_name=source_name or '')
    # Only now that the deck will be delivered: a job that fails leaves its draft
    # byte for byte as it was, which is what a retry is checked against (checkpoints.py).
    pins=_deck_pins(job,draft.pk,content,data['output_locale'],artifacts[0],photos,candidates) if ext=='pptx' and not cv else None
    data['content']=content
    data.pop('_source_seed',None)
    data.pop('_render',None)
    # A customer may edit while the provider is running. Never overwrite that
    # newer draft with the completed response for the prior confirmed version.
    GenerationDraft.objects.filter(pk=draft.pk,version=draft.version,encrypted_data=original).update(encrypted_data=pack(data),version=F('version')+1)
    # After that, and on its own: this update is the one that survives such an edit.
    if pins:_write_pins(job,draft.pk,pins,draft.version)
    return {'artifacts':artifacts,'metadata':{'engine':'structured-'+cfg['mode'],'warnings':warnings}}
