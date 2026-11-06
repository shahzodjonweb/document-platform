"""0012 on rows as production has them: one draft per open, marks only in the clear; and 0010 under the image still serving."""
from datetime import timedelta
import logging
import uuid
import pytest
from django.db import IntegrityError,connection,transaction
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from apps.studio.domain import unpack
from apps.studio.editor_policy import stored_commands
from apps.studio.models import EditorDocument
from tests.test_platform import account,upload

BEFORE=[('studio','0010_editor_groundwork')]
ONE_PER_OPEN=[('studio','0011_editor_lane_seconds')]
AFTER=[('studio','0012_editor_one_draft_per_file')]
SECRET='Секретный текст клиента'


def migrate(target):
    executor=MigrationExecutor(connection)
    executor.migrate(target)
    return MigrationExecutor(connection).loader.project_state(target).apps


@pytest.fixture
def at_0010(transactional_db):
    apps=migrate(BEFORE)
    yield apps
    # Whatever the test did, the next one finds the schema as the models say.
    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())


@pytest.fixture
def at_0011(transactional_db):
    apps=migrate(ONE_PER_OPEN)
    yield apps
    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())


def test_0012_keeps_the_newest_draft_of_each_file_and_encrypts_its_marks(at_0011,caplog):
    Old=at_0011.get_model('studio','EditorDocument')
    a=account();b=account(43);now=timezone.now()
    first,second=upload(a),upload(a,name='second.pdf');other=upload(b)
    note=lambda text:[{'type':'note','page':1,'x':1,'y':1,'text':text}]
    made=lambda owner,file,age,marks:Old.objects.create(account_id=owner.pk,file_id=file.pk,input_ids=[str(file.id)],commands=marks,created_at=now-timedelta(minutes=age))
    made(a,first,30,note(SECRET));made(a,first,20,note(SECRET));newest=made(a,first,10,note('Новейшая'))
    only=made(a,second,5,note('Единственная'));empty=made(b,other,1,[])
    with caplog.at_level(logging.INFO):migrate(AFTER)
    kept={row.pk:row for row in EditorDocument.objects.all()}
    assert set(kept)=={newest.pk,only.pk,empty.pk}
    assert unpack(kept[newest.pk].encrypted_commands)=={'version':1,'commands':note('Новейшая')} and stored_commands(kept[newest.pk])==note('Новейшая')
    assert unpack(kept[only.pk].encrypted_commands)=={'version':1,'commands':note('Единственная')}
    assert unpack(kept[empty.pk].encrypted_commands)=={'version':1,'commands':[]} and stored_commands(kept[empty.pk])==[]
    log=[record.getMessage() for record in caplog.records if 'editor drafts' in record.getMessage()]
    assert log==['editor drafts: kept 3, removed 2 (2 of them with marks), encrypted 3']
    assert SECRET not in caplog.text and 'Новейшая' not in caplog.text and str(first.pk) not in caplog.text and str(a.pk) not in caplog.text
    with pytest.raises(IntegrityError),transaction.atomic():
        EditorDocument.objects.create(account=a,file=first,input_ids=[str(first.id)])


def test_0012_keeps_a_files_older_draft_with_marks_over_a_newer_empty_one(at_0011):
    Old=at_0011.get_model('studio','EditorDocument')
    a=account();file=upload(a);now=timezone.now()
    marks=[{'type':'note','page':1,'x':1,'y':1,'text':SECRET}]
    marked=Old.objects.create(account_id=a.pk,file_id=file.pk,input_ids=[str(file.id)],commands=marks,created_at=now-timedelta(minutes=30))
    Old.objects.create(account_id=a.pk,file_id=file.pk,input_ids=[str(file.id)],commands=[],created_at=now-timedelta(minutes=5))
    migrate(AFTER)
    assert list(EditorDocument.objects.values_list('pk',flat=True))==[marked.pk] and stored_commands(EditorDocument.objects.get())==marks


def test_0012_packs_the_version_a_draft_is_at(at_0011):
    Old=at_0011.get_model('studio','EditorDocument')
    a=account();file=upload(a);marks=[{'type':'note','page':1,'x':1,'y':1,'text':'Yozuv'}]
    Old.objects.create(account_id=a.pk,file_id=file.pk,input_ids=[str(file.id)],commands=marks,version=5)
    migrate(AFTER)
    row=EditorDocument.objects.get()
    assert unpack(row.encrypted_commands)=={'version':5,'commands':marks} and stored_commands(row)==marks
    # The image before this one, still serving, empties the draft: that is what the customer did last.
    EditorDocument.objects.filter(pk=row.pk).update(commands=[],version=6)
    assert stored_commands(EditorDocument.objects.get())==[]


@pytest.mark.skipif(connection.vendor!='postgresql',reason='SQLite takes no table locks')
def test_0012_locks_out_every_writer_before_it_reads_a_row(at_0011):
    with CaptureQueriesContext(connection) as queries:migrate(AFTER)
    table=EditorDocument._meta.db_table
    touching=[query['sql'] for query in queries.captured_queries if table in query['sql'] and 'django_migrations' not in query['sql']]
    assert touching[0]==f'LOCK TABLE "{table}" IN ACCESS EXCLUSIVE MODE'


def test_0012_goes_back_without_touching_the_rows(at_0011):
    a=account();file=upload(a)
    migrate(AFTER)
    row=EditorDocument.objects.create(account=a,file=file,input_ids=[str(file.id)])
    Old=migrate(ONE_PER_OPEN).get_model('studio','EditorDocument')
    assert Old.objects.filter(pk=row.pk).exists()
    Old.objects.create(account_id=a.pk,file_id=file.pk,input_ids=[str(file.id)])
    assert Old.objects.count()==2


def test_the_image_before_this_one_can_still_write_after_0010(at_0010):
    """Deploy migrates before it swaps the API: the old code's insert names none of the new columns."""
    a=account();file=upload(a)
    key=lambda value:value.hex if connection.vendor=='sqlite' else str(value)
    with connection.cursor() as cursor:
        cursor.execute(f"INSERT INTO {EditorDocument._meta.db_table} (id,account_id,file_id,version,commands,input_ids,created_at) VALUES (%s,%s,%s,1,'[]','[]',%s)",[key(uuid.uuid4()),key(a.pk),key(file.pk),timezone.now()])
    Old=at_0010.get_model('studio','EditorDocument')
    row=Old.objects.get()
    assert row.device=='' and row.inspection_sha256=='' and row.encrypted_commands is None and row.updated_at is None
