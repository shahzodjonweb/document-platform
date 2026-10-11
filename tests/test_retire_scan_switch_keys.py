"""The deploy that retired images to PDF's crop and enhance switches (core 0018).

It removes the two keys from everything that can still run — bot drafts, bot
buttons, unconfirmed quotes, unfinished jobs — and leaves the record of what
already ran alone.
"""
import importlib
import secrets
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.core.models import BotCallback, BotDraft, Job, Quote
from tests.test_platform import account

pytestmark = pytest.mark.django_db

IMAGES = 'pdf.images_to_pdf'
LAYOUT = {'paper_size': 'fit', 'orientation': 'auto', 'margin': 0}
OLD = {**LAYOUT, 'auto_crop': True, 'enhance_text': True}


def deploy():
    importlib.import_module('apps.core.migrations.0018_retire_scan_switch_keys').retire_scan_switches(django_apps, None)


def quote(owner, parameters, feature=IMAGES):
    return Quote.objects.create(account=owner, feature_id=feature, parameters=parameters,
                                expires_at=timezone.now() + timedelta(minutes=10))


def job(owner, parameters, status):
    return Job.objects.create(account=owner, quote=quote(owner, parameters), feature_id=IMAGES, parameters=parameters,
                              idempotency_key=secrets.token_hex(8), request_hash='x', status=status)


def button(owner, payload, action='settings'):
    return BotCallback.objects.create(token=secrets.token_urlsafe(12), account=owner, action=action, payload=payload,
                                      expires_at=timezone.now() + timedelta(days=30))


def snapshot():
    return {model.__name__: sorted((str(row.pk), repr(getattr(row, field))) for row in model.objects.all())
            for model, field in ((BotDraft, 'parameters'), (BotCallback, 'payload'), (Quote, 'parameters'), (Job, 'parameters'))}


def test_the_deploy_cleans_what_can_still_run_and_keeps_the_record():
    owner, other = account(7001), account(7002)
    draft = BotDraft.objects.create(account=owner, feature_id=IMAGES, state='collecting', parameters={**OLD, 'paper_size': 'A4'}, version=9)
    plain_draft = BotDraft.objects.create(account=other, feature_id=IMAGES, state='collecting', parameters=LAYOUT)
    binding = {'draft_id': draft.id, 'version': draft.version}
    crop = button(owner, {**binding, 'parameters': {'auto_crop': False}, 'advanced': False})
    enhance = button(owner, {**binding, 'parameters': {'enhance_text': True}, 'advanced': True})
    mixed = button(owner, {**binding, 'parameters': {'paper_size': 'A4', 'auto_crop': True}, 'replace': False, 'advanced': False})
    paper = button(owner, {**binding, 'parameters': {'paper_size': 'Letter'}, 'replace': False, 'advanced': True})
    each_page = button(owner, {**binding, 'parameters': {}, 'replace': True, 'advanced': True})
    prompt = button(owner, {**binding, 'kind': 'margin'}, action='prompt')
    unconfirmed = quote(owner, OLD)
    other_feature = quote(owner, {'auto_crop': True}, feature='pdf.compress')
    queued, running, finalizing = (job(owner, OLD, status) for status in ('queued', 'running', 'finalizing'))
    finished = {status: job(owner, OLD, status) for status in ('succeeded', 'failed', 'canceled')}

    deploy()

    draft.refresh_from_db()
    assert draft.parameters == {**LAYOUT, 'paper_size': 'A4'}
    assert draft.version == 9, 'the screen on show keeps working'
    assert BotDraft.objects.get(pk=plain_draft.pk).parameters == LAYOUT
    assert BotCallback.objects.get(pk=crop.pk).payload == {**binding, 'parameters': {}, 'advanced': False, 'retired': 'scan_switches'}
    assert BotCallback.objects.get(pk=enhance.pk).payload == {**binding, 'parameters': {}, 'advanced': True, 'retired': 'scan_switches'}
    assert BotCallback.objects.get(pk=mixed.pk).payload == {**binding, 'parameters': {'paper_size': 'A4'}, 'replace': False, 'advanced': False}
    for untouched in (paper, each_page, prompt):
        assert BotCallback.objects.get(pk=untouched.pk).payload == untouched.payload
    assert Quote.objects.get(pk=unconfirmed.pk).parameters == LAYOUT
    assert Quote.objects.get(pk=other_feature.pk).parameters == {'auto_crop': True}, 'only images to PDF had the switches'
    for unfinished in (queued, running, finalizing):
        assert Job.objects.get(pk=unfinished.pk).parameters == LAYOUT
        assert Quote.objects.get(pk=unfinished.quote_id).parameters == OLD, 'a confirmed quote is history'
    for done in finished.values():
        assert Job.objects.get(pk=done.pk).parameters == OLD
        assert Quote.objects.get(pk=done.quote_id).parameters == OLD

    cleaned = snapshot()
    deploy()
    assert snapshot() == cleaned, 'a second run changes nothing'


def test_the_deploy_works_through_more_rows_than_one_batch(monkeypatch):
    migration = importlib.import_module('apps.core.migrations.0018_retire_scan_switch_keys')
    monkeypatch.setattr(migration, 'BATCH', 2)
    owner = account(7003)
    quotes = [quote(owner, OLD) for _ in range(5)]
    deploy()
    assert [row.parameters for row in Quote.objects.filter(pk__in=[q.pk for q in quotes])] == [LAYOUT] * 5
