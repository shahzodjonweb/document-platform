import logging
from django.db import migrations, models


def one_draft_per_file(apps, schema_editor):
    """Keep one draft per file, the newest with marks or else the newest, and encrypt the marks of those kept.

    Opening a file made a new draft every time. Counts only in the log: the
    marks and the labels are the customer's. Deferred foreign key checks are
    run here, as Postgres refuses to alter a table with deletions pending them.

    The image still serving goes on opening drafts and saving marks, so the
    table is locked first, until this migration commits. A second draft would
    fail the constraint, and a save let in by a weaker lock (SHARE ROW EXCLUSIVE
    lets its SELECT FOR UPDATE through) deadlocks with the constraint's own.
    """
    from apps.studio.domain import pack
    EditorDocument = apps.get_model('studio', 'EditorDocument')
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(f'LOCK TABLE {schema_editor.quote_name(EditorDocument._meta.db_table)} IN ACCESS EXCLUSIVE MODE')
    drafts = EditorDocument.objects.using(schema_editor.connection.alias)
    rows = list(drafts.order_by('-created_at', '-pk').values_list('pk', 'account_id', 'file_id', 'commands'))
    # Each file keeps its newest draft with marks, the customer's work, or else its newest.
    keep = {}
    for pk, account, file, commands in rows:
        if (account, file) not in keep or (commands and not keep[(account, file)][1]):
            keep[(account, file)] = (pk, bool(commands))
    seen, kept = keep, {pk for pk, _ in keep.values()}
    stale = [pk for pk, *_ in rows if pk not in kept]
    stale_with_marks = sum(bool(commands) for pk, _, _, commands in rows if pk not in kept)
    for start in range(0, len(stale), 500):
        drafts.filter(pk__in=stale[start:start + 500]).delete()
    packed = 0
    for draft in drafts.filter(encrypted_commands__isnull=True).only('pk', 'version', 'commands').iterator():
        draft.encrypted_commands = pack({'version': draft.version, 'commands': draft.commands})
        draft.save(update_fields=['encrypted_commands'])
        packed += 1
    schema_editor.connection.check_constraints(table_names=[EditorDocument._meta.db_table])
    logging.getLogger(__name__).info('editor drafts: kept %d, removed %d (%d of them with marks), encrypted %d', len(seen), len(stale), stale_with_marks, packed)


class Migration(migrations.Migration):

    dependencies = [
        ('studio', '0011_editor_lane_seconds'),
    ]

    operations = [
        migrations.RunPython(one_draft_per_file, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='editordocument',
            constraint=models.UniqueConstraint(fields=('account', 'file'), name='editor_one_draft_per_file'),
        ),
    ]
