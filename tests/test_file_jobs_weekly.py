"""File tools share one weekly counter: 15 tasks a week on Free, no limit on Plus or Premium.

Image→PDF, merge, compress, OCR, PDF→Word, the PDF editor and every other tool
draw on the same 15. A batch is checked as a whole when it is confirmed, and
its files that have not started yet keep their places.
"""
import io
from datetime import datetime, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.allowance import ai_documents_this_week, file_jobs_this_week, usage_snapshot, week_bounds
from apps.core.errors import DomainError
from apps.core.models import Account, Job
from apps.core.services import create_quote, submit_job, upload_file
from operations import plans as plan_settings
from tests.test_platform import account, login_client, upload

pytestmark = pytest.mark.django_db


def on_plan(customer, plan):
    Account.objects.filter(pk=customer.pk).update(staff_plan=plan)
    customer.refresh_from_db()
    return customer


def photo(customer):
    stream = io.BytesIO()
    Image.new('RGB', (240, 320), (242, 242, 237)).save(stream, format='PNG')
    return upload_file(customer, SimpleUploadedFile('document-photo.png', stream.getvalue(), 'image/png'))


def ran(customer, quote):
    """A task submitted and finished (free accounts run one at a time)."""
    job, _ = submit_job(customer, quote.id, f'file-{quote.id}')
    Job.objects.filter(pk=job.pk).update(status='succeeded')
    return job


def rotated(customer, n):
    asset = upload(customer)
    return [ran(customer, create_quote(customer, 'pdf.rotate', [str(asset.id)], {'angle': 90})) for _ in range(n)]


def test_every_file_tool_draws_on_the_same_week():
    customer = account()
    pdf, other = upload(customer), upload(customer, name='second.pdf')
    note = {'commands': [{'type': 'add_text', 'page': 1, 'x': 40, 'y': 100, 'text': 'Salom', 'font_size': 18}]}
    tasks = [('pdf.images_to_pdf', [photo(customer)], {}),
             ('pdf.merge', [pdf, other], {}),
             ('pdf.compress', [pdf], {}),
             ('ocr.extract_text', [pdf], {}),
             ('convert.pdf_to_docx', [pdf], {}),
             ('editor.visual', [pdf], note)]
    for count, (feature, assets, parameters) in enumerate(tasks, 1):
        ran(customer, create_quote(customer, feature, [str(a.id) for a in assets], parameters))
        assert file_jobs_this_week(customer) == count, feature
    assert ai_documents_this_week(customer) == 0


def test_fifteen_tasks_a_week_on_free_then_the_next_is_refused():
    customer = account()
    rotated(customer, 15)
    asset = photo(customer)
    late = create_quote(customer, 'pdf.images_to_pdf', [str(asset.id)], {})
    with pytest.raises(DomainError) as refused:
        submit_job(customer, late.id, 'the-sixteenth-task')
    assert refused.value.code == 'weekly_file_limit' and refused.value.status == 429
    assert refused.value.params == {'limit': 15, 'used': 15, 'requested': 1, 'resets_at': week_bounds()[1].isoformat()}


def test_a_quote_taken_earlier_cannot_slip_past_the_limit():
    """The count that decides is the one taken under the account lock at submission."""
    customer = account()
    asset = upload(customer)
    early = [create_quote(customer, 'pdf.rotate', [str(asset.id)], {'angle': 90}) for _ in range(16)]
    for quote in early[:15]:
        ran(customer, quote)
    with pytest.raises(DomainError, match='weekly_file_limit'):
        submit_job(customer, early[15].id, 'early-file-quote')
    assert Job.objects.filter(account=customer).count() == 15


def test_a_failed_task_gives_its_place_back_and_last_week_is_forgotten():
    customer = account()
    jobs = rotated(customer, 15)
    Job.objects.filter(pk=jobs[0].pk).update(status='failed')
    assert file_jobs_this_week(customer) == 14
    rotated(customer, 1)
    Job.objects.filter(account=customer).update(created_at=week_bounds()[0] - timedelta(seconds=1))
    assert file_jobs_this_week(customer) == 0


@pytest.mark.parametrize('plan', ['plus', 'premium'])
def test_paid_plans_have_no_file_limit(plan):
    customer = on_plan(account(), plan)
    rotated(customer, 16)
    assert usage_snapshot(customer)['file_jobs'] == {'limit': None, 'used': 16, 'remaining': None}


def test_the_api_offers_the_quote_but_refuses_the_task_and_says_why():
    customer = account()
    rotated(customer, 15)
    client = login_client(customer)
    asset = upload(customer)
    quote = client.post('/api/v1/quotes', {'feature_id': 'pdf.rotate', 'input_ids': [str(asset.id)], 'parameters': {'angle': 90}},
                        content_type='application/json')
    assert quote.status_code == 201, quote.content
    body = quote.json()
    assert body['affordable'] is False
    assert body['usage']['file_jobs'] == {'limit': 15, 'used': 15, 'remaining': 0}
    assert not {'meters', 'available_balances'} & set(body)
    refused = client.post('/api/v1/jobs', {'quote_id': body['id']}, content_type='application/json', HTTP_IDEMPOTENCY_KEY='refused-file-task')
    assert refused.status_code == 429
    error = refused.json()['error']
    assert error['code'] == 'weekly_file_limit' and error['message_params']['used'] == 15


def test_the_usage_endpoint_shows_the_week():
    customer = account()
    rotated(customer, 2)
    usage = login_client(customer).get('/api/v1/usage').json()
    assert set(usage) == {'plan', 'week', 'ai_documents', 'file_jobs', 'edits_per_file', 'resets_at'}
    assert usage['plan'] == 'free' and usage['edits_per_file'] == 3
    assert usage['ai_documents'] == {'limit': 5, 'used': 0, 'remaining': 5}
    assert usage['file_jobs'] == {'limit': 15, 'used': 2, 'remaining': 13}
    assert usage['week']['time_zone'] == 'Asia/Tashkent'
    starts, resets = (datetime.fromisoformat(usage['week'][key]) for key in ('starts_at', 'resets_at'))
    assert (starts, resets) == week_bounds() and usage['resets_at'] == usage['week']['resets_at']
    assert resets.isoformat().endswith('T00:00:00+05:00'), 'a Monday midnight in Tashkent'
    plus = login_client(on_plan(account(43), 'plus')).get('/api/v1/usage').json()
    assert plus['file_jobs']['limit'] is None and plus['ai_documents']['limit'] == 20 and plus['edits_per_file'] == 10


# ---------------------------------------------------------------- batches


@pytest.fixture
def plus_with_three(settings):
    """Plus has no file limit unless the owner sets one; batches are a paid tool.
    No paid plan may give less than Free, so Free is lowered to match first."""
    settings.DEBUG = True
    plan_settings.save('free', {'weekly_file_jobs': 3})
    plan_settings.save('plus', {'weekly_file_jobs': 3})
    return on_plan(account(), 'plus')


def pages(customer, count):
    return [{'feature_id': 'pdf.to_images', 'input_ids': [str(upload(customer).id)], 'parameters': {'dpi': 72}}
            for _ in range(count)]


def test_a_batch_that_does_not_fit_is_refused_whole(plus_with_three):
    from apps.studio.batches import create_batch_quote, quote_data, submit_batch
    from apps.studio.models import BatchRun
    customer = plus_with_three
    rotated(customer, 1)
    batch = create_batch_quote(customer, 'batch.convert', pages(customer, 3))
    assert quote_data(batch)['affordable'] is False
    with pytest.raises(DomainError) as refused:
        submit_batch(customer, batch.id, 'batch-too-big')
    assert refused.value.code == 'weekly_file_limit'
    assert refused.value.params['requested'] == 3 and refused.value.params['used'] == 1
    assert not BatchRun.objects.exists() and file_jobs_this_week(customer) == 1


def test_a_confirmed_batch_holds_places_for_the_files_not_started_yet(plus_with_three):
    from apps.studio.batches import create_batch_quote, quote_data, submit_batch
    customer = plus_with_three
    batch = create_batch_quote(customer, 'batch.convert', pages(customer, 2))
    assert quote_data(batch)['affordable'] is True
    run, created = submit_batch(customer, batch.id, 'batch-that-fits')
    assert created and not Job.objects.exists()
    assert file_jobs_this_week(customer) == 2, 'both files hold a place before either starts'
    rotated(customer, 1)
    asset = upload(customer)
    with pytest.raises(DomainError, match='weekly_file_limit'):
        submit_job(customer, create_quote(customer, 'pdf.rotate', [str(asset.id)], {}).id, 'after-the-batch')


def test_a_batch_that_exactly_fills_the_week_runs_every_file(plus_with_three):
    from apps.studio.batches import create_batch_quote, execute_batch, submit_batch
    customer = plus_with_three
    rotated(customer, 1)
    run, _ = submit_batch(customer, create_batch_quote(customer, 'batch.convert', pages(customer, 2)).id, 'batch-fills-the-week')
    run = execute_batch(run.id)
    assert list(run.children.values_list('error_code', flat=True)) == ['', '']
    assert run.status == 'succeeded' and file_jobs_this_week(customer) == 3


def test_a_workflow_needs_room_for_every_step_before_it_starts(plus_with_three):
    from apps.studio import workflows
    from apps.studio.models import SavedDefinition
    customer = plus_with_three
    rotated(customer, 2)
    asset = upload(customer)
    row = SavedDefinition.objects.create(account=customer, kind='workflow', name='Rotate then keep page 1', definition={
        'steps': [{'feature_id': 'pdf.rotate', 'parameters': {'angle': 90}},
                  {'feature_id': 'pdf.extract_pages', 'parameters': {'pages': '1'}}]})

    def confirmed():
        quoted = workflows.quote(customer, row.id, [str(asset.id)])
        return {'version': quoted['version'], 'input_ids': quoted['input_ids'], 'confirmed': True,
                'confirmation_token': quoted['confirmation_token']}

    with pytest.raises(DomainError) as refused:
        workflows.start(customer, row.id, confirmed(), 'two-steps-one-place')
    assert refused.value.code == 'weekly_file_limit' and refused.value.params['requested'] == 2
    plan_settings.save('plus', {'weekly_file_jobs': 4})
    run, token = workflows.start(customer, row.id, confirmed(), 'two-steps-two-places')
    assert workflows.execute(run, token).status == 'succeeded'
    assert file_jobs_this_week(customer) == 4


def test_a_batch_confirmed_last_week_still_holds_its_places_this_week(plus_with_three):
    """Confirmed a minute before Monday 00:00 and run after it: its waiting files
    hold their places in the week they are still waiting, so single tasks cannot
    take them first and the batch then run past the limit."""
    from apps.studio.batch_models import BatchRun
    from apps.studio.batches import create_batch_quote, execute_batch, submit_batch
    customer = plus_with_three
    run, _ = submit_batch(customer, create_batch_quote(customer, 'batch.convert', pages(customer, 3)).id, 'late-sunday-batch')
    BatchRun.objects.filter(pk=run.pk).update(created_at=week_bounds()[0] - timedelta(minutes=1))
    assert file_jobs_this_week(customer) == 3
    asset = upload(customer)
    with pytest.raises(DomainError, match='weekly_file_limit'):
        submit_job(customer, create_quote(customer, 'pdf.rotate', [str(asset.id)], {}).id, 'single-after-midnight')
    run = execute_batch(run.id)
    assert run.status == 'succeeded' and file_jobs_this_week(customer) == 3


def test_a_batch_file_that_failed_before_it_started_gives_its_place_back(plus_with_three):
    """A file whose quote expired or whose file changed made nothing; while the
    rest of the run waits in the queue only the files not yet tried hold places."""
    from apps.studio.batch_models import BatchItem
    from apps.studio.batches import create_batch_quote, submit_batch
    customer = plus_with_three
    run, _ = submit_batch(customer, create_batch_quote(customer, 'batch.convert', pages(customer, 2)).id, 'two-file-batch')
    first = BatchItem.objects.get(run=run, index=0)
    BatchItem.objects.filter(pk=first.pk).update(status='failed', error_code='quote_expired')
    assert run.status == 'queued' and file_jobs_this_week(customer) == 1
    # Its quote no longer holds a place either: submitted on its own, it is checked like any task.
    from apps.core.allowance import _holds_place
    assert not _holds_place(first.quote) and _holds_place(BatchItem.objects.get(run=run, index=1).quote)
