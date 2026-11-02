"""0010 under the image still serving: its rows have marks only in the clear."""
import uuid
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from apps.studio.models import EditorDocument
from tests.test_platform import account,upload

BEFORE=[('studio','0010_editor_groundwork')]


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


def test_the_image_before_this_one_can_still_write_after_0010(at_0010):
    """Deploy migrates before it swaps the API: the old code's insert names none of the new columns."""
    a=account();file=upload(a)
    key=lambda value:value.hex if connection.vendor=='sqlite' else str(value)
    with connection.cursor() as cursor:
        cursor.execute(f"INSERT INTO {EditorDocument._meta.db_table} (id,account_id,file_id,version,commands,input_ids,created_at) VALUES (%s,%s,%s,1,'[]','[]',%s)",[key(uuid.uuid4()),key(a.pk),key(file.pk),timezone.now()])
    Old=at_0010.get_model('studio','EditorDocument')
    row=Old.objects.get()
    assert row.device=='' and row.inspection_sha256=='' and row.encrypted_commands is None and row.updated_at is None
