from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="UniversityExamMarks",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("marks", models.FloatField(blank=True, null=True)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="accounts.student")),
                ("tool", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="accounts.assessmenttool")),
            ],
            options={
                "unique_together": {("tool", "student")},
            },
        ),
    ]
