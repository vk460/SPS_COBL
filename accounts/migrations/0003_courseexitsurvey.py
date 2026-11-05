from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_universityexammarks"),
    ]

    operations = [
        migrations.CreateModel(
            name="CourseExitSurvey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question_text", models.TextField(blank=True)),
                ("strongly_agree", models.PositiveIntegerField(default=0)),
                ("agree", models.PositiveIntegerField(default=0)),
                ("neutral", models.PositiveIntegerField(default=0)),
                ("disagree", models.PositiveIntegerField(default=0)),
                ("strongly_disagree", models.PositiveIntegerField(default=0)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="accounts.course")),
                ("course_outcome", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="accounts.courseoutcome")),
            ],
            options={
                "ordering": ["course_outcome__co_number"],
                "unique_together": {("course", "course_outcome")},
            },
        ),
    ]
