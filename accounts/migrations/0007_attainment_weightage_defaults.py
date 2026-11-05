from django.db import migrations, models


def update_legacy_defaults(apps, schema_editor):
    AttainmentWeightage = apps.get_model("accounts", "AttainmentWeightage")
    AttainmentWeightage.objects.filter(
        direct_attainment=80,
        indirect_attainment=20,
        cie_weightage=50,
        ese_weightage=40,
        survey_weightage=10,
    ).update(
        direct_attainment=90,
        indirect_attainment=10,
        cie_weightage=40,
        ese_weightage=60,
        survey_weightage=10,
    )


def restore_legacy_defaults(apps, schema_editor):
    AttainmentWeightage = apps.get_model("accounts", "AttainmentWeightage")
    AttainmentWeightage.objects.filter(
        direct_attainment=90,
        indirect_attainment=10,
        cie_weightage=40,
        ese_weightage=60,
        survey_weightage=10,
    ).update(
        direct_attainment=80,
        indirect_attainment=20,
        cie_weightage=50,
        ese_weightage=40,
        survey_weightage=10,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_courseperformanceindicator"),
    ]

    operations = [
        migrations.RunPython(update_legacy_defaults, restore_legacy_defaults),
        migrations.AlterField(
            model_name="attainmentweightage",
            name="direct_attainment",
            field=models.PositiveIntegerField(default=90),
        ),
        migrations.AlterField(
            model_name="attainmentweightage",
            name="indirect_attainment",
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.AlterField(
            model_name="attainmentweightage",
            name="cie_weightage",
            field=models.PositiveIntegerField(default=40),
        ),
        migrations.AlterField(
            model_name="attainmentweightage",
            name="ese_weightage",
            field=models.PositiveIntegerField(default=60),
        ),
    ]
