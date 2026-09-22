"""Synchronous, transaction-safe bot draft operations; no Telegram network calls."""
from django.db import transaction
from django.utils import timezone
from processors import normalize_parameters,ProcessorError
from apps.core.models import Account,BotDraft,BotInputReceipt,FileAsset,Job
from apps.core.errors import DomainError
from apps.core.policy import require_feature
from apps.core.services import create_quote,submit_job


def draft_for(account):
    return BotDraft.objects.get_or_create(account=account)[0]


def bound_draft(account,payload):
    try: draft=BotDraft.objects.select_for_update().get(account=account,pk=payload['draft_id'],version=payload['version'])
    except (BotDraft.DoesNotExist,KeyError,ValueError): raise DomainError('controls_expired',409)
    return draft


def snapshot(draft):
    return {'draft_id':draft.id,'version':draft.version}


def validate_parameters(draft,parameters):
    if not isinstance(parameters,dict) or any('password' in key.lower() or 'secret' in key.lower() for key in parameters): raise DomainError('secure_password_entry_required')
    # Required settings may still be missing in an in-progress draft.
    from processors.engine import PARAMETER_SCHEMAS
    complete=dict(parameters)
    metadata=list(FileAsset.objects.filter(account=draft.account,id__in=draft.input_ids).values_list('metadata',flat=True))
    schema=PARAMETER_SCHEMAS.get(draft.feature_id,{})
    if any(key not in schema.get('properties',{}) for key in parameters): raise DomainError('invalid_parameters')
    if any(key not in complete for key in schema.get('required',[])): return complete
    try: return normalize_parameters(draft.feature_id,complete,metadata)
    except ProcessorError as exc: raise DomainError(exc.code) from None


@transaction.atomic
def configure(account,*,feature_id=None,parameters=None,replace=False,binding=None):
    Account.objects.select_for_update().get(pk=account.pk)
    draft=bound_draft(account,binding) if binding else draft_for(account)
    if feature_id:
        require_feature(account,feature_id)
        if feature_id in ('pdf.protect','pdf.unlock_known'): raise DomainError('secure_password_entry_required')
        if draft.feature_id!=feature_id: draft.parameters={}
        draft.feature_id=feature_id
    draft.parameters=validate_parameters(draft,parameters if replace else {**draft.parameters,**(parameters or {})})
    draft.quote=None;draft.version+=1
    draft.save(update_fields=['feature_id','parameters','quote','version','updated_at'])
    return draft


@transaction.atomic
def attach_input(account,asset,chat_id,message_id,mode='add',binding=None):
    Account.objects.select_for_update().get(pk=account.pk)
    existing=BotInputReceipt.objects.filter(account=account,chat_id=chat_id,message_id=message_id).first()
    if existing: return draft_for(account),False
    if asset.account_id!=account.id or asset.state!='ready' or asset.expires_at<=timezone.now(): raise DomainError('file_unavailable',404)
    draft=bound_draft(account,binding) if binding else draft_for(account)
    if mode=='new': draft.input_ids=[];draft.parameters={}
    if len(draft.input_ids)>=50: raise DomainError('input_count_exceeded')
    draft.input_ids=[*draft.input_ids,str(asset.id)];draft.quote=None;draft.version+=1
    draft.save(update_fields=['input_ids','parameters','quote','version','updated_at'])
    BotInputReceipt.objects.create(account=account,asset=asset,chat_id=chat_id,message_id=message_id)
    return draft,True


@transaction.atomic
def order_inputs(account,positions,remove=None):
    Account.objects.select_for_update().get(pk=account.pk)
    draft=draft_for(account)
    if remove is not None:
        if not 0<=remove<len(draft.input_ids): raise DomainError('invalid_parameters')
        draft.input_ids=[v for i,v in enumerate(draft.input_ids) if i!=remove]
    else:
        if sorted(positions)!=list(range(len(draft.input_ids))): raise DomainError('invalid_parameters')
        draft.input_ids=[draft.input_ids[i] for i in positions]
    draft.quote=None;draft.version+=1
    draft.save(update_fields=['input_ids','quote','version','updated_at'])
    return draft


@transaction.atomic
def quote_draft(account,binding=None):
    Account.objects.select_for_update().get(pk=account.pk)
    draft=bound_draft(account,binding) if binding else draft_for(account)
    # A repeated Done action reuses the immutable quote while settings match.
    if draft.quote_id and draft.quote.expires_at>timezone.now(): return draft,draft.quote
    quote=create_quote(account,draft.feature_id,draft.input_ids,draft.parameters)
    draft.quote=quote
    draft.save(update_fields=['quote','updated_at'])
    return draft,quote


def run_quote(account,quote_id):
    # Quote-bound key is common to command, callback and transport retries.
    return submit_job(account,quote_id,f'bot:quote:{quote_id}','bot')
