# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    # Core ones
    User, Department, AcademicClass, Student,
    ProgramOutcome, ProgramSpecificOutcome, BloomLevel,
    
    # Add these gradually as you start using them
    Course, CourseOutcome,
    COPOMapping, COPSOMapping,
    AssessmentTool, IcaAssignmentExp, AssignmentTool, ExamDetail,
    COTarget, AttainmentWeightage,
    # Marks models can be registered later if needed
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    list_display = ('username', 'email', 'role', 'department', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('role', 'department', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('username',)

    fieldsets = UserAdmin.fieldsets + (
        ('Role & Department', {
            'fields': ('role', 'department'),
        }),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Role & Department', {
            'fields': ('role', 'department'),
        }),
    )

    # Optional: make some fields readonly after creation
    readonly_fields = ('last_login', 'date_joined')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_general_science')
    list_filter = ('is_general_science',)
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(AcademicClass)
class AcademicClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'department', 'mapped_department', 'academic_year', 'semester', 'is_locked')
    list_filter = ('department', 'academic_year', 'semester', 'is_locked')
    search_fields = ('name', 'academic_year')
    raw_id_fields = ('department', 'mapped_department')  # faster when many departments
    ordering = ('-academic_year', '-semester', 'name')


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('roll_no', 'name', 'academic_class', 'department')
    list_filter = ('academic_class__department', 'academic_class__academic_year')
    search_fields = ('roll_no', 'name')
    raw_id_fields = ('academic_class', 'department')
    ordering = ('roll_no',)


@admin.register(ProgramOutcome)
class ProgramOutcomeAdmin(admin.ModelAdmin):
    list_display = ('po_number', 'department', 'description_short')
    list_filter = ('department',)
    search_fields = ('po_number', 'description')
    raw_id_fields = ('department',)

    def description_short(self, obj):
        return obj.description[:60] + "..." if len(obj.description) > 60 else obj.description
    description_short.short_description = "Description"


@admin.register(ProgramSpecificOutcome)
class ProgramSpecificOutcomeAdmin(admin.ModelAdmin):
    list_display = ('pso_number', 'department', 'description_short')
    list_filter = ('department',)
    search_fields = ('pso_number', 'description')
    raw_id_fields = ('department',)

    def description_short(self, obj):
        return obj.description[:60] + "..." if len(obj.description) > 60 else obj.description
    description_short.short_description = "Description"


@admin.register(BloomLevel)
class BloomLevelAdmin(admin.ModelAdmin):
    list_display = ('level',)
    ordering = ('level',)
    # No need for much else — it's mostly static


# ────────────────────────────────────────────────
# Register more models when you're ready to enter data
# ────────────────────────────────────────────────

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('course_code', 'course_name', 'academic_class', 'faculty')
    list_filter = ('academic_class__department', 'faculty')
    search_fields = ('course_code', 'course_name')
    raw_id_fields = ('academic_class', 'faculty')


@admin.register(CourseOutcome)
class CourseOutcomeAdmin(admin.ModelAdmin):
    list_display = ('co_number', 'course', 'description_short', 'is_locked')
    list_filter = ('course__academic_class__department', 'is_locked')
    search_fields = ('course__course_code', 'description')
    raw_id_fields = ('course',)

    def description_short(self, obj):
        return obj.description[:60] + "..." if len(obj.description) > 60 else obj.description
    description_short.short_description = "Description"

from django.contrib import admin
from .models import COAttainmentPerTool

@admin.register(COAttainmentPerTool)
class COAttainmentPerToolAdmin(admin.ModelAdmin):
    list_display = ('tool', 'co', 'students_attempted', 'average_marks', 'attainment_percentage', 'max_marks', 'calculated_at')
    list_filter = ('tool__course', 'co')
    search_fields = ('tool__course__course_code', 'co__co_number')
    readonly_fields = ('calculated_at',)
# ... similarly for COPOMapping, AssessmentTool, etc.