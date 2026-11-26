"""Drop the Titan template's sample notes table, now that apps.notes is gone.

The notes app was the template's example feature; Flight never used it.
Its migrations went with it, so this drops the table it left behind.
"""

from django.db import migrations


class Migration(migrations.Migration):
    """Remove notes_note, if it is there."""

    dependencies = [("flights", "0002_load_airports")]

    operations = [
        migrations.RunSQL(
            [
                "DROP TABLE IF EXISTS notes_note;",
                "DELETE FROM django_migrations WHERE app = 'notes';",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
