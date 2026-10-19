"""Versioned authoring, encrypted drafts and role-aware generated artifacts."""
import hashlib
from copy import deepcopy
import json
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import Quote
from apps.core.policy import FEATURES, POLICY_VERSION, plan_limits
from apps.core.services import owned_assets
from apps.core import storage
from operations.integrations import cipher, ai_config
from .models import GenerationDraft

# Three services: a document, slides, or a CV. Everything the retired features
# encoded — audience, tone, subject, question count, structure — is said in the
# description instead, and the description is already the prompt. The retired
# ids stay in FEATURES so drafts and jobs made before this still resolve their
# names; they just cannot be authored any more. A CV is a PDF like a document,
# and is counted, quoted, edited and reviewed like one; what makes it a CV is
# keyed on its id (apps/studio/cv/).
DOCUMENT='ai.pdf_topic'
SLIDES='ai.pptx'
CV='ai.cv'
GENERATION_IDS={DOCUMENT,SLIDES,CV}
# Server-owned fields a client may never send.
READONLY_FIELDS={'_transcription','transcription_ready','transcription_reviewed','_source_seed','revision'}

def pack(value): return cipher().encrypt(json.dumps(value,ensure_ascii=False).encode())
def unpack(value): return json.loads(cipher().decrypt(bytes(value)))
def allowed(account,fid):
    return fid in FEATURES and FEATURES[fid]['plans'][account.plan] not in ('not_included','unavailable','none','excluded')
def require(account,fid):
    if not settings.ENABLE_BETA_TOOLS or fid not in GENERATION_IDS: raise DomainError('feature_unavailable',409)
    if not allowed(account,fid): raise DomainError('feature_not_in_plan',403)

# Questions a document may carry, the same on every plan (it was 10 on Free, 50
# on Plus and 150 on Premium). The last writing call writes every question
# beside up to PAGES_PER_CALL pages, and one reply is held to RESPONSE_CEILING
# (pages.call_tokens): 41 fit beside ten pages, and a cut-off reply retried at
# the same ceiling fails the same way. The provider's schema check also refuses
# any array of more than 100 items. So the cap is 40, not what Premium had.
MAX_QUESTIONS=40

def limits(account):
    seed=plan_limits(account)
    # Source text has to fit the request budget alongside the document itself, so
    # it is half of it rather than three times it. Promising more source than a
    # call can carry only moves the refusal later.
    return {'sections':seed['max_generated_pdf_pages'], 'slides':seed['max_generated_slides'], 'questions':MAX_QUESTIONS, 'source_chars':seed['max_ai_input_tokens']//2}

def validate_content(account,content,output_format='pdf',feature=None):
    """Bring a model response inside the plan, trimming rather than refusing.

    The page count was clamped to the plan before the model was ever asked, so
    anything over it here is the model overrunning its brief. That is not the
    customer's mistake and it costs them nothing: it is cut back to what was
    quoted. Only content that is unusable — the wrong shape, or empty — is
    refused.

    A CV (`feature` CV) always has its eight sections, whatever the plan's page
    cap says — they are parts of one or two pages, not pages — and its entries
    are held to the CV's own lengths (cv/content.py clean_fields).
    """
    if not isinstance(content,dict): raise DomainError('invalid_parameters')
    caps=limits(account)
    title=str(content.get('title','Document'))[:160]
    sections=content.get('sections',[])
    max_sections=caps['slides'] if output_format=='pptx' else caps['sections']
    if feature==CV:
        from .cv.content import SECTION_IDS
        max_sections=max(max_sections,len(SECTION_IDS))
    if not isinstance(sections,list): raise DomainError('invalid_parameters')
    if not sections: raise DomainError('content_required')
    from . import pages as paging
    body_cap=paging.max_section_chars(output_format)
    clean=[]
    for i,s in enumerate(sections[:max_sections]):
        if not isinstance(s,dict): raise DomainError('invalid_parameters')
        clean.append({'id':str(s.get('id',f's{i+1}'))[:40],'heading':str(s.get('heading',s.get('title','')))[:160],'body':str(s.get('body',''))[:body_cap],'notes':str(s.get('notes',''))[:2000]})
        # A slide also carries the layout it chose and what fills it. A document
        # section does only when it is more than text (a table, a list, a photo);
        # a plain one keeps exactly its four keys.
        try:
            if output_format=='pptx':
                from .layouts import clean_slide_fields
                clean[-1].update(clean_slide_fields(s))
            elif feature==CV:
                from .cv.content import clean_fields as clean_cv
                clean[-1].update(clean_cv(s))
            else:
                from .doc_designs import clean_fields
                clean[-1].update(clean_fields(s))
        except ValueError:raise DomainError('invalid_parameters') from None
    questions=content.get('questions',[])
    if not isinstance(questions,list): raise DomainError('invalid_parameters')
    questions=questions[:caps['questions']]
    qs=[]
    for i,q in enumerate(questions):
        if not isinstance(q,dict): raise DomainError('invalid_parameters')
        opts=q.get('options',[])
        if not isinstance(opts,list) or len(opts)>8: raise DomainError('invalid_parameters')
        marks=q.get('marks',1)
        if type(marks)!=int or not 1<=marks<=100: raise DomainError('invalid_parameters')
        qs.append({'id':str(q.get('id',f'q{i+1}'))[:40],'stem':str(q.get('stem',''))[:2000],'options':[str(v)[:500] for v in opts],'answer':str(q.get('answer',''))[:2000],'explanation':str(q.get('explanation',''))[:3000],'topic':str(q.get('topic',title))[:100],'marks':marks})
    if len({q['id'] for q in qs})!=len(qs): raise DomainError('invalid_parameters')
    citations=content.get('citations',[])
    if not isinstance(citations,list) or len(citations)>100 or any(not isinstance(c,dict) or len(json.dumps(c))>4000 for c in citations):raise DomainError('invalid_parameters')
    if len({section['id'] for section in clean})!=len(clean):raise DomainError('invalid_parameters')
    return {'title':title,'sections':clean,'questions':qs,'citations':citations}

def ensure_selected_preservation(data,normalized):
    """Reject normalization that would silently alter an untouched selection.

    Stored content was valid when authored, but an account downgrade or changed
    plan limits can make today's normalizer trim it. A scoped revision must keep
    the whole existing document; needing a smaller plan allowance is a refusal,
    never permission to discard the other pages or questions.
    """
    selected=data.get('revision',{}).get('selected_section_ids')
    if not selected:return
    original=data['content']
    if ([s['id'] for s in normalized['sections']]!=[s['id'] for s in original['sections']]
            or normalized['title']!=original['title']
            or normalized['questions']!=original.get('questions',[])
            or [s for s in normalized['sections'] if s['id'] not in selected]
               !=[s for s in original['sections'] if s['id'] not in selected]):
        raise DomainError('generation_limit')

def draft_data(d):
    data=unpack(d.encrypted_data)
    data.pop('_source_seed',None)
    if data.get('revision'):
        data['revision']={key:value for key,value in data['revision'].items() if key not in ('base_content','before')}
    return {'id':str(d.id),'feature_id':d.feature_id,'version':d.version,'provider_mode':d.provider_mode,'expires_at':d.expires_at,**data,'outline':[{'id':s['id'],'title':s['heading'],'body':s['body']} for s in data['content']['sections']]}

def source_excerpts(account,ids):
    if not ids:return []
    assets=owned_assets(account,ids)
    # How many files a document may be built from follows the plan rather than
    # being the same five for everyone; total pages is capped separately.
    caps=plan_limits(account)
    if len(assets)>caps.get('max_ai_source_files',5) or sum(a.page_count for a in assets)>caps['max_ai_source_pages']:raise DomainError('generation_limit')
    # Extraction is performed in the bounded parser child, not inside the HTTP worker.
    result=[]
    for a in assets:
        if a.mime_type!='application/pdf' or a.metadata.get('encrypted'):raise DomainError('unsupported_file')
        from .extraction import extract_pages
        for page,text in extract_pages(storage.local(a.object_key)):
            result.append({'asset_id':str(a.id),'page':page,'text':text[:12000]})
    if sum(len(v['text']) for v in result)>limits(account)['source_chars']:raise DomainError('generation_limit')
    return result

def edit_root(data,draft_id):
    """The file a draft's edits are counted against: the first document of its chain.

    An edit of an edit draws on the same file's edits as the first one did. A
    change made before roots were recorded counts against the document it changed.
    """
    revision=data.get('revision') or {}
    return str(revision.get('root_draft_id') or revision.get('source_draft_id') or draft_id)

def revision_source(account,identifier):
    """The document a change request is being applied to."""
    import uuid as _uuid
    try:identifier=_uuid.UUID(str(identifier))
    except (ValueError,TypeError):raise DomainError('invalid_parameters') from None
    source=GenerationDraft.objects.filter(account=account,id=identifier,expires_at__gt=timezone.now()).first()
    if not source:raise DomainError('not_found',404)
    original=unpack(source.encrypted_data)
    # A slide can be finished with nothing in its body — a stats slide is all
    # items — so items count as content too.
    if not any((section.get('body') or '').strip() or section.get('items') for section in original['content']['sections']):
        raise DomainError('revision_not_ready')
    # Text alone does not make a file: a new draft holds its source text from
    # the start. Only a file that was actually made can be edited, or an "edit"
    # of a draft never generated would be a new document outside the week's
    # limit (apps/core/allowance.py require_made). Quoting and submitting the
    # edit ask again.
    from apps.core.allowance import require_made
    require_made(account,edit_root(original,source.id))
    return source,original


def _image_cap(account,fid):
    """How many photo layouts a deck may ask for: the plan's allowance, when photos are on.

    Set here rather than taken from the client, the same way the page and
    question counts are.
    """
    # A CV's only picture is the customer's own portrait.
    if fid not in GENERATION_IDS or fid==CV:return 0
    from operations.integrations import pixabay_config
    if not pixabay_config()['ready']:return 0
    return int(plan_limits(account).get('max_deck_images',0) or 0)

def _pictures_wanted(edit,before,sections_count,fmt,cap):
    """The pictures a change that asks for them leaves the document with, within the plan's allowance.

    `before` is the document's sections as they stand. Its content pages are
    every page but a deck's cover, closing slide and section dividers, and a
    title page the change adds to a document; a deck's cover photo is not one
    of its pictures and takes one of the allowance. 'every' is a picture on
    each content page; 'add' is the pictures it has and those added: as many
    as it names, else about one content page in three, at least one. On a plan
    that adds none the request's count is kept, so the review can say the plan
    adds none and offer the one that does; the model is asked for none then.
    """
    from .photos import wanted
    deck=fmt=='pptx'
    cover=before[0] if deck and before else None
    pictured=wanted(before)
    had=[section for section in pictured if section is not cover]
    fixed=sum(1 for section in before if section is cover or section.get('layout') in ('cover','closing','section'))
    if not deck and 'title_page' in (edit.parts or []):fixed+=1
    content=max(1,sections_count-fixed)
    total=content if edit.pictures=='every' else len(had)+(edit.picture_count or max(1,round(content/3)))
    if not cap:return total
    return min(total,max(0,cap-(len(pictured)-len(had))))

def _deck_style(fid,brief):
    """A deck's look, read out of the description like its slide count.

    There is no colour field: "a dark deck in navy" is the brief saying so. A
    design picked on the review screen (`options.deck_design`) replaces all of
    this in `_prepare_draft`. Account branding still overrides the accent later, because
    a brand colour is a fact about the customer rather than a preference. A
    document has no deck theme; it takes only the colour.
    """
    from . import pages as paging
    colours=paging.requested_colours(brief)
    # A document takes a colour it is asked for too, over its design's own.
    if fid!=SLIDES:
        return {'accent':colours[0],'accent_fixed':True} if colours else {}
    # Only what the brief actually names is fixed; the rest is the design the
    # model chooses (apps/studio/deck_designs.py). A second colour named
    # ("ko'k, yashil va qizil") becomes the deck's second colour.
    style={}
    theme=paging.requested_theme(brief)
    if theme:style['deck_theme']=theme
    if colours:style.update(accent=colours[0],accent_fixed=True)
    if len(colours)>1:style['secondary']=colours[1]
    return style

def _prepare_draft(account,data,revision_base=None):
    if set(data)&READONLY_FIELDS:raise DomainError('invalid_parameters')
    fid=data.get('feature_id',DOCUMENT);require(account,fid)
    # The service decides the format; the client does not get a say. A document
    # is a PDF and a deck is a PowerPoint. The value is still validated so a
    # malformed one is refused rather than silently ignored, and the forcing
    # happens after the revision block below, which inherits the original's
    # format — a change request against a draft made before slides became
    # PowerPoint would otherwise come back as a PDF.
    if data.get('output_format') not in (None,'pdf','pptx'):raise DomainError('invalid_parameters')
    from . import language
    requested=data.get('output_locale')
    if requested is not None and requested not in language.SUPPORTED:raise DomainError('invalid_locale')
    title=str(data.get('title',data.get('topic','Untitled document'))).strip()[:160] or 'Untitled document'
    text=data.get('source_text',data.get('text',''))
    prompt=data.get('prompt',title)
    if not isinstance(text,str) or not isinstance(prompt,str):raise DomainError('invalid_parameters')
    if len(text)+len(prompt)>limits(account)['source_chars']:raise DomainError('generation_limit')
    ids=data.get('source_ids',data.get('input_ids',[]))
    excerpts=source_excerpts(account,ids)
    if len(text)+len(prompt)+sum(len(s['text']) for s in excerpts)>limits(account)['source_chars']:raise DomainError('generation_limit')
    options=data.get('options',data.get('parameters',{}))
    if not isinstance(options,dict) or len(json.dumps(options))>4000 or set(options)&READONLY_FIELDS:raise DomainError('invalid_parameters')
    # A change request inherits the document it applies to: same service, same
    # format, same sources. Only what the customer asks to change may change.
    revising=options.get('revise_draft_id')
    saved_revision=(revision_base or {}).get('revision',{})
    if saved_revision.get('selected_section_ids') and str(revising)!=saved_revision.get('source_draft_id'):
        raise DomainError('invalid_parameters')
    original=None
    selection=[]
    source_version=None
    if not revising and {'revise_section_ids','revise_base_version'} & set(options):raise DomainError('invalid_parameters')
    if revising:
        saved=(revision_base or {}).get('revision',{})
        # Once created, a selected revision owns an immutable snapshot. Saving its
        # wording cannot silently pick up later edits to the original document.
        if saved.get('selected_section_ids') and str(revising)==saved.get('source_draft_id'):
            original={**revision_base,'content':deepcopy(saved['base_content'])}
            source_version=saved['base_version']
        else:
            source,original=revision_source(account,revising)
            fid=source.feature_id
            source_version=source.version
        require(account,fid)
        from .revisions import selected_ids
        selection=selected_ids(options,original['content'],source_version)
        if saved.get('selected_section_ids') and selection!=saved['selected_section_ids']:raise DomainError('invalid_parameters')
        ids=original['source_ids'];excerpts=original['excerpts']
        title=original['title'] if revision_base is None else title
        text=original.get('source_text','')
        if not prompt.strip():raise DomainError('prompt_required')
        # Revisions inherit the confirmed look as well as the document. A typo
        # request has no template/theme instructions and must not reset either.
        inherited=(revision_base or original).get('options',{})
        for field,default in (('template_id','clean'),('branding',{})):
            previous=inherited.get(field,default)
            if selection and field in options and (options[field] or default)!=(previous or default):
                raise DomainError('invalid_parameters')
            if field not in options and (field in inherited or field=='template_id'):
                options={**options,field:deepcopy(previous)}
    fmt='pptx' if fid==SLIDES else 'pdf'
    # A CV is written from what the customer says about themselves, in one
    # message: there is nothing in a PDF for it to be made from.
    cv=fid==CV
    if cv and (ids or excerpts):raise DomainError('invalid_parameters')
    # Length and question count are read out of the description rather than
    # asked for separately: one section is one page, and questions are priced,
    # so they appear only when the description asks for them. `requested_pages`
    # is kept beside the resolved count so a clamp can be shown, not hidden.
    from . import pages as paging
    brief=prompt if original is not None else f'{prompt}\n{text}'
    # What a change to the whole document asks for is read by rule before it is
    # priced (apps/studio/edits.py): pages added or removed, a plan or a title
    # page, pictures and their kind, a test added or taken away, a new look. The
    # bot offers no count or design for a change: the request alone decides.
    # A change to selected pages reads none of it; it may not resize or restyle.
    edit=None
    # A CV change that asks for no pictures ("rasmsiz") takes its portrait away.
    portrait_removed=False
    # What the document had, for a change to the whole of it. Rewording a change
    # (the web saves it again) starts from the document, not from the first
    # wording's draft: a design or a test that wording dropped is the
    # document's again unless the new one drops it too. A selected change's
    # `original` is already its snapshot.
    before_options=original.get('options',{}) if original is not None else {}
    if original is not None and not selection:
        from . import edits as editing
        read=original['content']['sections']
        if cv and before_options.get('portrait_asset_id'):
            # A CV's one picture is its portrait, so "rasmsiz" has one to take away.
            read=[{**section,'image_query':'portrait'} if section.get('id')=='profile' else section for section in read]
        edit=editing.read(prompt,fmt=fmt,sections=read,
                          questions=len(original['content'].get('questions',[])))
        # Another file format is not a change to the document: the bot sends a
        # deck to PowerPoint → PDF and offers a new deck for a document, and
        # the web says so, rather than charging an edit that rewrites nothing.
        if edit.format_only:raise DomainError('format_only_change')
        if cv:
            # A change to a CV is a change to what it says. It has no pages to
            # add or move, no test and no pictures but the portrait: "add a page
            # for projects" is read as structural, and a structural change sends
            # the model the CV as bare ids. Only a new look, more detail and the
            # format are kept; the portrait rule is read first.
            portrait_removed=edit.pictures=='remove'
            edit=editing.Edit(redesign=edit.redesign,format=edit.format,format_only=edit.format_only,expand=edit.expand)
    # One language for the whole document, decided here and stored with the
    # draft: a language picked for this request (the studio's menu, the bot's
    # review button), then one the description names, then — for a change —
    # the document's own, then Russian for a description written in Russian,
    # then the request's, the account's settings and English. Every later
    # stage reads the result; none reads the description for a language again
    # (apps/studio/language.py).
    picked=requested if options.get('locale_chosen') is True else None
    previous=revision_base or {}
    # The studio sends back the language it was shown. One that came from the
    # description is not a request of its own, or rewording the description
    # could never change it again.
    if (picked is None and requested is not None and requested==previous.get('output_locale')
            and previous.get('locale_source') in ('prompt','prompt_language','document')):
        requested=None
    # A selected-page change cannot translate the whole document, and the pages
    # it leaves alone must not change: it keeps the source document's language,
    # whatever it names or picks. That language is kept with the revision when
    # it is created; a saved revision's own output_locale is only its last result.
    base_locale=(saved_revision.get('base_locale') or original.get('output_locale')) if selection else None
    if base_locale in language.SUPPORTED:
        resolved=language.Resolution(base_locale,'document')
    else:
        resolved=language.resolve(prompt,picked=picked,requested=requested,settings=language.settings_locale(account),
                                  document=original['output_locale'] if original is not None else None)
    locale=resolved.locale
    # Uzbek is written only in the Latin alphabet (owner's rule, 2026-10-12),
    # whatever alphabet the description used. The option stays for older clients.
    uz_script='latn'
    # A count chosen on the review screen beats the one read from the
    # description: it is how a misread count gets put right before paying.
    chosen=options.get('pages')
    if cv:
        # A CV is one page or two, and the renderer decides which: a count sent
        # by an older client is dropped, not refused.
        chosen=None;options={key:value for key,value in options.items() if key!='pages'}
    # So does a design chosen there: "Auto" leaves it to the model, as before.
    picked=options.get('deck_design')
    if picked is not None:
        from .deck_designs import DESIGNS,current
        # A draft saved with a design since retired keeps working, as its replacement.
        picked=current(picked)
        if fid!=SLIDES or picked!='auto' and picked not in DESIGNS:raise DomainError('invalid_parameters')
        options={**options,'deck_design':picked}
    # A CV's template, picked on its setup screen or in the studio; "auto" is the model's choice.
    template=options.get('cv_template')
    if template is not None:
        from .cv.templates import TEMPLATES,current as current_template
        if not cv or not isinstance(template,str):raise DomainError('invalid_parameters')
        template=current_template(template)
        if template!='auto' and template not in TEMPLATES:raise DomainError('invalid_parameters')
        options={**options,'cv_template':template}
    if cv:
        # Its eight sections, always, for a new CV and a change alike.
        from .cv.content import SECTION_IDS
        length,asked=(len(original['content']['sections']) if original is not None else len(SECTION_IDS)),None
    elif chosen is not None:
        if type(chosen) is not int or not 1<=chosen<=200:raise DomainError('invalid_parameters')
        length,asked=min(chosen,paging.ceiling(account,fmt)),chosen
    elif edit is not None:
        # A change keeps the document's length unless the request names a new
        # total, which wins, or adds or removes pages or parts ("bitta sahifa
        # qo'sh", "reja, kirish va xulosa ham bo'lsin"). A total of one is not
        # taken from a change request: "har 1ta slaydga rasm" (a picture on every
        # slide) once made a nine-slide deck one, and "add 1 page" is one more.
        # A deck's title page is its cover and adds no slide: "Boshiga bitta
        # sahifa qo'sh … deb yoz" writes the lines on the cover, where a second
        # title slide once followed it.
        if edit.total and edit.total>=2:
            asked=edit.total;length=min(asked,paging.ceiling(account,fmt))
        else:
            added=editing.added_parts(edit.parts,fmt)
            asked=None;length=max(1,len(original['content']['sections'])+edit.delta+len(added))
    elif selection:
        # A change to selected pages cannot resize the document: one that names
        # a new size in so many words is refused below. Read as a change is, so
        # "fix the typos on slide 2 and slide 6" names no size.
        from . import edits as editing
        asked=editing.read(prompt,fmt=fmt,sections=original['content']['sections']).total
        length=len(original['content']['sections'])
    else:
        length,asked=paging.resolve(account,brief,fmt)
    if selection:
        if asked is not None and asked!=len(original['content']['sections']):raise DomainError('invalid_parameters')
        length=len(original['content']['sections'])
    # Local authoring has no model to write the pages, so an unasked-for default
    # would render as blank ones. Follow the material that was actually given.
    # A CV keeps its eight sections: the bot sends its description as source
    # text locally, and its paragraphs are not sections.
    if original is None and asked is None and not cv and ai_config()['mode']=='local_fixture':
        supplied=len([p for p in (text or '\n\n'.join(x['text'] for x in excerpts)).split('\n\n') if p.strip()])
        if supplied:length=min(supplied,paging.ceiling(account,fmt))
    question_count=min(paging.requested_questions(brief),limits(account)['questions'])
    # The questions a change leaves the document with: none once removed, the
    # number asked for ("savollar slaydini 1 bet qil" is five), or a test of ten
    # (five on a deck) when it asks for one without a number — "Test tuz" used to
    # find no number and add nothing.
    kept=None
    if edit is not None:
        existing=len(original['content'].get('questions',[]))
        if edit.questions=='remove':question_count=kept=0
        elif edit.questions=='add':
            # "10 ta savol qo'sh" adds ten to those the document has; "savollar 5
            # ta bo'lsin" and "leave only 5 questions" are the test's new size,
            # and one smaller than it is cuts the test to it.
            if edit.more_questions:question_count=existing+edit.question_count
            else:question_count=edit.question_count or max(existing,5 if fid==SLIDES else 10)
            if question_count<existing:kept=question_count
        elif edit.question_count:question_count=kept=edit.question_count
        else:question_count=0
        question_count=min(question_count,limits(account)['questions'])
        if kept is not None:kept=min(kept,existing)
    # A CV has no test, whatever its description says ("5 ta savolga javob").
    if cv:question_count,kept=0,None
    # A deck's questions go on slides of their own at the end, five to a slide,
    # and those slides are part of the count: "10 slides, 5 questions at the
    # end" is ten slides, not fifteen. `length` is the whole deck; the sections
    # are the slides the model writes.
    question_slides=0
    if fid==SLIDES:
        if original is None:question_slides=paging.question_slides(question_count)
        else:question_slides=int(original.get('options',{}).get('question_slides',0) or 0)
        if edit is not None and (edit.questions or edit.question_count):
            # Removed, the deck loses its question slides; added, it gains them.
            remaining=len(original['content'].get('questions',[])) if kept is None else kept
            question_slides=paging.question_slides(max(remaining,question_count) if edit.questions!='remove' else 0)
    if original is not None and (asked is None or selection):
        sections_count=length
        if edit is not None and not cv:
            # Pages added are within the plan too, and so is a test added to a
            # deck at its limit: the slides it would push out are cut. What was
            # asked is kept so the review can say it was cut, not hide it.
            top=paging.ceiling(account,fmt)
            wanted=sections_count
            sections_count=max(1,min(sections_count,top-question_slides))
            if wanted!=len(original['content']['sections']) or sections_count<wanted:asked=wanted+question_slides
    else:
        question_slides=min(question_slides,max(0,length-1))
        sections_count=length-question_slides
    length=sections_count+question_slides
    # A document is plain prose in black and white unless its description asks
    # for more: pictures, tables or lists (layouts), or a look or colours (design).
    wants={}
    if fid not in (SLIDES,CV):
        from . import doc_designs
        wants={'wants_layouts':doc_designs.asks_for_layouts(brief),'wants_design':doc_designs.asks_for_design(brief)}
        if original is not None:
            # A change request keeps what the document already had.
            wants={key:value or bool(before_options.get(key)) for key,value in wants.items()}
        if edit is not None:
            # What a change asks of a document's look is what edits.py read, not
            # every word for one: "rasmsiz qil" names pictures to have none, and
            # "dizaynni o'zgartirma" a design to keep. Pictures are a layout; the
            # design is chosen again only for a new look. A colour named is the
            # accent (below), on the design the document has: it chooses none.
            wants={'wants_layouts':bool(edit.pictures in ('add','every') or before_options.get('wants_layouts')
                                        or doc_designs.asks_for_layouts(editing.without_pictures(prompt))),
                   'wants_design':bool(edit.redesign)}
    image_cap=_image_cap(account,fid)
    # A deck whose description asks for pictures gets as many as it names, or
    # one a slide ("har bir slaydda rasm"), within what the plan adds; the review
    # says so when the plan adds fewer.
    images_wanted=0
    if fid==SLIDES and original is None:
        from .doc_designs import asks_for_images
        if asks_for_images(brief):images_wanted=paging.requested_images(brief) or sections_count
    if edit is not None:
        # A change asking for pictures gets the plan's allowance and asks for the
        # pictures the document will have: one on every content page for "har
        # bir slaydda rasm"; else those it has and the ones added, as many as
        # it names or about one content page in three. Counted as a total, so a
        # deck that already had its pictures is not told it is done, nor a part
        # with a small share of them to take its own away. A deck's cover is
        # not counted: it keeps its photo whatever the change asks. One that
        # does not ask keeps the allowance the document had.
        if edit.pictures in ('add','every'):
            images_wanted=_pictures_wanted(edit,original['content']['sections'],sections_count,fmt,image_cap)
        elif fid!=SLIDES or 'image_cap' in before_options:
            image_cap=min(image_cap,int(before_options.get('image_cap',0) or 0))
    elif fid not in (SLIDES,CV) and not doc_designs.asks_for_images(brief) and not (original is not None and before_options.get('image_cap')):
        image_cap=0
    # Photographs unless drawings are asked for ("kitoblardagi rasmlardek"):
    # Pixabay is searched for that kind (apps/studio/photos.py). A change keeps
    # the kind the document had unless it names another.
    from .edits import photo_style
    if edit is not None:kind=edit.photo_style or before_options.get('photo_style')
    elif original is not None:kind=before_options.get('photo_style')
    else:kind=photo_style(prompt)
    if cv:kind=None
    # Pictures wanted and their kind are the server's reading, never the client's.
    computed=('wants_layouts','wants_design','images_wanted','photo_style')
    options={**{k:v for k,v in options.items() if k not in computed},
             'question_count':question_count,'length':length,'requested_pages':asked,'question_slides':question_slides,
             'uz_script':uz_script,**({'images_wanted':images_wanted} if images_wanted else {}),
             'image_cap':image_cap,**wants,**({'photo_style':kind} if kind in ('photo','illustration') else {})}
    template_id=options.get('template_id','clean')
    from .templates import style_for
    # Density is fixed at the spacing the page-fill targets were measured
    # against; a page that must be full has nothing left to choose.
    density={}
    template_style=style_for(account,template_id)
    if template_style is None:
        from .models import SavedDefinition
        import re
        template=SavedDefinition.objects.filter(account=account,id=template_id,kind='template').first()
        if not template:raise DomainError('not_found',404)
        accent=template.definition.get('content',{}).get('style',{}).get('accent','#255e49')
        if not isinstance(accent,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',accent):raise DomainError('invalid_parameters')
        # A customer's own saved template carries a colour they chose.
        template_style={'accent':accent,'accent_fixed':True}
    style={**template_style,**density}
    if original is not None:
        # The look starts from the document's, unless this change picked another
        # template: that look is the change's own until another is picked.
        own=(revision_base or {}).get('options',{})
        picked_own=revision_base is not None and own.get('template_id','clean')!=before_options.get('template_id','clean')
        inherited=own if picked_own else before_options
        previous_style=inherited.get('template_style',{})
        if template_id==inherited.get('template_id','clean'):
            # The saved style is server-authored. Still resolve the template
            # above to recheck its ownership and current plan permission.
            style=deepcopy(previous_style or style)
        elif fid in (SLIDES,CV):
            for key in ('deck_theme','deck_design','cv_template'):
                if previous_style.get(key):style[key]=previous_style[key]
        if edit is not None and edit.redesign:
            # "Varoqlarni hammasini bir xil qil", "boshqa dizayn": the look is
            # chosen again. A colour the request names still applies below.
            for key in ('deck_design','deck_theme','doc_design','cv_template'):style.pop(key,None)
        # A CV takes no colour from words: "навыки", "сертификат", "Brown
        # University" and "Qoraqalpog‘iston" all read as colours, and its look
        # is its template's, or the account's brand colour.
        if not selection and not cv:
            # A colour named is the accent, for a document as for a deck, as it
            # is in a new one ("yashil rangda qil"); a deck also takes a theme.
            theme=paging.requested_theme(brief) if fid==SLIDES else None
            accent=paging.requested_accent(brief)
            if theme:style['deck_theme']=theme
            if accent:style.update(accent=accent,accent_fixed=True)
        # A selected-page revision never changes the whole document's style.
    elif not cv:
        style.update(_deck_style(fid,brief))
    if picked and picked!='auto':
        # A design picked on the review screen beats whatever look the
        # description implies: its colours and its dark or bold are dropped,
        # keeping only a saved template's own colour. Branding still wins below.
        style={**{key:value for key,value in style.items() if key not in ('deck_theme','secondary','accent','accent_fixed')},
               **{key:template_style[key] for key in ('accent','accent_fixed') if key in template_style},
               'deck_design':picked}
    picked_template=options.get('cv_template') if cv else None
    if picked_template and picked_template!='auto':
        # The same for a CV's template: its colours are the template's, and a
        # saved template's own colour and branding still win.
        style={**{key:value for key,value in style.items() if key not in ('secondary','accent','accent_fixed')},
               **{key:template_style[key] for key in ('accent','accent_fixed') if key in template_style},
               'cv_template':picked_template}
    options['template_style']=style
    from .branding import prepare_branding
    options=prepare_branding(account,fid,options)
    # A CV's portrait: the customer's own JPEG or PNG, pinned; any other service refuses one.
    from .cv.portrait import prepare as prepare_portrait
    options=prepare_portrait(account,fid,options,before_options if original is not None else None,portrait_removed)
    options.pop('adaptive_context',None)
    cfg=ai_config()
    if cfg['mode']=='disabled' or cfg['mode']=='openai' and (not cfg['api_key'] or not cfg['model']):raise DomainError('provider_not_configured',409)
    if not prompt.strip() and not text.strip() and not excerpts:raise DomainError('prompt_required')
    # Creation is uncharged authoring. Provider calls happen only after an accepted quote.
    if original is not None:
        # The model is handed the document as it stands so it can return it
        # with only the requested changes applied.
        sections=[dict(section) for section in original['content']['sections'][:sections_count]]
        # New pages take ids no page has: a document whose pages were removed
        # may already use s4 with only three pages left.
        taken={section['id'] for section in original['content']['sections']}
        number=len(sections)
        while len(sections)<sections_count:
            number+=1
            if f's{number}' not in taken:sections.append({'id':f's{number}','heading':'','body':'','notes':''})
        draft_content={**original['content'],'sections':sections}
        if kept is not None:
            # Removed, or cut to the number asked for: the model is not handed the
            # rest. A question slide removed by its number takes its own questions.
            gone=set(edit.removed_question_slides) if edit is not None else set()
            draft_content['questions']=[question for number,question in enumerate(original['content'].get('questions',[]))
                                        if number//paging.QUESTIONS_PER_SLIDE+1 not in gone][:kept]
    elif cv:
        # The eight sections the model fills. With no model, the description
        # itself is the profile, so the CV still says what was written.
        from .cv.content import seed
        draft_content=seed(title,(text or prompt) if cfg['mode']=='local_fixture' else '')
    else:
        chunks=[p.strip() for p in (text or '\n\n'.join(x['text'] for x in excerpts)).split('\n\n') if p.strip()]
        # No headings. They used to be seeded with a fixed Overview / Key ideas /
        # Practice / Review cycle, which handed every document a practice section
        # and a review section nobody asked for — and repeated the four of them
        # every four pages. The description is the brief, so the structure comes
        # from the description.
        sections=[{'id':f's{i+1}','heading':'', 'body':('\n\n'.join(chunks[i:]) if i==sections_count-1 else chunks[i]) if i<len(chunks) else '', 'notes':''} for i in range(sections_count)]
        draft_content={'title':title,'sections':sections,'questions':options.get('questions',[]),'citations':[{'asset_id':x['asset_id'],'page':x['page']} for x in excerpts]}
    content=validate_content(account,draft_content,fmt,feature=fid)
    if selection:
        ensure_selected_preservation({'content':draft_content,'revision':{'selected_section_ids':selection}},content)
    payload={'title':title,'prompt':prompt,'source_text':text,'source_ids':ids,'excerpts':excerpts,'output_locale':locale,'locale_source':resolved.source,'output_format':fmt,'options':options,'content':content}
    if original is not None:
        payload['revision']={'request':prompt,'source_draft_id':str(revising),
                             'original_prompt':original.get('revision',{}).get('original_prompt',original.get('prompt','')),
                             'root_draft_id':edit_root(original,revising)}
        if selection:
            payload['revision'].update(selected_section_ids=selection,base_version=source_version,
                                       base_content=deepcopy(original['content']),base_locale=locale)
        else:
            # What was read, for the model and the checks after it; and the
            # document as it was, since a page added at the start or removed from
            # the middle leaves the outline's slots out of step with it.
            from dataclasses import asdict
            payload['revision'].update(edit=asdict(edit),before=deepcopy(original['content']))
    else:
        from .revisions import source_seed
        seed=source_seed(payload)
        if seed:payload['_source_seed']=seed
    if len(payload['excerpts'])>plan_limits(account)['max_ai_source_pages']:raise DomainError('generation_limit')
    if payload['source_ids']:owned_assets(account,payload['source_ids'])
    if cfg['mode']=='openai':
        enforce_budget(cfg,payload,fid,plan_limits(account)['max_ai_input_tokens'])
    return fid,cfg,payload

def enforce_budget(config,payload,feature_id,token_limit):
    """The draft held to the plan's input budget, when it is made and when it is quoted.

    A change is held to the largest request its job sends (provider.largest_body):
    a long document is written in parts, and one body holding every page, which
    no job sends, refused a fifteen-page Russian change whose two calls both
    fit. A new document is held to its whole body, as it always was.
    """
    from . import provider
    body=(provider.largest_body(config,payload,feature_id) if payload.get('revision')
          else provider.request_body(config,payload,feature_id))
    if provider.body_tokens(body)>token_limit:raise DomainError('generation_limit')
    return body

def require_topic(data,fid,payload):
    """Refuse a new document whose description names no topic ("12 ta slayd kk").

    The model would make one up, spending a weekly document on a subject nobody
    asked for, or fail on a reply too thin to pass the checks. Nothing is
    counted yet: the customer is told what is missing and, when the description
    asks for the other format, which tool makes it. A description asking only
    for a file in another format ("pdf ga o‘tkaz") is the file tools' work, and
    says so instead (convert_requested). Only a new document from a description
    alone is read: a change request and a draft with source files or pasted
    text (the web sends the service name as the description beside a file)
    have something to work from, and update_draft never refuses a draft that
    was already accepted. A new draft is made from its description whatever
    content or outline the request carries, so neither excuses it.
    """
    if payload.get('revision') or payload['source_ids'] or payload['excerpts'] or payload['source_text'].strip():return
    from .topics import asked_other_service,asks_to_convert,names_no_topic
    # The web's title field can hold the topic; by default it is the description's first line.
    title,prompt=payload['title'],payload['prompt']
    words=prompt if title=='Untitled document' or title in prompt else f'{title}\n{prompt}'
    if not names_no_topic(words):return
    if asks_to_convert(words):raise DomainError('convert_requested',400,{'service':'','convert':True})
    raise DomainError('topic_required',400,{'service':asked_other_service(words,fid)})

def create_draft(account,data):
    # `options.topic_given` is the customer answering the refusal: the bot's
    # topic question answered a second time, or the web's "Continue anyway".
    # The check reads words, and a topic it does not know ("Bahor") must never
    # leave anyone stuck. It is a request, not a setting, so it is not kept.
    key='options' if 'options' in data else 'parameters'
    options=data.get(key)
    given=isinstance(options,dict) and options.get('topic_given') is True
    if isinstance(options,dict) and 'topic_given' in options:
        data={**data,key:{k:v for k,v in options.items() if k!='topic_given'}}
    fid,cfg,payload=_prepare_draft(account,data)
    # After _prepare_draft, so a malformed request keeps its own error. A CV
    # needs a name where a document needs a topic, and takes the name it
    # finds as its title even when the customer insisted.
    if fid==CV:
        from .cv.content import require_name
        require_name(data,fid,payload,refuse=not given)
    elif not given:require_topic(data,fid,payload)
    return GenerationDraft.objects.create(account=account,feature_id=fid,encrypted_data=pack(payload),provider_mode=cfg['mode'],expires_at=timezone.now()+timedelta(hours=24))

def draft_jobs(account,draft_id,statuses):
    """Whether a job in one of `statuses` was submitted for a quote of this draft."""
    from apps.core.models import Job
    return Job.objects.filter(account=account,status__in=statuses,
                              quote__parameters__generation_draft_id=str(draft_id)).exists()

@transaction.atomic
def update_draft(account,draft_id,data):
    d=GenerationDraft.objects.select_for_update().filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    # A queued job checks, when it starts, that its draft is still the one it
    # was quoted on (validate_generation_quote). Changing the draft before then
    # — the review's count or language buttons, the deck setup screen, the web
    # editor — would fail it. A running job has passed that check and works
    # from its own snapshot, so edits while it runs stay allowed
    # (tests/test_studio_adversarial.py).
    if draft_jobs(account,d.id,('queued',)):raise DomainError('generation_running',409)
    if data.get('version')!=d.version:raise DomainError('version_conflict',409)
    original=unpack(d.encrypted_data)
    allowed_keys={'version','title','prompt','source_text','source_ids','output_locale','output_format','options','content','outline'}
    if set(data)-allowed_keys:raise DomainError('invalid_parameters')
    fields={key:original[key] for key in ('title','prompt','source_text','source_ids','output_locale','output_format','options')}
    fields.update({key:value for key,value in data.items() if key in fields})
    _,cfg,payload=_prepare_draft(account,{'feature_id':d.feature_id,**fields},revision_base=original)
    if cfg['mode']!=d.provider_mode:raise DomainError('provider_changed',409)
    # The page count lives in the description, so a reworded brief rebuilds the
    # outline the same way a changed source does.
    rebuild=any(key in data and data[key]!=original.get(key) for key in ('prompt','source_text','source_ids','output_format'))
    if rebuild and d.feature_id==CV:
        # A reworded CV description may name the person differently: the title
        # follows it. An accepted draft is never refused here.
        from .cv.content import require_name
        require_name(data,CV,payload,refuse=False)
    # So does a count chosen on the review screen.
    rebuild=rebuild or payload['options'].get('length')!=original.get('options',{}).get('length')
    content=data.get('content',payload['content'] if rebuild and not original.get('revision',{}).get('selected_section_ids') else original['content'])
    if 'outline' in data:
        outline=data['outline']
        if not isinstance(outline,list) or any(not isinstance(s,dict) for s in outline):raise DomainError('invalid_parameters')
        slide_keys=('layout','items','columns','image_query')
        content={**content,'sections':[{'id':s.get('id',str(i)),'heading':s.get('title',''),'body':s.get('body',''),'notes':s.get('notes',''),
                                         **{key:s[key] for key in slide_keys if key in s}} for i,s in enumerate(outline)]}
    if 'title' in data and isinstance(content,dict):content={**content,'title':payload['title']}
    payload['content']=validate_content(account,content,payload['output_format'],feature=d.feature_id)
    payload['title']=payload['content']['title']
    # Only server-authored, untouched source copies can be deduplicated. Sending
    # content/outline is an explicit author edit, even if its text happens to match.
    if 'content' in data or 'outline' in data:
        payload.pop('_source_seed',None)
    elif not rebuild:
        payload.pop('_source_seed',None)
        if original.get('_source_seed'):payload['_source_seed']=original['_source_seed']
    if payload.get('revision',{}).get('selected_section_ids'):
        # Selected revisions may edit content, but structural changes need the
        # whole-document flow so selected identities cannot silently disappear.
        base=payload['revision']['base_content']
        if [s['id'] for s in payload['content']['sections']]!=[s['id'] for s in base['sections']]:
            raise DomainError('invalid_parameters')
    # An edited outline is the page count now, so keep them in step.
    payload['options']={**payload['options'],'length':len(payload['content']['sections'])+int(payload['options'].get('question_slides',0) or 0)}
    if cfg['mode']=='openai':
        enforce_budget(cfg,payload,d.feature_id,plan_limits(account)['max_ai_input_tokens'])
    d.encrypted_data=pack(payload);d.version+=1;d.save(update_fields=['encrypted_data','version'])
    return d

def generation_quote(account,draft_id,version):
    d=GenerationDraft.objects.filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    require(account,d.feature_id)
    from apps.core.channel_gate import require as require_channels
    require_channels(account)
    if version!=d.version:raise DomainError('version_conflict',409)
    data=unpack(d.encrypted_data)
    # Said before the customer confirms, not after: an edit draws on the file's
    # own edits, anything else on the week's documents (apps/core/allowance.py).
    # Submission checks again under the account lock.
    from apps.core.allowance import require_ai_document,require_edit,require_made
    root=edit_root(data,d.id)
    if data.get('revision'):
        require_made(account,root)
        require_edit(account,root)
    else:require_ai_document(account)
    cfg=ai_config()
    if cfg['mode']!=d.provider_mode:raise DomainError('provider_changed',409)
    caps=limits(account)
    question_cap=max(len(data['content']['questions']),int(data['options'].get('question_count',0)))
    if not 0<=question_cap<=caps['questions']:raise DomainError('generation_limit')
    # Pages are an explicit, user-chosen number rather than a soft hint, so the
    # job is bounded by what was asked for instead of the plan's ceiling. One
    # page of headroom is allowed because a section written to fill its page
    # can spill onto the next.
    output_cap=len(data['content']['sections'])+int(data['options'].get('question_slides',0) or 0)+1
    if cfg['mode']=='openai':
        enforce_budget(cfg,data,d.feature_id,plan_limits(account)['max_ai_input_tokens'])
    snapshot=hashlib.sha256(bytes(d.encrypted_data)).hexdigest()
    from .branding import generation_inputs
    input_ids=generation_inputs(data)
    # A long document is written in several provider calls and needs longer than
    # the default lease to finish them. Rendering and settlement are on top.
    from .provider import call_budget
    lease_seconds=call_budget(len(data['content']['sections']))+240
    if data['output_format']=='pptx':
        from .photos import BUDGET_SECONDS
        lease_seconds+=BUDGET_SECONDS
    return Quote.objects.create(account=account,feature_id=d.feature_id,input_ids=input_ids,input_fingerprints=[{'id':str(a.id),'sha256':a.sha256} for a in owned_assets(account,input_ids)] if input_ids else [],parameters={'generation_draft_id':str(d.id),'draft_version':d.version,'snapshot':snapshot,**({'revision':True,'root_draft_id':root} if data.get('revision') else {})},policy={'plan':account.plan,'version':POLICY_VERSION,'tariff_version':'generation-draft-staging-v1','limits':plan_limits(account),'provider_mode':d.provider_mode,'provider_model':cfg['model'],'provider_image_model':cfg.get('image_model',''),'generation_bounds':{'question_cap':question_cap,'output_pages':output_cap,'key_pages':caps['sections'],'input_tokens':plan_limits(account)['max_ai_input_tokens']},'lease_seconds':lease_seconds},expires_at=timezone.now()+timedelta(minutes=10))

def validate_generation_quote(account,quote):
    require(account,quote.feature_id)
    d=GenerationDraft.objects.filter(id=quote.parameters.get('generation_draft_id'),account=account,expires_at__gt=timezone.now()).first()
    if not d or d.version!=quote.parameters.get('draft_version') or hashlib.sha256(bytes(d.encrypted_data)).hexdigest()!=quote.parameters.get('snapshot'):raise DomainError('version_conflict',409)
    config=ai_config()
    if config['mode']!=d.provider_mode or quote.policy.get('provider_model','')!=config['model']:raise DomainError('provider_changed',409)
    return owned_assets(account,quote.input_ids) if quote.input_ids else []
