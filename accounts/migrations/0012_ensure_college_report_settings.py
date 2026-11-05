from django.db import migrations


def ensure_college_report_settings(apps, schema_editor):
    CollegeReportSettings = apps.get_model("accounts", "CollegeReportSettings")
    CollegeReportSettings.objects.get_or_create(
        pk=1,
        defaults={"website": "https://www.sknscoe.ac.in"},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_shared_college_website"),
    ]

    operations = [
        migrations.RunPython(
            ensure_college_report_settings,
            migrations.RunPython.noop,
        ),
    ]
