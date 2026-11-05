from django.utils import timezone
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
import re


def validate_academic_year(value):
    match = re.fullmatch(r"(\d{4})-(\d{2})", value or "")
    if not match or int(match.group(2)) != (int(match.group(1)) + 1) % 100:
        raise ValidationError("Enter the academic year as YYYY-YY, for example 2025-26.")


# -----------------------------
# Department
# -----------------------------
class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_general_science = models.BooleanField(default=False)
    report_department_name = models.CharField(max_length=150, blank=True)
    report_accreditation = models.CharField(max_length=150, blank=True)
    report_email = models.EmailField(blank=True)
    report_hod_name = models.CharField(max_length=150, blank=True)
    report_hod_qualification = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name


class CollegeReportSettings(models.Model):
    website = models.URLField(default="https://www.sknscoe.ac.in")

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


# -----------------------------
# Custom User
# -----------------------------
class User(AbstractUser):
    ROLE_CHOICES = (
        ('HOD', 'HOD'),
        ('FACULTY', 'Faculty'),
        ('STUDENT', 'Student'),
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
class ProgramOutcome(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    po_number = models.CharField(max_length=10)   # PO1, PO2
    description = models.TextField()

    def __str__(self):
        return f"{self.po_number} - {self.department.name}"
    
class ProgramSpecificOutcome(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    pso_number = models.CharField(max_length=10)  # PSO1, PSO2
    description = models.TextField()

    def __str__(self):
        return f"{self.pso_number} - {self.department.name}"

class CourseOutcome(models.Model):

    course = models.ForeignKey(
        "Course",   # 🔥 string reference
        on_delete=models.CASCADE,
        related_name="cos"
    )

    co_number = models.PositiveIntegerField()
    description = models.TextField()
    is_locked = models.BooleanField(default=False)

    class Meta:
        unique_together = ("course", "co_number")
        ordering = ["co_number"]

    def __str__(self):
        return f"CO{self.co_number} - {self.course.course_code}"
    
class BloomLevel(models.Model):

    LEVEL_CHOICES = [
        ("BL1", "BL1"),
        ("BL2", "BL2"),
        ("BL3", "BL3"),
        ("BL4", "BL4"),
        ("BL5", "BL5"),
        ("BL6", "BL6"),
    ]

    level = models.CharField(
        max_length=3,
        choices=LEVEL_CHOICES,
        unique=True
    )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        # Auto create remaining BL levels
        for lvl, _ in self.LEVEL_CHOICES:
            BloomLevel.objects.get_or_create(level=lvl)

    def __str__(self):
        return self.level
    
# -----------------------------
# CO - PO Mapping
# -----------------------------
class COPOMapping(models.Model):

    co = models.ForeignKey(
        "CourseOutcome",
        on_delete=models.CASCADE,
        related_name="po_mappings"
    )

    po = models.ForeignKey(
        "ProgramOutcome",
        on_delete=models.CASCADE
    )

    level = models.IntegerField(
        choices=[
            (1, "Low"),
            (2, "Medium"),
            (3, "High"),
        ]
    )

    class Meta:
        unique_together = ("co", "po")

    def __str__(self):
        return f"{self.co} -> {self.po.po_number} ({self.level})"


# -----------------------------
# CO - PSO Mapping
# -----------------------------
class COPSOMapping(models.Model):

    co = models.ForeignKey(
        "CourseOutcome",
        on_delete=models.CASCADE,
        related_name="pso_mappings"
    )

    pso = models.ForeignKey(
        "ProgramSpecificOutcome",
        on_delete=models.CASCADE
    )

    level = models.IntegerField(
        choices=[
            (1, "Low"),
            (2, "Medium"),
            (3, "High"),
        ]
    )

    class Meta:
        unique_together = ("co", "pso")

    def __str__(self):
        return f"{self.co} -> {self.pso.pso_number} ({self.level})"


class CoursePerformanceIndicator(models.Model):
    course = models.ForeignKey(
        "Course",
        on_delete=models.CASCADE,
        related_name="performance_indicators",
    )
    po = models.ForeignKey(
        ProgramOutcome,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="course_performance_indicators",
    )
    pso = models.ForeignKey(
        ProgramSpecificOutcome,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="course_performance_indicators",
    )
    competency_level = models.CharField(max_length=50)
    competency_description = models.TextField()
    indicator_code = models.CharField(max_length=50)
    indicator_description = models.TextField()
    course_outcomes = models.ManyToManyField(
        CourseOutcome,
        blank=True,
        related_name="performance_indicators",
    )

    class Meta:
        ordering = ["po__po_number", "pso__pso_number", "competency_level", "indicator_code"]

    def clean(self):
        super().clean()
        if bool(self.po_id) == bool(self.pso_id):
            raise ValidationError("Select exactly one PO or PSO.")

    def __str__(self):
        outcome = self.po or self.pso
        return f"{outcome} - {self.indicator_code}"
    

from django.core.exceptions import ValidationError

class AcademicClass(models.Model):

    department = models.ForeignKey(
        "Department",
        on_delete=models.CASCADE,
        related_name="classes"
    )

    mapped_department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mapped_classes"
    )

    name = models.CharField(max_length=50)
    academic_year = models.CharField(max_length=20)
    semester = models.CharField(max_length=10)

    order = models.PositiveIntegerField(default=1)
    is_locked = models.BooleanField(default=False)

    def clean(self):
        validate_academic_year(self.academic_year)
        if self.department.name == "General Science":
            if not self.name.startswith("FY"):
                raise ValidationError(
                    "General Science classes must start with 'FY'"
                )

    def save(self, *args, **kwargs):
        self.name = self.name.strip().upper()   # Auto uppercase
        self.clean()
        super().save(*args, **kwargs)

    @property
    def has_course(self):
        return self.courses.exists()

    def __str__(self):
        return f"{self.name} - {self.semester} ({self.academic_year})"

    class Meta:
        unique_together = (
            'department',
            'mapped_department',
            'name',
            'academic_year',
            'semester'
        )
        ordering = ['-academic_year', '-semester', 'order']
        



class Student(models.Model):

    roll_no = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    list_order = models.PositiveIntegerField(default=0)

    academic_class = models.ForeignKey(
        AcademicClass,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="students"
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    class Meta:
        unique_together = ("roll_no", "academic_class")
        ordering = ["roll_no"]

    def __str__(self):
        return f"{self.roll_no} - {self.name}"



from django.conf import settings

class Course(models.Model):
    academic_class = models.ForeignKey(
        AcademicClass,
        on_delete=models.CASCADE,
        related_name="courses"
    )
    course_code = models.CharField(max_length=20)
    course_name = models.CharField(max_length=100)

    # ✅ ASSIGNED FACULTY
    faculty = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role__in": ["FACULTY", "HOD"]}
    )

    def __str__(self):
        return f"{self.course_code} - {self.course_name}"





class AssessmentTool(models.Model):
    course = models.ForeignKey(
        "Course",
        on_delete=models.CASCADE,
        related_name="assessment_tools"
    )

    main_tool = models.CharField(max_length=50)
    sub_tool = models.CharField(max_length=100)

    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.course.course_code} - {self.main_tool} - {self.sub_tool}"

class IcaAssignmentExp(models.Model):
    tool = models.ForeignKey(AssessmentTool, on_delete=models.CASCADE)
    sub_tool_no = models.PositiveIntegerField()
    co = models.ForeignKey(CourseOutcome, on_delete=models.CASCADE, null=True, blank=True)
    bl = models.CharField(max_length=5)
    marks = models.PositiveIntegerField()

class IcaStudentMarks(models.Model):

    tool = models.ForeignKey(
        AssessmentTool,
        on_delete=models.CASCADE
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE
    )

    subtool = models.ForeignKey(
        IcaAssignmentExp,
        on_delete=models.CASCADE
    )

    marks = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("tool", "student", "subtool")

    def __str__(self):
        return f"{self.student} - {self.subtool} - {self.marks}"

class AssignmentTool(models.Model):
    tool = models.ForeignKey(AssessmentTool, on_delete=models.CASCADE)
    question_no = models.CharField(max_length=20)
    co = models.ForeignKey(CourseOutcome, on_delete=models.CASCADE, null=True, blank=True)
    bl = models.CharField(max_length=5, default="BL1")
    question_count = models.PositiveIntegerField(default=1)
    marks = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("tool", "question_no")
class AssignmentTutorialMarks(models.Model):

    tool = models.ForeignKey(AssessmentTool, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    question = models.ForeignKey(AssignmentTool, on_delete=models.CASCADE)

    marks = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("tool", "student", "question")


class ExamDetail(models.Model):
    tool = models.ForeignKey(AssessmentTool, on_delete=models.CASCADE)
    question_no = models.CharField(max_length=20)
    co = models.ForeignKey(CourseOutcome, on_delete=models.CASCADE, null=True, blank=True)
    bl = models.CharField(max_length=5)
    marks = models.PositiveIntegerField()
    solve_any = models.IntegerField(default=0)

    class Meta:
        unique_together = ("tool", "question_no")

class ExamMarks(models.Model):

    tool = models.ForeignKey(AssessmentTool, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    question = models.ForeignKey(ExamDetail, on_delete=models.CASCADE)

    marks = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("tool", "student", "question")

class UniversityExam(models.Model):

    tool = models.ForeignKey(
        "AssessmentTool",
        on_delete=models.CASCADE,
        related_name="university_exams"
    )

    co = models.ForeignKey(
        "CourseOutcome",
        on_delete=models.CASCADE
    )

    marks = models.FloatField(default=0)

    class Meta:
        unique_together = ("tool", "co")

    def __str__(self):
        return f"{self.tool} - CO{self.co.co_number}"


class UniversityExamMarks(models.Model):
    tool = models.ForeignKey(AssessmentTool, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    marks = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("tool", "student")

    def __str__(self):
        return f"{self.student} - {self.tool} - {self.marks}"


class CourseExitSurvey(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    course_outcome = models.ForeignKey(CourseOutcome, on_delete=models.CASCADE)
    question_text = models.TextField(blank=True)
    strongly_agree = models.PositiveIntegerField(default=0)
    agree = models.PositiveIntegerField(default=0)
    neutral = models.PositiveIntegerField(default=0)
    disagree = models.PositiveIntegerField(default=0)
    strongly_disagree = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("course", "course_outcome")
        ordering = ["course_outcome__co_number"]

    def __str__(self):
        return f"{self.course} - CO{self.course_outcome.co_number} Exit Survey"
    
    
class COTarget(models.Model):

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE
    )

    course_outcome = models.ForeignKey(
        CourseOutcome,
        on_delete=models.CASCADE
    )

    bl_level = models.CharField(
        max_length=3,
        choices=[
            ("BL1", "BL1"),
            ("BL2", "BL2"),
            ("BL3", "BL3"),
            ("BL4", "BL4"),
            ("BL5", "BL5"),
            ("BL6", "BL6"),
        ],
        default="BL1"
    )

    target_percentage = models.PositiveIntegerField()

    class Meta:
        unique_together = ("course", "course_outcome")

    def __str__(self):
        return f"{self.course} - CO{self.course_outcome.co_number} ({self.target_percentage}%)"


class COQualityLoop(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    course_outcome = models.ForeignKey(CourseOutcome, on_delete=models.CASCADE)
    action_proposed = models.TextField(blank=True)
    target_modification = models.TextField(blank=True)

    class Meta:
        unique_together = ("course", "course_outcome")

    def __str__(self):
        return f"{self.course} - CO{self.course_outcome.co_number} Quality Loop"


class AttainmentLevelThreshold(models.Model):
    course = models.OneToOneField(Course, on_delete=models.CASCADE)
    level_2_min = models.PositiveSmallIntegerField(default=34)
    level_3_min = models.PositiveSmallIntegerField(default=67)

    def __str__(self):
        return f"{self.course} - Attainment Levels"
    

class AttainmentWeightage(models.Model):

    course = models.OneToOneField(
        Course,
        on_delete=models.CASCADE
    )

    direct_attainment = models.PositiveIntegerField(default=90)
    indirect_attainment = models.PositiveIntegerField(default=10)

    cie_weightage = models.PositiveIntegerField(default=40)
    ese_weightage = models.PositiveIntegerField(default=60)
    survey_weightage = models.PositiveIntegerField(default=10)

    def __str__(self):
        return f"{self.course} Weightage"
    
class COAttainmentPerTool(models.Model):
    """
    Stores aggregated attainment data for each CO in each AssessmentTool.
    This is calculated and saved after marks entry or on demand.
    """
    tool = models.ForeignKey(AssessmentTool, on_delete=models.CASCADE, related_name="co_attainments")
    co = models.ForeignKey(CourseOutcome, on_delete=models.CASCADE)

    # Aggregated values
    students_attempted = models.PositiveIntegerField(default=0)  # No. of students with non-null marks
    average_marks = models.FloatField(default=0.0)               # Class average marks for this CO
    attainment_percentage = models.FloatField(default=0.0)       # (avg / max) * 100
    max_marks = models.FloatField(default=0.0)                   # Sum of max marks for this CO

    # Metadata
    calculated_at = models.DateTimeField(auto_now=True)
    is_locked = models.BooleanField(default=False)  # Optional: lock after final calculation

    class Meta:
        unique_together = ('tool', 'co')
        verbose_name = "CO Attainment (per Tool)"
        verbose_name_plural = "CO Attainments (per Tool)"
        ordering = ['co__co_number']

    def __str__(self):
        return f"{self.tool} - CO{self.co.co_number} ({self.attainment_percentage:.2f}%)"
