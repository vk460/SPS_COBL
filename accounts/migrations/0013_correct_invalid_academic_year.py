from django.db import migrations


def correct_invalid_academic_year(apps, schema_editor):
    AcademicClass = apps.get_model("accounts", "AcademicClass")
    AcademicClass.objects.filter(academic_year="2").update(academic_year="2025-26")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_ensure_college_report_settings"),
    ]

    operations = [
        migrations.RunPython(
            correct_invalid_academic_year,
            migrations.RunPython.noop,
        ),
    ]
