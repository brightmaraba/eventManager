from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="public_code",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddConstraint(
            model_name="ticket",
            constraint=models.UniqueConstraint(
                condition=models.Q(("public_code__gt", "")),
                fields=("public_code",),
                name="unique_public_code",
            ),
        ),
    ]
