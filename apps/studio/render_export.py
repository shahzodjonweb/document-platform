"""A generated deck sent again from its saved sections and pins, with no call to anything.

A manual edit ends here: the deck is drawn again from what the draft holds, as
PowerPoint, PDF or both, with no model, no Pixabay, no photo choice and no AI
edit counted. It is a file task (allowance.quote_kind), and its quote points at
the draft instead of carrying it: ids, a hash and the format are all that a
Quote or Job row holds of it. A send never cuts what the customer wrote: a slide
whose text would not all show is refused, when quoted and when drawn alike.
"""
import hashlib
import logging
from datetime import timedelta
from pathlib import Path
from django.db import transaction
from django.utils import timezone
from apps.core import storage
from apps.core.errors import DomainError
from apps.core.models import FileAsset,Job,Quote
from apps.core.policy import POLICY_VERSION,plan_limits
from apps.core.services import owned_assets,verify_input_files
from .domain import EXPORT,SLIDES,draft_jobs,render_data,require,unpack,validate_content
from .models import GenerationDraft

logger=logging.getLogger(__name__)

FORMATS=('pptx','pdf','both')
DELIVERIES=('chat','download')
# owned_assets takes no more, whatever a plan's allowance of pictures is set to.
MAX_LISTED=50
# LibreOffice's allowance for a deck: a cold start, then a little for each slide,
# inside the ten minutes a job's lease leaves (services.execute_job).
OFFICE_SECONDS,OFFICE_SECONDS_PER_SLIDE,OFFICE_SECONDS_MOST=60,2,420
# Each holds an API worker, so the measure stops there whatever it has found (slide_fit.measure_deck). A quote that
# saw only part of a deck is still safe: the job measures every slide as it draws it (execute_render), and
# the next quote names the slides it failed on (_failed_on).
MEASURE_SECONDS=2
# The live budget beside a slide being typed, asked for far more often than a quote. Past it the slide is still
# measured, which takes up to 0.3 s more; only the list of layouts is given up.
FIT_SECONDS=0.5
# What Review says about a file before it exists, on top of its pictures. A
# PowerPoint of 60 slides of text is about 215 KB. The PDF's is a first guess:
# nothing here has run LibreOffice; step 11's renders can put numbers to it.
PPTX_BYTES,PPTX_BYTES_PER_SLIDE=40_000,3_000
PDF_BYTES,PDF_BYTES_PER_SLIDE=150_000,12_000

def _editable(draft,data):
    """Only a deck that was drawn can be drawn again: its pins are what hold it to what it looked like."""
    if draft.feature_id!=SLIDES or data.get('output_format')!='pptx' or not data.get('_render'):raise DomainError('deck_not_editable',409)

def chosen_photos(data):
    """{section id: asset id} of the pictures the deck draws: none for a slide removed or laid out without one.

    The candidates are not among them. They only wait to be chosen, and go by
    the draft's clock (services._extend_draft).
    """
    from .slide_layouts import PHOTO_ZONES
    from .slides import prepare_slides
    pinned=data['_render'].get('photos') or {}
    chosen={section['id']:pinned[section['id']]['asset_id'] for section in data['content']['sections'] if (pinned.get(section['id']) or {}).get('asset_id')}
    prepared,_=prepare_slides(data['content'],data['output_locale'],chosen)
    return {section['id']:chosen[section['id']] for kind,_,section in prepared if kind in PHOTO_ZONES and section.get('id') in chosen}

def _missing_pictures(account,data,chosen):
    """The slides of `chosen` whose picture is expired, deleted or gone, as a refusal can name them."""
    found={str(asset.pk) for asset in FileAsset.objects.filter(account=account,pk__in=chosen.values(),state='ready',expires_at__gt=timezone.now()) if storage.exists(asset.object_key)}
    positions={section['id']:index for index,section in enumerate(data['content']['sections'])}
    return [{'id':section_id,'index':positions[section_id]} for section_id,asset_id in chosen.items() if asset_id not in found]

def over_budget(data,chosen):
    """The slides whose text would not all show, as `slide_text_too_long` names them: the first of them, if there are very many."""
    from .branding import drawn_style
    from .slide_fit import measure_deck
    measured=measure_deck(data['content'],data['output_locale'],drawn_style(data),data['_render'],chosen,seconds=MEASURE_SECONDS)
    return [{'id':slide['id'],'index':slide['index'],'words_over':slide['words_over']} for slide in measured if not slide['fits']]

def _failed_on(account,draft_id,snapshot):
    """The slides a send of the draft, to the byte as it stands, failed for being too long: its bytes draw the same again.

    All a customer has to go on when a long deck is past what the quote can
    measure, and it costs no measuring.
    """
    failed=Job.objects.filter(account=account,feature_id=EXPORT,error_code='slide_text_too_long',parameters__generation_draft_id=str(draft_id),parameters__snapshot=snapshot).order_by('-created_at').first()
    return failed.parameters.get('too_long') if failed else None

def export_quote(account,draft_id,version,fmt,deliver):
    """A pointer to the draft as it stands, refused now for anything that would stop it being sent.

    Parsing nothing and running nothing but the measure of its slides, it is
    safe in the API process. Modelled on domain.generation_quote.
    """
    if fmt not in FORMATS or deliver not in DELIVERIES:raise DomainError('invalid_parameters')
    d=GenerationDraft.objects.filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    require(account,EXPORT)
    from apps.core.channel_gate import require as require_channels
    require_channels(account)
    if version!=d.version:raise DomainError('version_conflict',409)
    if draft_jobs(account,d.id,('queued',)):raise DomainError('generation_running',409)
    data=unpack(d.encrypted_data)
    _editable(d,data)
    if fmt!='pptx':
        from processors.engine import office_runtime
        if not office_runtime()['available']:raise DomainError('engine_unavailable',409)
    # The brand name and colour are still the plan's to have. A logo no longer stored only leaves the logo out (_style).
    from .branding import prepare_branding,without_logo
    prepare_branding(account,EXPORT,without_logo(data)['options'])
    chosen=chosen_photos(data)
    missing=_missing_pictures(account,data,chosen)
    if missing:raise DomainError('pinned_asset_expired',409,{'sections':missing})
    snapshot=hashlib.sha256(bytes(d.encrypted_data)).hexdigest()
    over=_failed_on(account,d.id,snapshot) or over_budget(data,chosen)
    if over:raise DomainError('slide_text_too_long',409,{'sections':over})
    # The pictures it draws, each held to the bytes quoted and kept from cleanup while the job waits.
    limits=plan_limits(account)
    listed=list(dict.fromkeys(chosen.values()))[:min(MAX_LISTED,int(limits.get('max_deck_images',0) or 0))]
    fingerprints=[{'id':str(asset.id),'sha256':asset.sha256} for asset in owned_assets(account,listed)] if listed else []
    quote=Quote(account=account,feature_id=EXPORT,input_ids=listed,input_fingerprints=fingerprints,
                parameters={'generation_draft_id':str(d.id),'version':d.version,'snapshot':snapshot,'format':fmt,'deliver':deliver},
                policy={'plan':account.plan,'version':POLICY_VERSION,'tariff_version':'deck-render-v1','limits':limits,'lease_seconds':300},
                expires_at=timezone.now()+timedelta(minutes=10))
    # Said before the customer confirms, not after. Submission checks again under the account lock.
    from apps.core.allowance import require_quote
    require_quote(account,quote)
    quote.save()
    return quote

def quote_summary(account,quote):
    """What the Review sheet says about a send: its slides, its files' rough size, how long it stays and what it uses.

    `warnings` says now what the file will come without: a logo no longer stored.
    """
    from apps.core.allowance import usage_snapshot
    from .branding import logo_kept
    from .slides import question_sections
    data=unpack(GenerationDraft.objects.get(account=account,pk=quote.parameters['generation_draft_id']).encrypted_data)
    slides=len(data['content']['sections'])+len(question_sections(data['content'],data['output_locale']))
    pictures=sum(FileAsset.objects.filter(account=account,pk__in=chosen_photos(data).values()).values_list('size_bytes',flat=True))
    fmt=quote.parameters['format'];size=0
    if fmt!='pdf':size+=PPTX_BYTES+PPTX_BYTES_PER_SLIDE*slides+pictures
    if fmt!='pptx':size+=PDF_BYTES+PDF_BYTES_PER_SLIDE*slides+pictures
    allowance=usage_snapshot(account)['file_jobs']
    return {'slides':slides,'format':fmt,'kept_until':timezone.now()+timedelta(hours=24),'size_estimate':size,
            'cost':{'kind':'included','left':None,'limit':None} if allowance['limit'] is None else {'kind':'file_task','left':allowance['remaining'],'limit':allowance['limit']},
            'warnings':[] if logo_kept(account,data) else ['logo_left_out']}

def fit_section(account,draft_id,section):
    """How one slide as the customer is typing it sits on its deck, and which layouts would hold it whole.

    Nothing is saved or kept. A section with no id, or one the deck does not
    have, is measured as a slide added at the end.
    """
    if not isinstance(section,dict):raise DomainError('invalid_parameters')
    d=GenerationDraft.objects.filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    require(account,EXPORT)
    data=unpack(d.encrypted_data)
    _editable(d,data)
    sections=data['content']['sections']
    section={**section,'id':str(section.get('id') or 'new-slide')[:40]}
    edited=[section if old['id']==section['id'] else old for old in sections]
    if not any(old['id']==section['id'] for old in sections):edited.append(section)
    # As a save would hold it to the deck's bounds, and the plan's count of slides.
    content=validate_content(account,{**data['content'],'sections':edited},'pptx',feature=d.feature_id)
    if not any(old['id']==section['id'] for old in content['sections']):raise DomainError('generation_limit')
    from .branding import drawn_style
    from .slide_fit import measure_deck
    drafted={**data,'content':content}
    measured=measure_deck(content,data['output_locale'],drawn_style(data),data['_render'],chosen_photos(drafted),only={section['id']},seconds=FIT_SECONDS)
    return measured[0]

def pinned_assets(account,ids):
    """The pictures a send listed, or `pinned_asset_expired`: to a customer it is that, not a file they lost."""
    if not ids:return []
    try:return owned_assets(account,ids)
    except DomainError as exc:
        if exc.code=='file_unavailable':raise DomainError('pinned_asset_expired',409) from None
        raise

def pinned_files(job):
    """The pictures a send listed, verified on disk. One gone from the disk with no copy to fetch is `pinned_asset_expired` too; bytes that differ are `file_changed`."""
    assets=pinned_assets(job.account,job.input_ids)
    if not all(storage.local(asset.object_key).is_file() for asset in assets):raise DomainError('pinned_asset_expired',409)
    return verify_input_files(job,assets)

def validate_render_quote(account,quote):
    """Whether a quote still draws what it was quoted on: this version of the draft, to the byte, and its pictures."""
    require(account,quote.feature_id)
    parameters=quote.parameters
    d=GenerationDraft.objects.filter(id=parameters.get('generation_draft_id'),account=account,expires_at__gt=timezone.now()).first()
    if not d or d.version!=parameters.get('version') or hashlib.sha256(bytes(d.encrypted_data)).hexdigest()!=parameters.get('snapshot'):raise DomainError('version_conflict',409)
    return pinned_assets(account,quote.input_ids)

def _pictures(account,chosen):
    """{section id: picture} from the account's files, as render_pptx takes them; every one of them, or the job fails."""
    assets={str(asset.pk):asset for asset in FileAsset.objects.filter(account=account,pk__in=chosen.values(),state='ready',expires_at__gt=timezone.now())}
    found={}
    for section_id,asset_id in chosen.items():
        asset=assets.get(asset_id)
        if asset is None:raise DomainError('pinned_asset_expired',409)
        try:jpeg=storage.read_bytes(asset.object_key)
        except OSError:raise DomainError('pinned_asset_expired',409) from None
        if hashlib.sha256(jpeg).hexdigest()!=asset.sha256:raise DomainError('file_changed',409)
        found[section_id]={'jpeg':jpeg,**{key:asset.metadata.get(key) for key in ('width','height','provider','id','page_url')}}
    return found

def _style(job,data,warnings):
    """The look as a generation reads it (branding.render_style), but a logo no longer stored costs the send only the logo.

    The customer is told, at the quote and on the file. Refused, they would have
    no way past it but to make another deck, when the file keeps its colour and
    name. The bytes of a logo that is there are still held to what was chosen.
    """
    from .branding import logo_kept,render_style,without_logo
    if logo_kept(job.account,data):return render_style(job.account,data,feature_id=job.feature_id)
    warnings.append('logo_left_out')
    return render_style(job.account,without_logo(data),feature_id=job.feature_id)

def own_words(texts):
    """The customer's words as a design may set them: in capitals, or as the initials it draws for a card or a name (one letter, or quote_1's two)."""
    found=[*texts,*(text.upper() for text in texts)]
    for text in texts:
        # Across lines too: a name on two lines is one name to the drawers, as quote_1._who reads it.
        initials=[next(character.upper() for character in word if character.isalnum()) for word in text.split() if any(character.isalnum() for character in word)]
        found+=[*initials,*(first+second for first,second in zip(initials,initials[1:]))]
    return '\n'.join(found)

def execute_render(job,output_dir):
    """The deck, drawn again from the draft as it was quoted, and nothing else: no model, no photo search, no change to its words."""
    with transaction.atomic():
        draft=GenerationDraft.objects.select_for_update().filter(id=job.parameters.get('generation_draft_id'),account=job.account).first()
        # Read under the lock: a job writing pins moves the quote along with the bytes (execution._write_pins).
        validate_render_quote(job.account,Quote.objects.get(pk=job.quote_id))
        data=unpack(draft.encrypted_data)
    content,locale,pins=data['content'],data['output_locale'],data['_render']
    warnings=[]
    style=_style(job,data,warnings)
    pictures=_pictures(job.account,chosen_photos(data))
    from .slides import render_pptx
    deck=render_pptx(content,Path(output_dir)/'document.pptx',locale,'user_document',style=style,photos=pictures,pins=pins)
    metadata=deck['metadata']
    # Never a shortened file: it changed under a stale client, or the measure and the drawing differ. Nothing is counted.
    if metadata['shortened']:
        # The refusal's list would go with the job, which keeps only its code: the next quote gives it (_failed_on).
        Job.objects.filter(pk=job.pk).update(parameters={**job.parameters,'too_long':metadata['shortened']})
        raise DomainError('slide_text_too_long',409,{'sections':metadata['shortened']})
    if len(metadata['photos'])<len(pictures):warnings.append('images_skipped')
    # The file as delivered holds no word in the wrong alphabet but the customer's own.
    from .scripts import artifact_violations,fields
    own=own_words([style.get('brand_name','')]+[text for _,text in fields(content) if isinstance(text,str)])
    if artifact_violations(deck['path'],locale,own):
        logger.error('Job %s: rendered deck has Cyrillic that is not the customer\'s in a %s document',job.id,locale)
        raise DomainError('script_policy',500)
    drawn=dict(zip((section['id'] for section in content['sections']),metadata['variants']))
    changed={section_id:drawn[section_id] for section_id in metadata['repinned']}
    # As with a generation: the title stays out of what is kept with the file (execution._deck_pins).
    seed=metadata.pop('deck_seed')
    metadata['render']={**render_data({**pins,'variants':{**pins.get('variants',{}),**changed}}),'deck_seed':hashlib.sha256(seed.encode()).hexdigest(),'renderer_version':pins.get('renderer_version')}
    fmt=job.parameters.get('format','pptx')
    artifacts=[deck]
    if fmt!='pptx':
        from processors.sandbox import execute_sandbox
        seconds=min(OFFICE_SECONDS_MOST,OFFICE_SECONDS+OFFICE_SECONDS_PER_SLIDE*deck['page_count'])
        pdf=execute_sandbox('convert.pptx_to_pdf',[deck['path']],{},Path(output_dir)/'pdf',timeout=seconds+30,office_timeout=seconds)['artifacts'][0]
        artifacts=[deck,pdf] if fmt=='both' else [pdf]
        if fmt=='pdf':Path(deck['path']).unlink()
    source_name=FileAsset.objects.filter(account=job.account,pk__in=data.get('source_ids') or []).order_by('created_at').values_list('name',flat=True).first()
    for artifact in artifacts:artifact.update(title=content.get('title',''),source_name=source_name or '')
    # Only now that the file will be delivered: a job that fails leaves its draft as it was.
    # A slide that took another variant keeps it from here on, and nothing else in the draft moves.
    if changed:
        from .execution import _write_pins
        _write_pins(job,draft.pk,lambda current:{**current,'variants':{**current.get('variants',{}),**changed}},draft.version)
    return {'artifacts':artifacts,'metadata':{'engine':'deck-render','warnings':warnings}}
