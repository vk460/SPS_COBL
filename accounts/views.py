from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.models import update_last_login
from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
import io
import base64
import math
import re
from pathlib import Path
from collections import defaultdict
from django.db.models import Count, Q, Sum
from django.db import transaction

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ModuleNotFoundError:
    matplotlib = None
    plt = None

from .models import (
    AcademicClass,
    AssessmentTool,
    AttainmentWeightage,
    AssignmentTool,
    AssignmentTutorialMarks,
    COAttainmentPerTool,
    CollegeReportSettings,
    COPOMapping,
    COPSOMapping,
    COTarget,
    Course,
    CourseOutcome,
    CoursePerformanceIndicator,
    ExamDetail,
    ExamMarks,
    IcaAssignmentExp,
    IcaStudentMarks,
    ProgramOutcome,
    ProgramSpecificOutcome,
    Student,
    UniversityExam,
    UniversityExamMarks,
)

User = get_user_model()

# =====================================================
# AUTHENTICATION
# =====================================================

def home(request):
    return render(request, "accounts/home.html")


def no_permission(request):
    return HttpResponseForbidden("You do not have permission to access this page.")

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required


def login_view(request):

    role = request.GET.get("role") or request.POST.get("role")

    if request.method == "POST":

        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user:
            user_logged_in.disconnect(update_last_login, dispatch_uid="update_last_login")
            login(request, user)

            if user.role == "HOD":
                return redirect("hod_dashboard")

            elif user.role == "FACULTY":
                return redirect("faculty_dashboard")

            elif user.role == "STUDENT":
                return redirect("home")

        return render(request, "accounts/login.html", {
            "error": "Invalid username or password",
            "role": role
        })

    return render(request, "accounts/login.html", {"role": role})


def logout_view(request):
    logout(request)
    return redirect("login")

# =====================================================
# DASHBOARDS
# =====================================================

def _course_completion_rows(department):
    courses = list(
        Course.objects.filter(academic_class__department=department)
        .select_related(
            "academic_class",
            "academic_class__department",
            "academic_class__mapped_department",
            "faculty",
        )
        .order_by(
            "academic_class__academic_year",
            "academic_class__semester",
            "course_code",
        )
    )
    if not courses:
        return []

    course_ids = [course.id for course in courses]
    course_outcomes = list(
        CourseOutcome.objects.filter(course_id__in=course_ids)
        .values_list("course_id", "id")
    )
    co_ids_by_course = defaultdict(set)
    for course_id, co_id in course_outcomes:
        co_ids_by_course[course_id].add(co_id)

    assessment_tools = list(
        AssessmentTool.objects.filter(course_id__in=course_ids)
        .values("id", "course_id", "main_tool")
    )
    tools_by_course = defaultdict(list)
    tool_types = {}
    tool_ids_by_type = defaultdict(list)
    for tool in assessment_tools:
        tool_type = tool["main_tool"].strip().lower()
        tools_by_course[tool["course_id"]].append(tool)
        tool_types[tool["id"]] = tool_type
        tool_ids_by_type[tool_type].append(tool["id"])

    tool_item_counts = {}
    supported_tool_models = (
        (
            ("ica", "experiment", "practical"),
            IcaAssignmentExp,
            True,
        ),
        (
            ("ise assignment", "assignment", "tutorial"),
            AssignmentTool,
            True,
        ),
        (
            ("ese", "university exam theory", "mock oral"),
            UniversityExam,
            False,
        ),
        (
            ("ise exam", "ut1", "ut2", "ut3", "prelim", "exam"),
            ExamDetail,
            True,
        ),
    )
    for aliases, item_model, has_optional_co in supported_tool_models:
        relevant_tool_ids = [
            tool_id
            for tool_type in aliases
            for tool_id in tool_ids_by_type[tool_type]
        ]
        if not relevant_tool_ids:
            continue
        annotations = {"total": Count("id")}
        if has_optional_co:
            annotations["missing_co"] = Count(
                "id",
                filter=Q(co__isnull=True),
            )
        for item_stats in (
            item_model.objects.filter(tool_id__in=relevant_tool_ids)
            .values("tool_id")
            .annotate(**annotations)
        ):
            tool_item_counts[item_stats["tool_id"]] = (
                item_stats["total"],
                item_stats.get("missing_co", 0),
            )

    mark_students_by_tool = {}
    for mark_model in (
        IcaStudentMarks,
        AssignmentTutorialMarks,
        ExamMarks,
        UniversityExamMarks,
    ):
        for mark_stats in (
            mark_model.objects.filter(tool__course_id__in=course_ids)
            .exclude(marks__isnull=True)
            .values("tool_id")
            .annotate(student_count=Count("student_id", distinct=True))
        ):
            mark_students_by_tool[mark_stats["tool_id"]] = mark_stats["student_count"]

    target_co_ids_by_course = defaultdict(set)
    for course_id, co_id in COTarget.objects.filter(
        course_id__in=course_ids
    ).values_list("course_id", "course_outcome_id"):
        target_co_ids_by_course[course_id].add(co_id)
    weighted_course_ids = set(
        AttainmentWeightage.objects.filter(course_id__in=course_ids)
        .values_list("course_id", flat=True)
    )

    mapped_co_ids_by_course = defaultdict(set)
    for course_id, co_id in COPOMapping.objects.filter(
        co__course_id__in=course_ids
    ).values_list("co__course_id", "co_id"):
        mapped_co_ids_by_course[course_id].add(co_id)
    for course_id, co_id in COPSOMapping.objects.filter(
        co__course_id__in=course_ids
    ).values_list("co__course_id", "co_id"):
        mapped_co_ids_by_course[course_id].add(co_id)

    outcome_department_ids = {
        course.academic_class.mapped_department_id
        if course.academic_class.department.is_general_science
        else course.academic_class.department_id
        for course in courses
    }
    outcome_department_ids.discard(None)
    department_ids_with_outcomes = set(
        ProgramOutcome.objects.filter(department_id__in=outcome_department_ids)
        .values_list("department_id", flat=True)
    )
    department_ids_with_outcomes.update(
        ProgramSpecificOutcome.objects.filter(department_id__in=outcome_department_ids)
        .values_list("department_id", flat=True)
    )
    college_website = CollegeReportSettings.objects.filter(pk=1).values_list(
        "website",
        flat=True,
    ).first()

    completion_rows = []
    for course in courses:
        course_co_ids = co_ids_by_course[course.id]
        course_tools = tools_by_course[course.id]
        department_id = (
            course.academic_class.mapped_department_id
            if course.academic_class.department.is_general_science
            else course.academic_class.department_id
        )

        course_tool_setup_complete = bool(course_tools)
        course_marks_complete = bool(course_tools)
        for tool in course_tools:
            tool_id = tool["id"]
            tool_type = tool_types[tool_id]
            item_stats = tool_item_counts.get(tool_id, (0, 0))
            if not any(tool_type in aliases for aliases, _, _ in supported_tool_models):
                course_tool_setup_complete = False
                course_marks_complete = False
                continue
            if item_stats[0] == 0 or item_stats[1] > 0:
                course_tool_setup_complete = False
                course_marks_complete = False
            if mark_students_by_tool.get(tool_id, 0) == 0:
                course_marks_complete = False

        course_targets_complete = (
            bool(course_co_ids)
            and course.id in weighted_course_ids
            and course_co_ids.issubset(target_co_ids_by_course[course.id])
        )
        course_mappings_complete = (
            bool(course_co_ids)
            and department_id in department_ids_with_outcomes
            and course_co_ids.issubset(mapped_co_ids_by_course[course.id])
        )

        steps = [
            {
                "label": "Course outcomes",
                "complete": bool(course_co_ids),
                "required": True,
            },
            {
                "label": "Assessment tools and CO mapping",
                "complete": course_tool_setup_complete,
                "required": True,
            },
            {
                "label": "Student marks",
                "complete": course_marks_complete,
                "required": True,
            },
            {
                "label": "Attainment weightage and CO targets",
                "complete": course_targets_complete,
                "required": True,
            },
        ]
        if department_id in department_ids_with_outcomes:
            steps.append({
                "label": "PO/PSO mappings",
                "complete": course_mappings_complete,
                "required": True,
            })
        steps.append({
            "label": "CO-PO-PSO Attainment",
            "complete": (
                bool(course_co_ids)
                and course_tool_setup_complete
                and course_marks_complete
                and course_targets_complete
                and course_mappings_complete
            ),
            "required": True,
            "url_name": "co_po_pso_attainment",
        })
        steps.append({
            "label": "Department report header",
            "complete": bool(
                course.academic_class.department.report_accreditation
                and course.academic_class.department.report_email
                and course.academic_class.department.report_hod_name
                and course.academic_class.department.report_hod_qualification
                and college_website
            ),
            "required": True,
        })

        required_steps = [step for step in steps if step["required"]]
        completed_count = sum(step["complete"] for step in required_steps)
        total_count = len(required_steps)
        percentage = round(completed_count * 100 / total_count) if total_count else 0
        pending_sections = [
            step["label"] for step in required_steps if not step["complete"]
        ]
        status = (
            "Ready" if completed_count == total_count
            else "Not started" if completed_count == 0
            else "In progress"
        )
        completion_rows.append({
            "course": course,
            "steps": steps,
            "completed_count": completed_count,
            "total_count": total_count,
            "percentage": percentage,
            "pending_sections": pending_sections,
            "status": status,
            "status_class": status.lower().replace(" ", "-"),
        })

    return sorted(
        completion_rows,
        key=lambda row: (
            row["status"] == "Ready",
            row["percentage"],
            row["course"].course_code,
        ),
    )


@login_required
def hod_dashboard(request):
    if request.user.role != "HOD":
        return HttpResponseForbidden("Access denied")

    user = request.user

    teachers = User.objects.filter(
        department=user.department,
        role="FACULTY"
    )

    assigned_courses = Course.objects.filter(
        faculty=user
    ).select_related(
        "academic_class"
    ).order_by(
        "academic_class__academic_year",
        "academic_class__semester",
        "course_code"
    )
    current_semester = None

    classes = AcademicClass.objects.filter(
        department=user.department
    )

    if classes.exists():

        # Get latest academic year
        latest_year = classes.order_by("-academic_year") \
                              .values_list("academic_year", flat=True) \
                              .first()

        # Get latest semester inside that year
        current_semester = classes.filter(
            academic_year=latest_year
        ).order_by("-semester") \
         .values_list("semester", flat=True) \
         .first()

    return render(request, "accounts/hod_dashboard.html", {
        "teachers": teachers,
        "assigned_courses": assigned_courses,
        "current_semester": current_semester,
    })


@login_required
def hod_course_completion(request):
    if request.user.role != "HOD" or not request.user.department:
        return HttpResponseForbidden("Access denied")

    department = request.user.department
    all_rows = _course_completion_rows(department)
    class_ids = sorted({
        row["course"].academic_class_id for row in all_rows
    })
    classes = list(
        AcademicClass.objects.filter(id__in=class_ids).order_by(
            "-academic_year", "-semester", "order", "name"
        )
    )
    class_options = [
        (
            str(academic_class.id),
            f"{academic_class.name} · Semester {academic_class.semester} · "
            f"{academic_class.academic_year}",
        )
        for academic_class in classes
    ]
    year_options = sorted({
        row["course"].academic_class.academic_year for row in all_rows
    }, reverse=True)
    semester_options = sorted({
        row["course"].academic_class.semester for row in all_rows
    })
    faculty_by_id = {}
    for row in all_rows:
        faculty = row["course"].faculty
        if faculty:
            faculty_by_id[faculty.id] = (
                faculty.get_full_name() or faculty.username
            )
    faculty_options = sorted(
        ((str(faculty_id), name) for faculty_id, name in faculty_by_id.items()),
        key=lambda option: option[1].casefold(),
    )

    selected_class = request.GET.get("class", "").strip()
    selected_year = request.GET.get("year", "").strip()
    selected_semester = request.GET.get("semester", "").strip()
    selected_faculty = request.GET.get("faculty", "").strip()
    selected_status = request.GET.get("status", "").strip()
    search_query = request.GET.get("q", "").strip()

    filtered_rows = all_rows
    if selected_class:
        filtered_rows = [
            row for row in filtered_rows
            if str(row["course"].academic_class_id) == selected_class
        ]
    if selected_year:
        filtered_rows = [
            row for row in filtered_rows
            if row["course"].academic_class.academic_year == selected_year
        ]
    if selected_semester:
        filtered_rows = [
            row for row in filtered_rows
            if row["course"].academic_class.semester == selected_semester
        ]
    if selected_faculty == "unassigned":
        filtered_rows = [
            row for row in filtered_rows if row["course"].faculty_id is None
        ]
    elif selected_faculty:
        filtered_rows = [
            row for row in filtered_rows
            if str(row["course"].faculty_id) == selected_faculty
        ]
    valid_statuses = {"Ready", "In progress", "Not started"}
    if selected_status in valid_statuses:
        filtered_rows = [
            row for row in filtered_rows if row["status"] == selected_status
        ]
    if search_query:
        normalized_query = search_query.casefold()
        filtered_rows = [
            row for row in filtered_rows
            if normalized_query in row["course"].course_code.casefold()
            or normalized_query in row["course"].course_name.casefold()
        ]

    class_order = {
        academic_class.id: index
        for index, academic_class in enumerate(classes)
    }
    filtered_rows.sort(
        key=lambda row: (
            class_order.get(row["course"].academic_class_id, len(classes)),
            row["course"].course_code.casefold(),
        )
    )
    rows_by_class = defaultdict(list)
    for row in filtered_rows:
        academic_class = row["course"].academic_class
        rows_by_class[academic_class.id].append(row)
    class_groups = [
        {
            "academic_class": academic_class,
            "rows": rows_by_class[academic_class.id],
        }
        for academic_class in classes
        if academic_class.id in rows_by_class
    ]

    return render(request, "accounts/hod_course_completion.html", {
        "class_groups": class_groups,
        "course_count": len(filtered_rows),
        "ready_count": sum(row["status"] == "Ready" for row in filtered_rows),
        "in_progress_count": sum(
            row["status"] == "In progress" for row in filtered_rows
        ),
        "not_started_count": sum(
            row["status"] == "Not started" for row in filtered_rows
        ),
        "class_options": class_options,
        "year_options": year_options,
        "semester_options": semester_options,
        "faculty_options": faculty_options,
        "selected_class": selected_class,
        "selected_year": selected_year,
        "selected_semester": selected_semester,
        "selected_faculty": selected_faculty,
        "selected_status": selected_status,
        "search_query": search_query,
    })


@login_required
def department_report_header(request):
    if request.user.role != "HOD" or not request.user.department:
        return HttpResponseForbidden("Access denied")

    department = request.user.department
    college_settings, _ = CollegeReportSettings.objects.get_or_create(pk=1)
    edit_mode = request.GET.get("edit") == "1"
    if request.method == "POST":
        edit_mode = True
        form = DepartmentReportHeaderForm(request.POST, instance=department)
        college_form = CollegeWebsiteForm(request.POST, instance=college_settings)
        if form.is_valid() and college_form.is_valid():
            form.save()
            college_form.save()
            messages.success(request, "Department report header details saved.")
            return redirect("department_report_header")
    else:
        form = DepartmentReportHeaderForm(instance=department)
        college_form = CollegeWebsiteForm(instance=college_settings)

    return render(
        request,
        "accounts/department_report_header.html",
        {
            "form": form,
            "college_form": college_form,
            "department": department,
            "edit_mode": edit_mode,
        },
    )


@login_required(login_url='login')
def faculty_dashboard(request):
    # Only FACULTY allowed
    if request.user.role != "FACULTY":
        return HttpResponseForbidden("Access denied")

    # Courses assigned to this faculty
    courses = Course.objects.filter(faculty=request.user)

    return render(
        request,
        "accounts/faculty_dashboard.html",
        {
            "courses": courses
        }
    )


# =====================================================
# HOD → CREATE FACULTY
# =====================================================

@login_required
def create_teacher(request):
    if request.user.role != "HOD":
        return HttpResponseForbidden("Only HOD can create teachers")

    teachers = User.objects.filter(
        role="FACULTY",
        department=request.user.department,
    )

    error = success = None

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        name = request.POST.get("name")

        if User.objects.filter(username=username).exists():
            error = "Username already exists"
        else:
            User.objects.create_user(
                username=username,
                password=password,
                first_name=name,
                role="FACULTY",
                department=request.user.department,
            )
            success = "Teacher created successfully"

    return render(request, "accounts/create_teacher.html", {
        "teachers": teachers,
        "error": error,
        "success": success,
    })

# =====================================================
# HOD → RESET FACULTY PASSWORD (AJAX)
# =====================================================

@login_required
def reset_teacher_password(request):
    if request.user.role != "HOD":
        return JsonResponse({"error": "Unauthorized"}, status=403)

    if request.method == "POST":
        teacher_id = request.POST.get("teacher")
        password = request.POST.get("password")

        teacher = get_object_or_404(
            User,
            id=teacher_id,
            role="FACULTY",
            department=request.user.department,
        )

        teacher.set_password(password)
        teacher.save()
        return JsonResponse({"success": True})

    return JsonResponse({"error": "Invalid request"}, status=400)


@login_required
def delete_teacher(request, teacher_id):
    # Only HOD can delete teachers
    if request.user.role != "HOD":
        return HttpResponseForbidden("Not allowed")

    teacher = get_object_or_404(
        User,
        id=teacher_id,
        role="FACULTY",
        department=request.user.department
    )

    # ❗ Optional safety check (recommended)
    if teacher.course_set.exists():
        # If teacher has assigned courses, you can block delete
        return HttpResponseForbidden("Teacher is assigned to courses")

    teacher.delete()
    return redirect("hod_dashboard")
# =====================================================
# HOD → PO & PSO (DEPARTMENT LEVEL)
# =====================================================

@login_required
def manage_po(request):
    if request.user.role != "HOD":
        return HttpResponseForbidden()

    department = request.user.department
    pos = ProgramOutcome.objects.filter(department=department).order_by("po_number")

    if request.method == "POST":
        count = int(request.POST.get("po_count", 0))

        with transaction.atomic():
            for i in range(1, count + 1):
                desc = request.POST.get(f"po_desc_{i}", "").strip()
                if desc:
                    po_number = f"PO{i}"
                    ProgramOutcome.objects.update_or_create(
                        department=department,
                        po_number=po_number,
                        defaults={"description": desc}
                    )
        return redirect("manage_po")

    return render(request, "accounts/manage_po.html", {
        "department": department,
        "pos": pos,
        "po_count": pos.count(),
    })


@login_required
def manage_pso(request):

    if request.user.role != "HOD":
        return HttpResponseForbidden()

    department = request.user.department

    psos = ProgramSpecificOutcome.objects.filter(
        department=department
    ).order_by("pso_number")

    if request.method == "POST":

        count = int(request.POST.get("pso_count", 0))

        with transaction.atomic():
            for i in range(1, count + 1):
                desc = request.POST.get(f"pso_desc_{i}", "").strip()
                if not desc:
                    continue
                desc = desc.replace("\n", " ")
                pso_number = f"PSO{i}"
                ProgramSpecificOutcome.objects.update_or_create(
                    department=department,
                    pso_number=pso_number,
                    defaults={"description": desc}
                )
        return redirect("manage_pso")

    return render(request, "accounts/manage_pso.html", {
        "department": department,
        "psos": psos,
        "pso_count": psos.count(),
    })
# =====================================================
# HOD → MANAGE ACADEMIC CLASSES (FULL CRUD)
# =====================================================
# views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import (
    AcademicClass,
    Department,
    ProgramOutcome,
    ProgramSpecificOutcome,
    validate_academic_year,
)

from django.shortcuts import get_object_or_404


@login_required
def gs_class_create(request):

    user = request.user

    if not user.department or not user.department.is_general_science:
        return redirect("no_permission")

    departments = Department.objects.filter(is_general_science=False)

    if request.method == "POST":

        academic_year = request.POST.get("academic_year")
        semester = request.POST.get("semester")

        mapped_depts = request.POST.getlist("mapped_department[]")
        class_names = request.POST.getlist("class_name[]")
        orders = request.POST.getlist("order[]")

        try:
            validate_academic_year(academic_year)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect("gs_class_create")

        for dept_id, name, order in zip(mapped_depts, class_names, orders):

            if not dept_id or not name.strip():
                continue

            mapped_dept = get_object_or_404(Department, id=dept_id)

            try:

                AcademicClass.objects.create(
                    department=user.department,
                    mapped_department=mapped_dept,
                    name=name.strip(),
                    academic_year=academic_year,
                    semester=semester,
                    order=order,
                    is_locked=True
                )

            except ValidationError as e:

                messages.error(request, e.messages[0])
                return redirect("gs_class_create")

        messages.success(request, "Classes created successfully")
        return redirect("gs_class_list")

    return render(request, "general_science/create.html", {
        "departments": departments
    })

@login_required
def gs_sem_edit(request, year, sem):

    user = request.user

    classes = AcademicClass.objects.filter(
        department=user.department,
        academic_year=year,
        semester=sem
    )

    for c in classes:
        if c.has_course:
            return redirect("gs_class_list")

    classes.update(is_locked=False)

    return redirect("gs_class_list")

@login_required
def gs_class_list(request):

    user = request.user

    if not user.department or not user.department.is_general_science:
        return redirect("no_permission")

    classes = AcademicClass.objects.filter(
        department=user.department
    ).order_by("-academic_year", "-semester", "order")

    departments = Department.objects.filter(
        is_general_science=False
    )

    return render(request, "general_science/list.html", {
        "classes": classes,
        "departments": departments
    })

from django.contrib import messages
from django.core.exceptions import ValidationError

@login_required
def gs_sem_update(request, year, sem):

    user = request.user

    classes = AcademicClass.objects.filter(
        department=user.department,
        academic_year=year,
        semester=sem
    )

    if request.method == "POST":

        for c in classes:

            if c.has_course:
                continue

            new_name = request.POST.get(f"name_{c.id}")
            new_order = request.POST.get(f"order_{c.id}")
            new_dept_id = request.POST.get(f"dept_{c.id}")

            if new_name is not None and new_name.strip() == "":
                if Student.objects.filter(academic_class=c).exists():
                    messages.error(
                        request,
                        f"{c.name} still has students. Move or remove the students "
                        "before removing this class.",
                    )
                    return redirect("gs_class_list")
                c.delete()
                continue

            try:
                if new_name:
                    c.name = new_name.strip().upper()

                if new_order:
                    c.order = new_order

                if new_dept_id:
                    c.mapped_department_id = new_dept_id

                c.is_locked = True
                c.save()

            except ValidationError as e:
                messages.error(request, e.messages[0])
                return redirect("gs_class_list")

        # New Rows
        new_names = request.POST.getlist("new_name[]")
        new_orders = request.POST.getlist("new_order[]")
        new_depts = request.POST.getlist("new_dept[]")

        for name, order, dept_id in zip(new_names, new_orders, new_depts):

            if not name.strip() or not dept_id:
                continue

            try:
                AcademicClass.objects.create(
                    department=user.department,
                    mapped_department_id=dept_id,
                    name=name.strip().upper(),
                    academic_year=year,
                    semester=sem,
                    order=order,
                    is_locked=True
                )
            except ValidationError as e:
                messages.error(request, e.messages[0])
                return redirect("gs_class_list")

        messages.success(request, "Semester Updated Successfully")

    return redirect("gs_class_list")


from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import AcademicClass


@login_required
def dept_class_create(request):

    user = request.user

    # Only NON General Science HOD allowed
    if not user.department or user.department.is_general_science:
        return redirect("no_permission")

    if request.method == "POST":

        academic_year = request.POST.get("academic_year")
        semester = request.POST.get("semester")

        class_names = request.POST.getlist("class_name[]")
        orders = request.POST.getlist("order[]")

        try:
            validate_academic_year(academic_year)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect("dept_class_create")

        for name, order in zip(class_names, orders):

            if name.strip() == "":
                continue

            AcademicClass.objects.create(
                department=user.department,
                name=name.strip(),
                academic_year=academic_year,
                semester=semester,
                order=order,
                is_locked=True
            )

        messages.success(request, "Classes Created Successfully")
        return redirect("dept_class_list")

    return render(request, "department/create.html")
@login_required
def dept_class_list(request):

    user = request.user

    if not user.department or user.department.is_general_science:
        return redirect("no_permission")

    classes = AcademicClass.objects.filter(
        department=user.department
    ).order_by("-academic_year", "-semester")

    return render(request, "department/list.html", {
        "classes": classes
    })

@login_required
def dept_sem_edit(request, year, sem):

    user = request.user

    classes = AcademicClass.objects.filter(
        department=user.department,
        academic_year=year,
        semester=sem
    )

    # Check if ANY class has courses
    if Course.objects.filter(academic_class__in=classes).exists():
        return redirect("dept_class_list")

    classes.update(is_locked=False)

    return redirect("dept_class_list")

@login_required
def dept_sem_update(request, year, sem):

    user = request.user

    classes = AcademicClass.objects.filter(
        department=user.department,
        academic_year=year,
        semester=sem
    )

    if request.method == "POST":

        # 🔹 Update existing rows
        for c in classes:

            if c.has_course:
                continue

            new_name = request.POST.get(f"name_{c.id}")
            new_order = request.POST.get(f"order_{c.id}")

            if new_name is not None and new_name.strip() == "":
                if Student.objects.filter(academic_class=c).exists():
                    messages.error(
                        request,
                        f"{c.name} still has students. Move or remove the students "
                        "before removing this class.",
                    )
                    return redirect("dept_class_list")
                c.delete()
                continue

            if new_name:
                c.name = new_name.strip()

            if new_order:
                c.order = new_order

            c.is_locked = True
            c.save()

        # 🔹 Create new rows
        new_names = request.POST.getlist("new_name[]")
        new_orders = request.POST.getlist("new_order[]")

        for name, order in zip(new_names, new_orders):

            if name.strip() == "":
                continue

            AcademicClass.objects.create(
                department=user.department,
                name=name.strip(),
                academic_year=year,
                semester=sem,
                order=order,
                is_locked=True
            )

    return redirect("dept_class_list")

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse

from django.db.models.functions import Cast
from django.db.models import IntegerField

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException
from zipfile import BadZipFile

from .models import Student, AcademicClass

@login_required
def assign_students(request, class_id):
    academic_class = get_object_or_404(AcademicClass, id=class_id)

    if not request.user.is_superuser:
        if request.user.role != "HOD" or academic_class.department != request.user.department:
            return HttpResponseForbidden("Not allowed")

    # 👩‍🎓 Students of THIS class only
    students = (
        Student.objects
        .filter(academic_class=academic_class)
        .order_by("list_order", "pk")
    )

    MAX_ROLL = 120
    used_rolls = students.values_list("roll_no", flat=True)
    available_rolls = [
        str(i) for i in range(1, MAX_ROLL + 1)
        if str(i) not in used_rolls
    ]

    if request.method == "POST":
        action = request.POST.get("action")
        student_id = request.POST.get("student_id")
        roll_no = (request.POST.get("roll_no") or "").strip()
        name = " ".join((request.POST.get("name") or "").split())

        # 🗑 DELETE
        if action == "delete" and student_id:
            student = get_object_or_404(
                Student,
                id=student_id,
                academic_class=academic_class
            )
            has_marks = (
                IcaStudentMarks.objects.filter(student=student).exists()
                or AssignmentTutorialMarks.objects.filter(student=student).exists()
                or ExamMarks.objects.filter(student=student).exists()
                or UniversityExamMarks.objects.filter(student=student).exists()
            )
            if has_marks:
                messages.error(
                    request,
                    "This student has saved assessment marks and cannot be deleted.",
                )
                return redirect(request.path)
            student.delete()
            messages.success(request, "Student deleted")
            return redirect(request.path)

        if not roll_no or not name:
            messages.error(request, "Roll number and student name are required.")
            return redirect(request.path)

        # 🔁 DUPLICATE ROLL CHECK (CLASS-WISE)
        qs = Student.objects.filter(
            roll_no=roll_no,
            academic_class=academic_class
        )
        if student_id:
            qs = qs.exclude(id=student_id)

        if qs.exists():
            messages.error(request, "Roll number already exists in this class")
            return redirect(request.path)

        # ✏️ EDIT
        if student_id:
            Student.objects.filter(
                id=student_id,
                academic_class=academic_class
            ).update(
                roll_no=roll_no,
                name=name
            )
            messages.success(request, "Student updated")

        # ➕ ADD
        else:
            Student.objects.create(
                roll_no=roll_no,
                name=name,
                list_order=(
                    Student.objects.filter(
                        academic_class=academic_class
                    ).aggregate(max_order=Max("list_order"))["max_order"] or 0
                ) + 1,
                academic_class=academic_class,
                department=academic_class.department
            )
            messages.success(request, "Student added")

        return redirect(request.path)

    return render(
        request,
        "accounts/assign_students.html",
        {
            "academic_class": academic_class,   # ✅ REQUIRED
            "students": students,
            "available_rolls": available_rolls,
        }
    )

@login_required
def import_class_students_excel(request, class_id):
    academic_class = get_object_or_404(AcademicClass, id=class_id)

    if request.user.role != "HOD" or academic_class.department != request.user.department:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST" and request.FILES.get("excel"):
        wb = openpyxl.load_workbook(request.FILES["excel"])
        ws = wb.active

        imported_count = 0
        with transaction.atomic():
            imported_roll_numbers = set()
            for list_order, (roll_no, name) in enumerate(
                ws.iter_rows(min_row=2, values_only=True),
                start=1,
            ):
                if roll_no is None and name is None:
                    continue

                roll_no = "" if roll_no is None else str(roll_no)
                name = "" if name is None else str(name)
                imported_roll_numbers.add(roll_no)

                Student.objects.update_or_create(
                    roll_no=roll_no,
                    academic_class=academic_class,
                    defaults={
                        "name": name,
                        "list_order": list_order,
                        "department": academic_class.department
                    }
                )
                imported_count += 1

            Student.objects.filter(
                academic_class=academic_class
            ).exclude(
                roll_no__in=imported_roll_numbers
            ).delete()

        if not imported_count:
            messages.error(request, "No valid student rows found in the Excel file.")
        else:
            messages.success(
                request,
                f"{imported_count} student(s) imported successfully",
            )

    return redirect("assign_students", academic_class.id)

@login_required
def export_class_students_excel(request, class_id):
    academic_class = get_object_or_404(AcademicClass, id=class_id)

    if request.user.role != "HOD" or academic_class.department != request.user.department:
        return HttpResponse("Unauthorized", status=403)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Students"

    ws.append(["Roll No", "Name"])

    students = (
        Student.objects
        .filter(academic_class=academic_class)
        .order_by("list_order", "pk")
    )

    for s in students:
        ws.append([s.roll_no, s.name])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="students_{academic_class.name}.xlsx"'
    )

    wb.save(response)
    return response


from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import AcademicClass, Course
from django import forms

class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["course_code", "course_name"]  


class DepartmentReportHeaderForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = (
            "report_department_name",
            "report_accreditation",
            "report_email",
            "report_hod_name",
            "report_hod_qualification",
        )
        labels = {
            "report_department_name": "Department name for report",
            "report_accreditation": "Department accreditation",
            "report_email": "Department email",
            "report_hod_name": "HOD name",
            "report_hod_qualification": "HOD qualification",
        }
        widgets = {
            "report_department_name": forms.TextInput(attrs={"placeholder": "Department of Mechanical Engineering"}),
            "report_accreditation": forms.TextInput(attrs={"placeholder": "NBA Accredited"}),
            "report_email": forms.EmailInput(attrs={"placeholder": "department@example.edu"}),
            "report_hod_name": forms.TextInput(attrs={"placeholder": "Dr. Full Name"}),
            "report_hod_qualification": forms.TextInput(attrs={"placeholder": "M.E., Ph.D. (Department)"}),
        }


class CollegeWebsiteForm(forms.ModelForm):
    class Meta:
        model = CollegeReportSettings
        fields = ("website",)
        labels = {"website": "College website"}
        widgets = {
            "website": forms.URLInput(attrs={"placeholder": "https://www.sknscoe.ac.in"}),
        }


@login_required
def create_course(request, class_id):
    academic_class = get_object_or_404(AcademicClass, id=class_id)

    if request.user.role != "HOD" or academic_class.department != request.user.department:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            course.academic_class = academic_class  # 🔥 class-wise link
            course.save()
            return redirect("class_dashboard", class_id=class_id)
    else:
        form = CourseForm()

    return render(
        request,
        "accounts/create_courses.html",
        {
            "form": form,
            "academic_class": academic_class
        }
    )

from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Course

@login_required
def delete_course(request, course_id):
    # Only HOD can delete
    if request.user.role != "HOD":
        return HttpResponseForbidden("Not allowed")

    course = get_object_or_404(
        Course,
        id=course_id,
        academic_class__department=request.user.department
    )

    tool_ids = course.assessment_tools.values_list("id", flat=True)
    has_marks = (
        IcaStudentMarks.objects.filter(tool_id__in=tool_ids).exists()
        or AssignmentTutorialMarks.objects.filter(tool_id__in=tool_ids).exists()
        or ExamMarks.objects.filter(tool_id__in=tool_ids).exists()
        or UniversityExamMarks.objects.filter(tool_id__in=tool_ids).exists()
    )
    if has_marks:
        messages.error(
            request,
            "This course has saved student marks and cannot be deleted.",
        )
        return redirect("class_dashboard", class_id=course.academic_class_id)

    class_id = course.academic_class.id
    course.delete()

    return redirect("class_dashboard", class_id=class_id)


@login_required
def class_dashboard(request, class_id):
    if request.user.role != "HOD" or not request.user.department:
        return HttpResponseForbidden("Access denied")

    academic_class = get_object_or_404(
        AcademicClass,
        id=class_id,
        department=request.user.department
    )

    courses = academic_class.courses.select_related("faculty").all()

    return render(
        request,
        "accounts/class_dashboard.html",
        {
            "academic_class": academic_class,
            "courses": courses
        }
    )


@login_required
def class_po_pso_attainment(request, class_id):
    if request.user.role != "HOD" or not request.user.department:
        return HttpResponseForbidden("Access denied")

    academic_class = get_object_or_404(
        AcademicClass,
        id=class_id,
        department=request.user.department,
    )
    courses = list(
        Course.objects.filter(academic_class=academic_class)
        .order_by("course_code")
    )

    outcome_by_key = {}
    course_mapping_data = []
    for course in courses:
        mapping_rows, pos, psos = _course_mapping_grades(course)
        outcome_keys = [
            *(("po", outcome.id) for outcome in pos),
            *(("pso", outcome.id) for outcome in psos),
        ]
        for outcome in pos:
            outcome_by_key[("po", outcome.id)] = outcome
        for outcome in psos:
            outcome_by_key[("pso", outcome.id)] = outcome

        grades_by_outcome = defaultdict(list)
        for mapping_row in mapping_rows:
            for outcome_key, entry in zip(
                outcome_keys,
                mapping_row["entries"],
            ):
                if entry["grade"] is not None:
                    grades_by_outcome[outcome_key].append(entry["grade"])

        course_mapping_data.append((course, grades_by_outcome))

    def outcome_sort_key(outcome_key):
        kind, _ = outcome_key
        outcome = outcome_by_key[outcome_key]
        field_name = "po_number" if kind == "po" else "pso_number"
        label = getattr(outcome, field_name)
        number = re.search(r"\d+", label)
        return (
            0 if kind == "po" else 1,
            int(number.group()) if number else float("inf"),
            label,
        )

    outcome_keys = sorted(outcome_by_key, key=outcome_sort_key)
    outcome_columns = [
        {
            "key": f"{kind}-{outcome_id}",
            "label": getattr(
                outcome_by_key[(kind, outcome_id)],
                "po_number" if kind == "po" else "pso_number",
            ),
        }
        for kind, outcome_id in outcome_keys
    ]
    subject_rows = []
    for index, (course, grades_by_outcome) in enumerate(course_mapping_data, 1):
        cells = []
        for outcome_key in outcome_keys:
            grades = grades_by_outcome[outcome_key]
            if not grades:
                cells.append("")
                continue
            average = sum(grades) / len(grades)
            cells.append(
                int(average) if average.is_integer() else round(average, 2)
            )
        subject_rows.append({
            "serial_number": index,
            "course": course,
            "cells": cells,
        })

    if request.GET.get("export") == "excel":
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "PO-PSO Attainment"
        column_count = max(4, len(outcome_columns) + 3)
        worksheet.merge_cells(
            start_row=1,
            start_column=1,
            end_row=1,
            end_column=column_count,
        )
        title_cell = worksheet.cell(
            row=1,
            column=1,
            value="DIRECT ATTAINMENT OF PO-PSOS",
        )
        title_cell.font = Font(name="Aptos Display", size=16, bold=True, color="17243B")
        title_cell.fill = PatternFill("solid", fgColor="F4C9AD")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.row_dimensions[1].height = 30

        worksheet.merge_cells(
            start_row=2,
            start_column=1,
            end_row=2,
            end_column=column_count,
        )
        class_cell = worksheet.cell(
            row=2,
            column=1,
            value=(
                f"{academic_class.name} | Semester {academic_class.semester} | "
                f"Academic year {academic_class.academic_year}"
            ),
        )
        class_cell.font = Font(name="Aptos", size=10, color="56657D")
        class_cell.alignment = Alignment(horizontal="left", vertical="center")
        worksheet.row_dimensions[2].height = 22

        headers = ["SR.NO", "Course Code", "Course Name"] + [
            outcome["label"] for outcome in outcome_columns
        ]
        if not outcome_columns:
            headers.append("PO/PSO outcomes not configured")
        for column_index, label in enumerate(headers, 1):
            cell = worksheet.cell(row=4, column=column_index, value=label)
            cell.font = Font(name="Aptos", bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="245EEA")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.row_dimensions[4].height = 24

        thin_blue = Side(style="thin", color="DCE3EE")
        cell_border = Border(
            left=thin_blue,
            right=thin_blue,
            top=thin_blue,
            bottom=thin_blue,
        )
        for row_index, row in enumerate(subject_rows, 5):
            values = [
                row["serial_number"],
                row["course"].course_code,
                row["course"].course_name,
                *row["cells"],
            ]
            if not outcome_columns:
                values.append("")
            for column_index, value in enumerate(values, 1):
                cell = worksheet.cell(row=row_index, column=column_index)
                cell.value = value
                if isinstance(value, str):
                    cell.data_type = "s"
                cell.font = Font(name="Aptos", size=10, color="17243B")
                cell.fill = PatternFill(
                    "solid",
                    fgColor="F7F9FC" if row_index % 2 == 0 else "FFFFFF",
                )
                cell.alignment = Alignment(
                    horizontal="left" if column_index == 3 else "center",
                    vertical="center",
                )
                cell.border = cell_border
            worksheet.row_dimensions[row_index].height = 22

        widths = [9, 20, 34] + [12] * len(outcome_columns)
        if not outcome_columns:
            widths.append(32)
        for column_index, width in enumerate(widths, 1):
            worksheet.column_dimensions[
                openpyxl.utils.get_column_letter(column_index)
            ].width = width
        worksheet.freeze_panes = "D5"
        worksheet.auto_filter.ref = (
            f"A4:{openpyxl.utils.get_column_letter(column_count)}"
            f"{max(4, len(subject_rows) + 4)}"
        )

        response = HttpResponse(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )
        safe_class_name = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            academic_class.name,
        ).strip("-")
        response["Content-Disposition"] = (
            f'attachment; filename="PO-PSO-Attainment-{safe_class_name}.xlsx"'
        )
        workbook.save(response)
        return response

    return render(
        request,
        "accounts/class_po_pso_attainment.html",
        {
            "academic_class": academic_class,
            "subject_rows": subject_rows,
            "outcome_columns": outcome_columns,
        },
    )


@login_required
def class_po_pso_average(request, class_id):
    if request.user.role != "HOD" or not request.user.department:
        return HttpResponseForbidden("Access denied")

    academic_class = get_object_or_404(
        AcademicClass,
        id=class_id,
        department=request.user.department,
    )
    courses = list(
        Course.objects.filter(academic_class=academic_class)
        .order_by("course_code")
    )

    outcome_by_key = {}
    course_average_data = []
    for course in courses:
        mapping_rows, pos, psos = _course_mapping_grades(course)
        outcome_keys = [
            *(("po", outcome.id) for outcome in pos),
            *(("pso", outcome.id) for outcome in psos),
        ]
        for outcome in pos:
            outcome_by_key[("po", outcome.id)] = outcome
        for outcome in psos:
            outcome_by_key[("pso", outcome.id)] = outcome

        grades_by_outcome = defaultdict(list)
        for mapping_row in mapping_rows:
            for outcome_key, entry in zip(
                outcome_keys,
                mapping_row["entries"],
            ):
                if entry["grade"] is not None:
                    grades_by_outcome[outcome_key].append(entry["grade"])

        course_average_data.append((course, grades_by_outcome))

    def outcome_sort_key(outcome_key):
        kind, _ = outcome_key
        outcome = outcome_by_key[outcome_key]
        field_name = "po_number" if kind == "po" else "pso_number"
        label = getattr(outcome, field_name)
        number = re.search(r"\d+", label)
        return (
            0 if kind == "po" else 1,
            int(number.group()) if number else float("inf"),
            label,
        )

    outcome_keys = sorted(outcome_by_key, key=outcome_sort_key)
    outcome_columns = [
        {
            "label": getattr(
                outcome_by_key[(kind, outcome_id)],
                "po_number" if kind == "po" else "pso_number",
            ),
        }
        for kind, outcome_id in outcome_keys
    ]
    subject_rows = []
    for index, (course, grades_by_outcome) in enumerate(course_average_data, 1):
        averages = []
        for outcome_key in outcome_keys:
            grades = grades_by_outcome[outcome_key]
            if not grades:
                averages.append(0)
                continue
            average = sum(grades) / len(grades)
            averages.append(
                int(average) if average.is_integer() else round(average, 2)
            )
        subject_rows.append({
            "serial_number": index,
            "course": course,
            "averages": averages,
        })

    if request.GET.get("export") == "excel":
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "PO-PSO Average"
        column_count = max(4, len(outcome_columns) + 3)
        worksheet.merge_cells(
            start_row=1,
            start_column=1,
            end_row=1,
            end_column=column_count,
        )
        title_cell = worksheet.cell(
            row=1,
            column=1,
            value="COURSE ARTICULATION MATRIX (PO & PSO MAPPING)",
        )
        title_cell.font = Font(name="Aptos Display", size=16, bold=True, color="17243B")
        title_cell.fill = PatternFill("solid", fgColor="F4C9AD")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.row_dimensions[1].height = 30

        worksheet.merge_cells(
            start_row=2,
            start_column=1,
            end_row=2,
            end_column=column_count,
        )
        class_cell = worksheet.cell(
            row=2,
            column=1,
            value=(
                f"{academic_class.name} | Semester {academic_class.semester} | "
                f"Academic year {academic_class.academic_year}"
            ),
        )
        class_cell.font = Font(name="Aptos", size=10, color="56657D")
        class_cell.alignment = Alignment(horizontal="left", vertical="center")
        worksheet.row_dimensions[2].height = 22

        headers = ["SR.NO", "Course Code", "Course Name"] + [
            outcome["label"] for outcome in outcome_columns
        ]
        if not outcome_columns:
            headers.append("PO/PSO outcomes not configured")
        for column_index, label in enumerate(headers, 1):
            cell = worksheet.cell(row=4, column=column_index, value=label)
            cell.font = Font(name="Aptos", bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="245EEA")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.row_dimensions[4].height = 24

        thin_blue = Side(style="thin", color="DCE3EE")
        cell_border = Border(
            left=thin_blue,
            right=thin_blue,
            top=thin_blue,
            bottom=thin_blue,
        )
        for row_index, row in enumerate(subject_rows, 5):
            values = [
                row["serial_number"],
                row["course"].course_code,
                row["course"].course_name,
                *row["averages"],
            ]
            if not outcome_columns:
                values.append("")
            for column_index, value in enumerate(values, 1):
                cell = worksheet.cell(row=row_index, column=column_index)
                cell.value = value
                if isinstance(value, str):
                    cell.data_type = "s"
                cell.font = Font(name="Aptos", size=10, color="17243B")
                cell.fill = PatternFill(
                    "solid",
                    fgColor="F7F9FC" if row_index % 2 == 0 else "FFFFFF",
                )
                cell.alignment = Alignment(
                    horizontal="left" if column_index == 3 else "center",
                    vertical="center",
                )
                cell.border = cell_border
            worksheet.row_dimensions[row_index].height = 22

        widths = [9, 20, 34] + [12] * len(outcome_columns)
        if not outcome_columns:
            widths.append(32)
        for column_index, width in enumerate(widths, 1):
            worksheet.column_dimensions[
                openpyxl.utils.get_column_letter(column_index)
            ].width = width
        worksheet.freeze_panes = "D5"
        worksheet.auto_filter.ref = (
            f"A4:{openpyxl.utils.get_column_letter(column_count)}"
            f"{max(4, len(subject_rows) + 4)}"
        )

        response = HttpResponse(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )
        safe_class_name = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            academic_class.name,
        ).strip("-")
        response["Content-Disposition"] = (
            f'attachment; filename="PO-PSO-Average-{safe_class_name}.xlsx"'
        )
        workbook.save(response)
        return response

    return render(
        request,
        "accounts/class_po_pso_average.html",
        {
            "academic_class": academic_class,
            "subject_rows": subject_rows,
            "outcome_columns": outcome_columns,
        },
    )


@login_required
def class_weighted_co_levels(request, class_id):
    if request.user.role != "HOD" or not request.user.department:
        return HttpResponseForbidden("Access denied")

    academic_class = get_object_or_404(
        AcademicClass,
        id=class_id,
        department=request.user.department,
    )
    courses = list(
        Course.objects.filter(academic_class=academic_class)
        .order_by("course_code")
    )
    course_levels = []
    co_numbers = set()

    for course in courses:
        attainment_rows = co_attainment_sheet(
            request,
            course.id,
            return_attainment_rows=True,
        )
        levels_by_co = {
            row["co"]: row["weighted_level"]
            for row in attainment_rows
        }
        for co_key in levels_by_co:
            co_match = re.fullmatch(r"CO(\d+)", co_key)
            if co_match:
                co_numbers.add(int(co_match.group(1)))
        course_levels.append((course, levels_by_co))

    co_columns = sorted(co_numbers)
    subject_rows = [
        {
            "serial_number": index,
            "course": course,
            "levels": [
                levels_by_co.get(f"CO{co_number}", "")
                for co_number in co_columns
            ],
        }
        for index, (course, levels_by_co) in enumerate(course_levels, 1)
    ]

    if request.GET.get("export") == "excel":
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "Weighted CO Levels"
        column_count = max(4, len(co_columns) + 3)
        worksheet.merge_cells(
            start_row=1,
            start_column=1,
            end_row=1,
            end_column=column_count,
        )
        title_cell = worksheet.cell(
            row=1,
            column=1,
            value="LEVEL OF WEIGHTED CO",
        )
        title_cell.font = Font(name="Aptos Display", size=16, bold=True, color="17243B")
        title_cell.fill = PatternFill("solid", fgColor="F4C9AD")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.row_dimensions[1].height = 30

        worksheet.merge_cells(
            start_row=2,
            start_column=1,
            end_row=2,
            end_column=column_count,
        )
        class_cell = worksheet.cell(
            row=2,
            column=1,
            value=(
                f"{academic_class.name} | Semester {academic_class.semester} | "
                f"Academic year {academic_class.academic_year}"
            ),
        )
        class_cell.font = Font(name="Aptos", size=10, color="56657D")
        class_cell.alignment = Alignment(horizontal="left", vertical="center")
        worksheet.row_dimensions[2].height = 22

        headers = ["SR.NO", "Course Code", "Course Name"] + [
            f"CO{co_number}" for co_number in co_columns
        ]
        if not co_columns:
            headers.append("COs not configured")
        for column_index, label in enumerate(headers, 1):
            cell = worksheet.cell(row=4, column=column_index, value=label)
            cell.font = Font(name="Aptos", bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="245EEA")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.row_dimensions[4].height = 24

        thin_blue = Side(style="thin", color="DCE3EE")
        cell_border = Border(
            left=thin_blue,
            right=thin_blue,
            top=thin_blue,
            bottom=thin_blue,
        )
        for row_index, row in enumerate(subject_rows, 5):
            values = [
                row["serial_number"],
                row["course"].course_code,
                row["course"].course_name,
                *[
                    level if level != "" else "-"
                    for level in row["levels"]
                ],
            ]
            if not co_columns:
                values.append("")
            for column_index, value in enumerate(values, 1):
                cell = worksheet.cell(row=row_index, column=column_index)
                cell.value = value
                if isinstance(value, str):
                    cell.data_type = "s"
                cell.font = Font(name="Aptos", size=10, color="17243B")
                cell.fill = PatternFill(
                    "solid",
                    fgColor="F7F9FC" if row_index % 2 == 0 else "FFFFFF",
                )
                cell.alignment = Alignment(
                    horizontal="left" if column_index == 3 else "center",
                    vertical="center",
                )
                cell.border = cell_border
            worksheet.row_dimensions[row_index].height = 22

        widths = [9, 20, 34] + [12] * len(co_columns)
        if not co_columns:
            widths.append(24)
        for column_index, width in enumerate(widths, 1):
            worksheet.column_dimensions[
                openpyxl.utils.get_column_letter(column_index)
            ].width = width
        worksheet.freeze_panes = "D5"
        worksheet.auto_filter.ref = (
            f"A4:{openpyxl.utils.get_column_letter(column_count)}"
            f"{max(4, len(subject_rows) + 4)}"
        )

        response = HttpResponse(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )
        safe_class_name = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            academic_class.name,
        ).strip("-")
        response["Content-Disposition"] = (
            f'attachment; filename="Weighted-CO-Levels-{safe_class_name}.xlsx"'
        )
        workbook.save(response)
        return response

    return render(
        request,
        "accounts/class_weighted_co_levels.html",
        {
            "academic_class": academic_class,
            "subject_rows": subject_rows,
            "co_columns": [f"CO{co_number}" for co_number in co_columns],
        },
    )


@login_required
def class_co_gap_quality_report(request, class_id):
    if request.user.role != "HOD" or not request.user.department:
        return HttpResponseForbidden("Access denied")

    academic_class = get_object_or_404(
        AcademicClass,
        id=class_id,
        department=request.user.department,
    )
    department = academic_class.department
    department_name = (
        department.report_department_name.strip()
        or f"Department of {department.name}"
    )
    courses = Course.objects.filter(
        academic_class=academic_class
    ).order_by("course_code")
    course_reports = []
    for course in courses:
        report_data = co_attainment_sheet(
            request,
            course.id,
            report_type="gap",
            return_report_context=True,
        )
        if isinstance(report_data, HttpResponse):
            return report_data
        course_reports.append({
            "course": course,
            "gap_rows": report_data["gap_rows"],
        })
    college_settings, _ = CollegeReportSettings.objects.get_or_create(pk=1)

    if request.GET.get("download") == "docx":
        from docx import Document
        from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Inches, Pt, RGBColor

        document = Document()
        section = document.sections[0]
        section.page_width = Inches(8.27)
        section.page_height = Inches(11.69)
        section.top_margin = Inches(2.45)
        section.bottom_margin = Inches(0.45)
        section.left_margin = Inches(0.42)
        section.right_margin = Inches(0.42)
        section.header_distance = Inches(0.12)
        section.footer_distance = Inches(0.2)
        document.styles["Normal"].font.name = "Times New Roman"
        document.styles["Normal"].font.size = Pt(8)

        def shade_cell(cell, color):
            properties = cell._tc.get_or_add_tcPr()
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), color)
            properties.append(shading)

        def set_cell(cell, value, *, bold=False, fill=None, size=7.5):
            cell.text = "" if value is None else str(value)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if fill:
                shade_cell(cell, fill)
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.paragraph_format.space_before = Pt(1)
                paragraph.paragraph_format.space_after = Pt(1)
                for run in paragraph.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(size)
                    run.font.bold = bold

        def add_table(headers, rows, widths):
            table = document.add_table(rows=1, cols=len(headers))
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            for index, (header, width) in enumerate(zip(headers, widths)):
                table.columns[index].width = Inches(width)
                table.rows[0].cells[index].width = Inches(width)
                set_cell(
                    table.rows[0].cells[index],
                    header,
                    bold=True,
                    fill="DCE8D5",
                    size=7,
                )
            header_properties = table.rows[0]._tr.get_or_add_trPr()
            repeat_header = OxmlElement("w:tblHeader")
            repeat_header.set(qn("w:val"), "true")
            header_properties.append(repeat_header)
            for row_values in rows:
                cells = table.add_row().cells
                for index, (cell, value, width) in enumerate(
                    zip(cells, row_values, widths)
                ):
                    cell.width = Inches(width)
                    set_cell(
                        cell,
                        value,
                        bold=index == 0,
                        fill=(
                            "E9F5E4"
                            if index == len(headers) - 1 and index > 0
                            else None
                        ),
                        size=7.5,
                    )
            return table

        header = section.header
        header_table = header.add_table(rows=1, cols=2, width=Inches(7.43))
        header_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        header_table.autofit = False
        header_table.columns[0].width = Inches(1.3)
        header_table.columns[1].width = Inches(6.13)
        header_table.cell(0, 0).width = Inches(1.3)
        header_table.cell(0, 1).width = Inches(6.13)
        header_table.cell(0, 0).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        header_table.cell(0, 1).vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        logo_path = (
            Path(__file__).resolve().parent
            / "static"
            / "accounts"
            / "images"
            / "spspm-logo.png"
        )
        logo_paragraph = header_table.cell(0, 0).paragraphs[0]
        logo_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if logo_path.is_file():
            logo_paragraph.add_run().add_picture(str(logo_path), width=Inches(1.05))
        header_text = header_table.cell(0, 1)
        header_lines = [
            ("Savitribai Phule Shikshan Prasarak Mandal’s", 11, "000000"),
            ("SKN SINHGAD COLLEGE OF ENGINEERING", 20, "CC0000"),
            ("(Approved by AICTE & Affiliated to PAH Solapur University, Solapur)", 10, "000000"),
            ("Accredited with ‘A+’ Grade by NAAC", 11, "CC0000"),
            ("A/p- Korti, Tal- Pandharpur, Pin- 413304, Dist.- Solapur.", 10, "000000"),
            (department_name, 18, "CC0000"),
        ]
        if department.report_accreditation:
            header_lines.append((department.report_accreditation, 11, "CC0000"))
        for line_index, (text, size, color) in enumerate(header_lines):
            paragraph = (
                header_text.paragraphs[0]
                if line_index == 0
                else header_text.add_paragraph()
            )
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = 1
            run = paragraph.add_run(text)
            run.font.name = "Arial"
            run.font.size = Pt(size)
            run.font.bold = True
            run.font.color.rgb = RGBColor.from_string(color)
        contact_details = []
        if department.report_email:
            contact_details.extend(
                (
                    ("e-mail: ", RGBColor(0, 0, 0), True, False),
                    (department.report_email, RGBColor(5, 99, 193), False, True),
                )
            )
        if college_settings and college_settings.website:
            if contact_details:
                contact_details.append(("   ", RGBColor(0, 0, 0), False, False))
            contact_details.extend(
                (
                    ("Website: ", RGBColor(0, 0, 0), True, False),
                    (college_settings.website, RGBColor(5, 99, 193), False, True),
                )
            )
        if contact_details:
            paragraph = header_text.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            for text, color, bold, underline in contact_details:
                run = paragraph.add_run(text)
                run.font.name = "Arial"
                run.font.size = Pt(10)
                run.font.bold = bold
                run.font.color.rgb = color
                run.underline = underline
        separator = header.add_paragraph()
        separator.paragraph_format.space_before = Pt(0)
        separator.paragraph_format.space_after = Pt(3)
        separator.paragraph_format.line_spacing = Pt(1)
        paragraph_borders = OxmlElement("w:pBdr")
        bottom_border = OxmlElement("w:bottom")
        bottom_border.set(qn("w:val"), "single")
        bottom_border.set(qn("w:sz"), "18")
        bottom_border.set(qn("w:color"), "000000")
        paragraph_borders.append(bottom_border)
        separator._p.get_or_add_pPr().append(paragraph_borders)
        officials_table = header.add_table(rows=1, cols=2, width=Inches(7.43))
        officials_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        officials_table.autofit = False
        officials_table.columns[0].width = Inches(3.715)
        officials_table.columns[1].width = Inches(3.715)
        official_details = (
            ("Dr. K. J. Karande", "M. Tech., Ph.D. (E&TC Engg.)", "PRINCIPAL"),
            (
                department.report_hod_name or "HOD",
                department.report_hod_qualification,
                "HOD",
            ),
        )
        for column, details in enumerate(official_details):
            official_cell = officials_table.cell(0, column)
            official_cell.width = Inches(3.715)
            official_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for row_index, detail in enumerate(details):
                paragraph = (
                    official_cell.paragraphs[0]
                    if row_index == 0
                    else official_cell.add_paragraph()
                )
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                run = paragraph.add_run(detail)
                run.font.name = "Times New Roman"
                run.font.size = Pt(11 if row_index == 1 else 12)
                run.font.bold = row_index != 1
                run.font.color.rgb = (
                    RGBColor(204, 0, 0)
                    if row_index == 0
                    else RGBColor(0, 0, 0)
                )
        official_borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            border = OxmlElement(f"w:{edge}")
            border.set(qn("w:val"), "single" if edge == "bottom" else "nil")
            if edge == "bottom":
                border.set(qn("w:sz"), "18")
                border.set(qn("w:color"), "000000")
            official_borders.append(border)
        officials_table._tbl.tblPr.append(official_borders)

        if not course_reports:
            empty_report = document.add_paragraph("No courses are available for this class.")
            empty_report.alignment = WD_ALIGN_PARAGRAPH.CENTER

        for index, report in enumerate(course_reports):
            if index:
                document.add_page_break()

            title = document.add_paragraph()
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER
            title.paragraph_format.space_before = Pt(0)
            title.paragraph_format.space_after = Pt(4)
            title_run = title.add_run("CO Attainment Gap")
            title_run.font.name = "Times New Roman"
            title_run.font.size = Pt(11)
            title_run.font.bold = True

            course = report["course"]
            info_table = document.add_table(rows=2, cols=2)
            info_table.style = "Table Grid"
            info_table.autofit = False
            info_table.columns[0].width = Inches(3.71)
            info_table.columns[1].width = Inches(3.71)
            info_values = (
                (f"Subject: {course.course_name}", f"A.Y.: {academic_class.academic_year}"),
                (f"Subject Code: {course.course_code}", f"Semester: {academic_class.semester}"),
            )
            for row_index, values in enumerate(info_values):
                for column_index, value in enumerate(values):
                    cell = info_table.cell(row_index, column_index)
                    cell.width = Inches(3.71)
                    set_cell(
                        cell,
                        value,
                        bold=True,
                        fill="F4F7FC",
                        size=7.5,
                    )

            gap_rows = report["gap_rows"]
            document.add_paragraph().paragraph_format.space_after = Pt(1)
            add_table(
                (
                    "CO's",
                    "Target %",
                    "CO Attainment %",
                    "Attainment Gap\n(Target - Attainment) %",
                    "Focus",
                ),
                [
                    (
                        row["co"],
                        row["target"] if row["target"] is not None else "Not set",
                        row["attainment"],
                        row["gap"] if row["gap"] is not None else "—",
                        row["focus"],
                    )
                    for row in gap_rows
                ] or [("No COs configured", "", "", "", "")],
                (0.62, 0.82, 0.95, 1.55, 3.49),
            )

            heading = document.add_paragraph()
            heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
            heading.paragraph_format.space_before = Pt(5)
            heading.paragraph_format.space_after = Pt(3)
            heading_run = heading.add_run("Closure of Quality Loop")
            heading_run.font.name = "Times New Roman"
            heading_run.font.size = Pt(9)
            heading_run.font.bold = True
            add_table(
                (
                    "CO's",
                    "Target %",
                    "CO Attainment Gap\n(Target - Attainment) %",
                    "Action Proposed to Bridge Gap",
                    "Modifications of Target",
                ),
                [
                    (
                        row["co"],
                        row["target"] if row["target"] is not None else "Not set",
                        row["gap"] if row["gap"] is not None else "—",
                        row["action_proposed"] or "No action recorded",
                        row["target_modification"] or "No target change recorded",
                    )
                    for row in gap_rows
                ] or [("No COs configured", "", "", "", "")],
                (0.62, 0.82, 1.2, 2.45, 2.34),
            )

            signature_spacer = document.add_paragraph()
            signature_spacer.paragraph_format.space_before = Pt(8)
            signature_spacer.paragraph_format.space_after = Pt(2)
            signature_spacer.paragraph_format.line_spacing = Pt(8)
            teacher_name = (
                course.faculty.get_full_name() or course.faculty.username
                if course.faculty
                else "Not assigned"
            )
            signature_table = document.add_table(rows=2, cols=3)
            signature_table.style = "Table Grid"
            signature_table.alignment = WD_TABLE_ALIGNMENT.LEFT
            signature_table.autofit = False
            signature_widths = (0.65, 2.05, 1.0)
            for column_index, width in enumerate(signature_widths):
                signature_table.columns[column_index].width = Inches(width)
            for column_index, label in enumerate(("Sr.No.", "Name of Subject Teacher", "Sign")):
                cell = signature_table.cell(0, column_index)
                cell.width = Inches(signature_widths[column_index])
                set_cell(cell, label, bold=True, fill="F4F7FC", size=7)
            for column_index, value in enumerate(("1.", teacher_name, "")):
                cell = signature_table.cell(1, column_index)
                cell.width = Inches(signature_widths[column_index])
                set_cell(cell, value, size=7.5)

        buffer = io.BytesIO()
        document.save(buffer)
        safe_class_name = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            academic_class.name,
        ).strip("-")
        response = HttpResponse(
            buffer.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )
        response["Content-Disposition"] = (
            f'attachment; filename="CO-Gap-Quality-Loop-{safe_class_name}.docx"'
        )
        return response

    return render(
        request,
        "accounts/class_co_gap_quality_report.html",
        {
            "academic_class": academic_class,
            "department_name": department_name,
            "course_reports": course_reports,
            "college_settings": college_settings,
        },
    )


from django.http import HttpResponseForbidden
from django.contrib.auth import get_user_model

User = get_user_model()

@login_required
def assign_course_teacher(request, course_id):
    # Only HOD can assign
    if request.user.role != "HOD":
        return HttpResponseForbidden("Not allowed")

    course = get_object_or_404(
        Course,
        id=course_id,
        academic_class__department=request.user.department
    )

    # Faculty/HOD list (same department)
    teachers = User.objects.filter(
        role__in=["FACULTY", "HOD"],
        department=request.user.department
    ).order_by("role", "first_name", "last_name", "username")

    if request.method == "POST":
        teacher_id = request.POST.get("teacher")
        teacher = get_object_or_404(teachers, id=teacher_id)
        course.faculty = teacher
        course.save()

        return redirect(
            "class_dashboard",
            class_id=course.academic_class.id
        )

    return render(
        request,
        "accounts/assign_course_teacher.html",
        {
            "course": course,
            "teachers": teachers
        }
    )


from django.db.models import Avg, IntegerField
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

@login_required
def view_course(request, course_id):

    course = get_object_or_404(Course, id=course_id)
    if request.user.role == "FACULTY" and course.faculty != request.user:
        return HttpResponseForbidden("Not allowed")
    if request.user.role == "HOD" and course.academic_class.department != request.user.department:
        return HttpResponseForbidden("Not allowed")

    cos = list(course.cos.order_by("co_number"))

    academic_class = course.academic_class

    mapping_rows, pos, psos = _course_mapping_grades(
        course,
        cos=cos,
        persist=True,
    )

    # ================= BUILD MATRIX TABLE =================

    matrix_rows = [
        {
            "co": row["co"],
            "cells": [
                entry["grade"] if entry["grade"] is not None else "-"
                for entry in row["entries"]
            ],
        }
        for row in mapping_rows
    ]

    # ================= COLUMN AVERAGE =================

    averages = []

    for po in pos:
        avg = COPOMapping.objects.filter(
            po=po, co__in=cos
        ).aggregate(Avg("level"))["level__avg"]
        averages.append(round(avg, 2) if avg else 0)

    for pso in psos:
        avg = COPSOMapping.objects.filter(
            pso=pso, co__in=cos
        ).aggregate(Avg("level"))["level__avg"]
        averages.append(round(avg, 2) if avg else 0)
    tools = AssessmentTool.objects.filter(course=course).order_by('created_at')
    return render(request, "accounts/view_course.html", {
        "course": course,
        "pos": pos,
        "psos": psos,
        "matrix_rows": matrix_rows,
        "averages": averages,
        "tools": tools,
        "class_id": academic_class.id
    })
@login_required
def manage_co(request, course_id):

    course = get_object_or_404(Course, id=course_id)

    # Only the assigned teacher can edit COs. The assignee can be Faculty or HOD.
    if request.user != course.faculty:
        return HttpResponseForbidden("You are not allowed to edit CO.")

    cos = course.cos.all()

    if request.method == "POST":
        co_count = int(request.POST.get("co_count", 0))

        with transaction.atomic():
            for i in range(1, co_count + 1):
                desc = request.POST.get(f"co_desc_{i}", "").strip()
                if desc:
                    CourseOutcome.objects.update_or_create(
                        course=course,
                        co_number=i,
                        defaults={"description": desc},
                    )

        return redirect("view_course", course_id=course.id)

    return render(request, "accounts/manage_co.html", {
        "course": course,
        "cos": cos,
        "co_count": cos.count(),
    })

from django.db.models import Avg
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect


def _course_mapping_outcomes(course):
    academic_class = course.academic_class
    department = (
        academic_class.mapped_department
        if academic_class.department.is_general_science
        else academic_class.department
    )
    def numeric_outcome_order(outcome, field_name):
        label = getattr(outcome, field_name)
        number = re.search(r"\d+", label)
        return (
            int(number.group()) if number else float("inf"),
            label,
        )

    pos = list(ProgramOutcome.objects.filter(department=department))
    psos = list(ProgramSpecificOutcome.objects.filter(department=department))
    pos.sort(key=lambda po: numeric_outcome_order(po, "po_number"))
    psos.sort(key=lambda pso: numeric_outcome_order(pso, "pso_number"))
    return pos, psos


def _course_mapping_grades(course, cos=None, pos=None, psos=None, persist=False):
    cos = list(cos if cos is not None else course.cos.order_by("co_number"))
    if pos is None or psos is None:
        course_pos, course_psos = _course_mapping_outcomes(course)
        pos = course_pos if pos is None else list(pos)
        psos = course_psos if psos is None else list(psos)
    else:
        pos = list(pos)
        psos = list(psos)

    indicators = CoursePerformanceIndicator.objects.filter(
        course=course
    ).prefetch_related("course_outcomes")
    po_tpi = defaultdict(int)
    pso_tpi = defaultdict(int)
    po_mpi = defaultdict(int)
    pso_mpi = defaultdict(int)

    for indicator in indicators:
        co_ids = [co.id for co in indicator.course_outcomes.all()]
        if indicator.po_id:
            po_tpi[indicator.po_id] += 1
            for co_id in co_ids:
                po_mpi[(co_id, indicator.po_id)] += 1
        elif indicator.pso_id:
            pso_tpi[indicator.pso_id] += 1
            for co_id in co_ids:
                pso_mpi[(co_id, indicator.pso_id)] += 1

    def make_entry(tpi, mpi):
        raw_percentage = mpi * 100 / tpi if tpi else 0
        percentage = round(raw_percentage, 2)
        if raw_percentage >= 70:
            grade = 3
        elif raw_percentage >= 40:
            grade = 2
        elif raw_percentage > 0:
            grade = 1
        else:
            grade = None
        return {
            "tpi": tpi,
            "mpi": mpi,
            "percentage": percentage,
            "grade": grade,
        }

    grade_rows = []
    po_mappings = []
    pso_mappings = []
    for co in cos:
        entries = []
        for po in pos:
            entry = make_entry(po_tpi[po.id], po_mpi[(co.id, po.id)])
            entries.append(entry)
            if entry["grade"] is not None:
                po_mappings.append(
                    COPOMapping(co=co, po=po, level=entry["grade"])
                )
        for pso in psos:
            entry = make_entry(pso_tpi[pso.id], pso_mpi[(co.id, pso.id)])
            entries.append(entry)
            if entry["grade"] is not None:
                pso_mappings.append(
                    COPSOMapping(co=co, pso=pso, level=entry["grade"])
                )
        grade_rows.append({"co": co, "entries": entries})

    if persist:
        with transaction.atomic():
            COPOMapping.objects.filter(co__course=course).delete()
            COPSOMapping.objects.filter(co__course=course).delete()
            COPOMapping.objects.bulk_create(po_mappings)
            COPSOMapping.objects.bulk_create(pso_mappings)

    return grade_rows, pos, psos


@login_required
def course_performance_indicators(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if request.user.role == "FACULTY" and course.faculty != request.user:
        return HttpResponseForbidden("Not allowed")
    if request.user.role == "HOD" and course.academic_class.department != request.user.department:
        return HttpResponseForbidden("Not allowed")
    if request.user.role not in ("FACULTY", "HOD"):
        return HttpResponseForbidden("Not allowed")
    cos = list(course.cos.order_by("co_number"))
    pos, psos = _course_mapping_outcomes(course)
    allowed_po_ids = {po.id for po in pos}
    allowed_pso_ids = {pso.id for pso in psos}
    allowed_co_ids = {co.id for co in cos}

    if request.method == "POST":
        submitted_rows = []
        invalid = False

        def read_count(field_name, maximum):
            nonlocal invalid
            value = request.POST.get(field_name, "")
            if not value.isdigit() or int(value) > maximum:
                invalid = True
                return 0
            return int(value)

        outcome_groups = [
            (
                "po",
                po.id,
                allowed_po_ids,
                int(re.search(r"\d+", po.po_number).group())
                if re.search(r"\d+", po.po_number)
                else index,
            )
            for index, po in enumerate(pos, start=1)
        ] + [
            (
                "pso",
                pso.id,
                allowed_pso_ids,
                int(re.search(r"\d+", pso.pso_number).group())
                if re.search(r"\d+", pso.pso_number)
                else index,
            )
            for index, pso in enumerate(psos, start=1)
        ]
        total_indicators = 0

        for outcome_type, outcome_id, allowed_ids, outcome_number in outcome_groups:
            if outcome_id not in allowed_ids:
                invalid = True
                break
            prefix = f"{outcome_type}_{outcome_id}"
            competency_count = read_count(
                f"{prefix}_competency_count", 50
            )
            for competency_index in range(1, competency_count + 1):
                competency_prefix = f"{prefix}_comp_{competency_index}"
                competency_description = request.POST.get(
                    f"{competency_prefix}_description", ""
                ).strip()
                indicator_count = read_count(
                    f"{competency_prefix}_indicator_count", 50
                )
                total_indicators += indicator_count
                if (
                    not competency_description
                    or total_indicators > 500
                ):
                    invalid = True
                    break

                for indicator_index in range(1, indicator_count + 1):
                    indicator_prefix = (
                        f"{competency_prefix}_pi_{indicator_index}"
                    )
                    indicator_description = request.POST.get(
                        f"{indicator_prefix}_description", ""
                    ).strip()
                    co_ids = []
                    for co_id in allowed_co_ids:
                        mapping_value = request.POST.get(
                            f"{indicator_prefix}_co_{co_id}", ""
                        )
                        if mapping_value == "1":
                            co_ids.append(co_id)
                        elif mapping_value != "":
                            invalid = True
                    if not indicator_description:
                        invalid = True
                        break
                    submitted_rows.append({
                        "outcome_type": outcome_type,
                        "outcome_id": outcome_id,
                        "competency_level": f"{outcome_number}.{competency_index}",
                        "competency_description": competency_description,
                        "indicator_code": (
                            f"{outcome_number}.{competency_index}."
                            f"{indicator_index}"
                        ),
                        "indicator_description": indicator_description,
                        "co_ids": co_ids,
                    })
                if invalid:
                    break
            if invalid:
                break

        if invalid:
            messages.error(
                request,
                "Enter valid competency and performance-indicator counts, complete "
                "their descriptions, and select 1 or blank for each CO.",
            )
            return redirect("course_performance_indicators", course_id=course.id)

        if not submitted_rows and CoursePerformanceIndicator.objects.filter(
            course=course
        ).exists():
            messages.error(
                request,
                "The submitted form is empty. Existing performance indicators "
                "were not changed.",
            )
            return redirect("course_performance_indicators", course_id=course.id)

        with transaction.atomic():
            CoursePerformanceIndicator.objects.filter(course=course).delete()
            for row in submitted_rows:
                indicator = CoursePerformanceIndicator.objects.create(
                    course=course,
                    po_id=row["outcome_id"] if row["outcome_type"] == "po" else None,
                    pso_id=row["outcome_id"] if row["outcome_type"] == "pso" else None,
                    competency_level=row["competency_level"],
                    competency_description=row["competency_description"],
                    indicator_code=row["indicator_code"],
                    indicator_description=row["indicator_description"],
                )
                indicator.course_outcomes.set(row["co_ids"])

            _course_mapping_grades(course, cos=cos, pos=pos, psos=psos, persist=True)

        messages.success(request, "Performance indicators and CO mappings saved.")
        return redirect("course_performance_indicators", course_id=course.id)

    saved_by_outcome = defaultdict(list)
    for indicator in CoursePerformanceIndicator.objects.filter(
        course=course
    ).prefetch_related("course_outcomes"):
        outcome_type = "po" if indicator.po_id else "pso"
        outcome_id = indicator.po_id or indicator.pso_id
        saved_by_outcome[(outcome_type, outcome_id)].append({
            "competency_level": indicator.competency_level,
            "competency_description": indicator.competency_description,
            "indicator_code": indicator.indicator_code,
            "indicator_description": indicator.indicator_description,
            "co_ids": [
                co.id for co in indicator.course_outcomes.all()
            ],
        })

    outcome_sections = []
    for outcome_type, outcomes in (("po", pos), ("pso", psos)):
        for outcome in outcomes:
            groups = {}
            for indicator in saved_by_outcome[(outcome_type, outcome.id)]:
                key = (
                    indicator["competency_level"],
                    indicator["competency_description"],
                )
                groups.setdefault(key, []).append({
                    "indicator_code": indicator["indicator_code"],
                    "indicator_description": indicator["indicator_description"],
                    "co_ids": indicator["co_ids"],
                })
            outcome_sections.append({
                "kind": outcome_type,
                "id": outcome.id,
                "label": (
                    outcome.po_number
                    if outcome_type == "po"
                    else outcome.pso_number
                ),
                "number": (
                    int(re.search(
                        r"\d+",
                        outcome.po_number
                        if outcome_type == "po"
                        else outcome.pso_number,
                    ).group())
                    if re.search(
                        r"\d+",
                        outcome.po_number
                        if outcome_type == "po"
                        else outcome.pso_number,
                    )
                    else len(outcome_sections) + 1
                ),
                "description": outcome.description,
                "competencies": [
                    {
                        "level": level,
                        "description": description,
                        "indicators": indicators,
                    }
                    for (level, description), indicators in groups.items()
                ],
            })
            outcome_sections[-1]["competencies"].sort(
                key=lambda competency: tuple(
                    int(part)
                    for part in re.findall(r"\d+", competency["level"])
                )
            )
            for competency in outcome_sections[-1]["competencies"]:
                competency["indicators"].sort(
                    key=lambda indicator: tuple(
                        int(part)
                        for part in re.findall(
                            r"\d+", indicator["indicator_code"]
                        )
                    )
                )

    return render(
        request,
        "accounts/performance_indicators.html",
        {
            "course": course,
            "cos": cos,
            "pos": pos,
            "psos": psos,
            "outcome_sections": outcome_sections,
            "co_data": [
                {
                    "id": co.id,
                    "label": f"CO{co.co_number}",
                    "description": co.description,
                }
                for co in cos
            ],
        },
    )


def _performance_indicator_course_allowed(request, course):
    if request.user.role == "FACULTY":
        return course.faculty == request.user
    if request.user.role == "HOD":
        return course.academic_class.department == request.user.department
    return False


@login_required
def export_course_performance_indicators_template(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if not _performance_indicator_course_allowed(request, course):
        return HttpResponseForbidden("Not allowed")

    cos = list(course.cos.order_by("co_number"))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Performance Indicators"
    headers = [
        "Outcome",
        "Competency Level",
        "Competency Description",
        "PI No",
        "Performance Indicator",
    ] + [f"CO{co.co_number}" for co in cos]
    ws.append(headers)

    indicators = CoursePerformanceIndicator.objects.filter(
        course=course
    ).select_related("po", "pso").prefetch_related("course_outcomes")
    for indicator in indicators:
        outcome = indicator.po.po_number if indicator.po_id else indicator.pso.pso_number
        mapped_co_ids = {co.id for co in indicator.course_outcomes.all()}
        ws.append([
            outcome,
            indicator.competency_level,
            indicator.competency_description,
            indicator.indicator_code,
            indicator.indicator_description,
            *[1 if co.id in mapped_co_ids else "" for co in cos],
        ])

    for column in ws.columns:
        width = min(max(len(str(cell.value or "")) for cell in column) + 2, 45)
        ws.column_dimensions[column[0].column_letter].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    response = HttpResponse(
        output.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{course.course_code}_performance_indicators.xlsx"'
    )
    return response


@login_required
def import_course_performance_indicators(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if not _performance_indicator_course_allowed(request, course):
        return HttpResponseForbidden("Not allowed")
    if request.method != "POST" or not request.FILES.get("excel"):
        messages.error(request, "Select an Excel file to import.")
        return redirect("course_performance_indicators", course_id=course.id)

    try:
        wb = openpyxl.load_workbook(request.FILES["excel"], read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except (OSError, ValueError, TypeError, InvalidFileException, BadZipFile) as exc:
        messages.error(request, f"Could not read the Excel file: {exc}")
        return redirect("course_performance_indicators", course_id=course.id)

    if not rows:
        messages.error(request, "The Excel file is empty.")
        return redirect("course_performance_indicators", course_id=course.id)

    def clean(value):
        return str(value).strip() if value is not None else ""

    headers = [clean(value) for value in rows[0]]
    required_headers = [
        "Outcome",
        "Competency Level",
        "Competency Description",
        "PI No",
        "Performance Indicator",
    ]
    missing = [header for header in required_headers if header not in headers]
    cos = list(course.cos.order_by("co_number"))
    co_headers = {f"CO{co.co_number}": co for co in cos}
    if missing:
        messages.error(request, "Missing Excel columns: " + ", ".join(missing))
        return redirect("course_performance_indicators", course_id=course.id)
    if any(header not in headers for header in co_headers):
        missing_co_headers = [
            header for header in co_headers if header not in headers
        ]
        messages.error(
            request,
            "Missing CO columns: " + ", ".join(missing_co_headers),
        )
        return redirect("course_performance_indicators", course_id=course.id)

    column_index = {header: index for index, header in enumerate(headers)}
    pos, psos = _course_mapping_outcomes(course)
    outcomes = {
        outcome.po_number.upper(): ("po", outcome)
        for outcome in pos
    }
    outcomes.update({
        outcome.pso_number.upper(): ("pso", outcome)
        for outcome in psos
    })
    parsed_rows = []
    errors = []
    previous_outcome = ""
    previous_competency_level = ""
    previous_competency_description = ""
    for row_number, values in enumerate(rows[1:], start=2):
        if not any(value is not None and clean(value) for value in values):
            continue
        values = list(values) + [""] * (len(headers) - len(values))
        outcome_label = clean(values[column_index["Outcome"]]).upper()
        if not outcome_label:
            outcome_label = previous_outcome
        outcome_info = outcomes.get(outcome_label)
        competency_level = clean(values[column_index["Competency Level"]])
        if not competency_level:
            competency_level = previous_competency_level
        competency_description = clean(
            values[column_index["Competency Description"]]
        )
        if not competency_description:
            competency_description = previous_competency_description
        indicator_code = clean(values[column_index["PI No"]])
        indicator_description = clean(
            values[column_index["Performance Indicator"]]
        )
        if not outcome_info:
            errors.append(f"row {row_number}: unknown Outcome '{outcome_label}'")
            continue
        if not competency_level or not competency_description:
            errors.append(f"row {row_number}: competency fields are required")
            continue
        if not indicator_code or not indicator_description:
            errors.append(f"row {row_number}: PI fields are required")
            continue
        previous_outcome = outcome_label
        previous_competency_level = competency_level
        previous_competency_description = competency_description

        co_ids = []
        for header, co in co_headers.items():
            value = clean(values[column_index[header]]).lower()
            if value in ("1", "yes", "y", "x", "true"):
                co_ids.append(co.id)
            elif value not in ("", "0", "no", "n", "false"):
                errors.append(
                    f"row {row_number}: {header} must be blank or 1"
                )
        parsed_rows.append({
            "outcome_type": outcome_info[0],
            "outcome_id": outcome_info[1].id,
            "competency_level": competency_level,
            "competency_description": competency_description,
            "indicator_code": indicator_code,
            "indicator_description": indicator_description,
            "co_ids": co_ids,
        })

    if errors:
        messages.error(request, "Import failed: " + "; ".join(errors[:8]))
        return redirect("course_performance_indicators", course_id=course.id)
    if not parsed_rows:
        messages.error(request, "No valid performance-indicator rows found.")
        return redirect("course_performance_indicators", course_id=course.id)
    if len(parsed_rows) > 500:
        messages.error(request, "The Excel file may contain at most 500 indicators.")
        return redirect("course_performance_indicators", course_id=course.id)

    with transaction.atomic():
        CoursePerformanceIndicator.objects.filter(course=course).delete()
        for row in parsed_rows:
            indicator = CoursePerformanceIndicator.objects.create(
                course=course,
                po_id=row["outcome_id"] if row["outcome_type"] == "po" else None,
                pso_id=row["outcome_id"] if row["outcome_type"] == "pso" else None,
                competency_level=row["competency_level"],
                competency_description=row["competency_description"],
                indicator_code=row["indicator_code"],
                indicator_description=row["indicator_description"],
            )
            indicator.course_outcomes.set(row["co_ids"])
        _course_mapping_grades(course, cos=cos, pos=pos, psos=psos, persist=True)

    messages.success(
        request,
        f"{len(parsed_rows)} performance indicator(s) imported successfully.",
    )
    return redirect("course_performance_indicators", course_id=course.id)


@login_required
def course_mapping_grade(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if request.user.role == "FACULTY" and course.faculty != request.user:
        return HttpResponseForbidden("Not allowed")
    if request.user.role == "HOD" and course.academic_class.department != request.user.department:
        return HttpResponseForbidden("Not allowed")
    if request.user.role not in ("FACULTY", "HOD"):
        return HttpResponseForbidden("Not allowed")
    cos = list(course.cos.order_by("co_number"))
    grade_rows, pos, psos = _course_mapping_grades(course, cos=cos, persist=True)
    outcomes = [
        {"label": po.po_number, "kind": "PO"} for po in pos
    ] + [
        {"label": pso.pso_number, "kind": "PSO"} for pso in psos
    ]

    averages = []
    for column in range(len(outcomes)):
        grades = [
            row["entries"][column]["grade"]
            for row in grade_rows
            if row["entries"][column]["grade"] is not None
        ]
        averages.append(round(sum(grades) / len(grades), 2) if grades else 0)

    return render(
        request,
        "accounts/mapping_grade.html",
        {
            "course": course,
            "outcomes": outcomes,
            "grade_rows": grade_rows,
            "averages": averages,
        },
    )


@login_required
def co_po_pso_matrix(request, course_id):

    course = get_object_or_404(Course, id=course_id)
    if request.user.role == "FACULTY" and course.faculty != request.user:
        return HttpResponseForbidden("Not allowed")
    if request.user.role == "HOD" and course.academic_class.department != request.user.department:
        return HttpResponseForbidden("Not allowed")
    if request.user.role not in ("FACULTY", "HOD"):
        return HttpResponseForbidden("Not allowed")
    cos = list(course.cos.order_by("co_number"))
    grade_rows, pos, psos = _course_mapping_grades(
        course,
        cos=cos,
        persist=True,
    )
    if request.method == "POST":
        messages.info(request, "Mappings are calculated from the performance indicators.")
        return redirect("course_performance_indicators", course_id=course.id)

    matrix_rows = [
        {
            "co": row["co"],
            "cells": [
                entry["grade"] if entry["grade"] is not None else "-"
                for entry in row["entries"]
            ],
        }
        for row in grade_rows
    ]

    # ================= COLUMN AVERAGE =================
    po_averages = []
    for po in pos:
        avg = COPOMapping.objects.filter(
            po=po, co__in=cos
        ).aggregate(Avg("level"))["level__avg"]
        po_averages.append(round(avg, 2) if avg else 0)

    pso_averages = []
    for pso in psos:
        avg = COPSOMapping.objects.filter(
            pso=pso, co__in=cos
        ).aggregate(Avg("level"))["level__avg"]
        pso_averages.append(round(avg, 2) if avg else 0)

    return render(request, "accounts/co_matrix.html", {
        "course": course,
        "cos": cos,
        "pos": pos,
        "psos": psos,
        "matrix_rows": matrix_rows,
        "grade_rows": grade_rows,
        "po_averages": po_averages,
        "pso_averages": pso_averages,
    })



from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Course, AssessmentTool


@login_required
def assessment_tool_page(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if request.user.role == "FACULTY" and course.faculty != request.user:
        return HttpResponseForbidden("Not allowed")
    if request.user.role == "HOD" and course.academic_class.department != request.user.department:
        return HttpResponseForbidden("Not allowed")

    if request.method == "POST":
        main_tool = request.POST.get("main_tool")
        sub_tool = request.POST.get("sub_tool")

        # Duplicate prevention
        exists = AssessmentTool.objects.filter(
            course=course,
            main_tool=main_tool,
            sub_tool=sub_tool
        ).exists()

        if exists:
            messages.warning(request, "This tool already exists.")
        else:
            AssessmentTool.objects.create(
                course=course,
                main_tool=main_tool,
                sub_tool=sub_tool
            )
            messages.success(request, "Tool added successfully.")

        return redirect("assessment_tool_page", course_id=course.id)

    tools = AssessmentTool.objects.filter(course=course)

    return render(request, "tools/assessment_tools.html", {
        "course": course,
        "tools": tools
    })

from django.shortcuts import get_object_or_404
from django.contrib import messages
@login_required
def delete_assessment_tool(request, tool_id):
    tool = get_object_or_404(AssessmentTool, id=tool_id)
    course_id = tool.course.id

    if tool.is_locked:
        messages.error(request, "This tool is locked and cannot be deleted.")
    elif (
        IcaStudentMarks.objects.filter(tool=tool).exists()
        or AssignmentTutorialMarks.objects.filter(tool=tool).exists()
        or ExamMarks.objects.filter(tool=tool).exists()
        or UniversityExamMarks.objects.filter(tool=tool).exists()
    ):
        messages.error(
            request,
            "This tool has saved student marks and cannot be deleted.",
        )
    else:
        tool.delete()
        messages.success(request, "Tool deleted successfully.")

    return redirect("assessment_tool_page", course_id=course_id)

from .models import AssessmentTool, IcaAssignmentExp

@login_required
def ica_tool_detail(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    course = tool.course

    cos = CourseOutcome.objects.filter(
        course=course
    ).order_by("co_number")

    details = IcaAssignmentExp.objects.filter(
        tool=tool
    ).order_by("sub_tool_no")

    if request.method == "POST":
        try:
            rows = int(request.POST.get("total_rows", 0))
        except ValueError:
            messages.error(request, "Select a valid number of assessment rows.")
            return redirect("ica_tool_detail", tool_id=tool.id)

        if not 0 <= rows <= 15:
            messages.error(request, "Select a valid number of assessment rows.")
            return redirect("ica_tool_detail", tool_id=tool.id)

        removed_details = IcaAssignmentExp.objects.filter(
            tool=tool,
            sub_tool_no__gt=rows,
        )
        if IcaStudentMarks.objects.filter(subtool__in=removed_details).exists():
            messages.error(
                request,
                "These rows have saved student marks. Remove or transfer those "
                "marks before reducing the assessment rows.",
            )
            return redirect("ica_tool_detail", tool_id=tool.id)

        with transaction.atomic():
            removed_details.delete()

            for i in range(1, rows + 1):
                marks = request.POST.get(f"marks_{i}")
                if not marks:
                    continue

                IcaAssignmentExp.objects.update_or_create(
                    tool=tool,
                    sub_tool_no=i,
                    defaults={
                        "co_id": request.POST.get(f"co_{i}") or None,
                        "bl": request.POST.get(f"bl_{i}") or "BL1",
                        "marks": int(marks),
                    }
                )

        return redirect("ica_tool_detail", tool_id=tool.id)

    return render(
        request,
        "tools/ica_detail.html",
        {
            "tool": tool,
            "course": course,
            "cos": cos,
            "details": details,
            "sub_tool_prefix": tool.sub_tool,
            "range_15": range(1, 16),
        }
    )



from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from .models import AssessmentTool, CourseOutcome, AssignmentTool


def _distribute_assignment_marks(total_marks, rows):
    question_total = sum(row["question_count"] for row in rows)
    if not question_total:
        return

    allocations = []
    for index, row in enumerate(rows):
        numerator = total_marks * row["question_count"]
        marks, remainder = divmod(numerator, question_total)
        allocations.append([index, marks, remainder])

    remaining_marks = total_marks - sum(allocation[1] for allocation in allocations)
    for index, _, _ in sorted(
        allocations,
        key=lambda allocation: (-allocation[2], allocation[0]),
    )[:remaining_marks]:
        allocations[index][1] += 1

    for index, marks, _ in allocations:
        rows[index]["marks"] = marks


@login_required
def assignment_tutorial_page(request, tool_id):
    from .models import (
        AssessmentTool,
        AssignmentTool,
        AssignmentTutorialMarks,
        CourseOutcome,
    )

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    course = tool.course
    cos = list(CourseOutcome.objects.filter(course=course).order_by("co_number"))
    co_by_id = {str(co.id): co for co in cos}
    existing_details = list(
        AssignmentTool.objects.filter(tool=tool).select_related("co").order_by("question_no")
    )

    if request.method == "POST":
        try:
            assignment_count = int(request.POST.get("assignment_count", ""))
        except ValueError:
            assignment_count = 0

        if not 1 <= assignment_count <= 15:
            messages.error(request, "Select the number of assignments before saving.")
            return redirect("assignment_tutorial_page", tool_id=tool.id)

        submitted_rows = []
        used_cos = defaultdict(set)
        invalid = False

        for field, co_id in request.POST.items():
            match = re.fullmatch(r"co_A(\d+)\.(\d+)", field)
            if not match:
                continue

            assignment_no, distribution_no = map(int, match.groups())
            question_no = f"A{assignment_no}.{distribution_no}"
            questions_text = request.POST.get(f"questions_{question_no}", "").strip()
            bl = request.POST.get(f"bl_{question_no}", "")

            try:
                question_count = int(questions_text)
            except ValueError:
                question_count = 0

            if (
                not 1 <= assignment_no <= assignment_count
                or not 1 <= distribution_no <= len(cos)
                or co_id not in co_by_id
                or question_count < 1
                or bl not in {f"BL{i}" for i in range(1, 7)}
                or co_id in used_cos[assignment_no]
            ):
                invalid = True
                break

            used_cos[assignment_no].add(co_id)
            submitted_rows.append({
                "assignment_no": assignment_no,
                "distribution_no": distribution_no,
                "question_no": question_no,
                "co_id": int(co_id),
                "bl": bl,
                "question_count": question_count,
            })

        assignment_totals = {}
        for assignment_no in range(1, assignment_count + 1):
            try:
                total_marks = int(
                    request.POST.get(f"total_A{assignment_no}", "").strip()
                )
            except ValueError:
                total_marks = -1
            if total_marks < 0:
                invalid = True
                break
            assignment_totals[assignment_no] = total_marks

        if not invalid:
            for assignment_no in range(1, assignment_count + 1):
                assignment_rows = [
                    row for row in submitted_rows
                    if row["assignment_no"] == assignment_no
                ]
                _distribute_assignment_marks(
                    assignment_totals[assignment_no],
                    assignment_rows,
                )

        if invalid or not submitted_rows or any(
            not used_cos[assignment_no]
            for assignment_no in range(1, assignment_count + 1)
        ):
            messages.error(
                request,
                "Add a CO distribution with a CO, Bloom level, and total marks "
                "for every assignment. A CO can appear only once per assignment.",
            )
            return redirect("assignment_tutorial_page", tool_id=tool.id)

        old_item_groups = {}
        for item in existing_details:
            match = re.fullmatch(r"A(\d+)\.\d+", item.question_no or "")
            if not match:
                old_item_groups[item.id] = None
                continue
            group_key = (int(match.group(1)), item.co_id)
            old_item_groups[item.id] = group_key

        old_group_marks = defaultdict(lambda: defaultdict(int))
        marked_group_students = defaultdict(set)
        saved_marks = AssignmentTutorialMarks.objects.filter(
            tool=tool,
            marks__isnull=False,
        ).values_list("student_id", "question_id", "marks")
        for student_id, question_id, marks in saved_marks:
            group_key = old_item_groups.get(question_id)
            if group_key is None:
                messages.error(
                    request,
                    "Some saved student marks cannot be matched to an assignment "
                    "and CO. Correct the existing configuration before changing it.",
                )
                return redirect("assignment_tutorial_page", tool_id=tool.id)
            old_group_marks[group_key][student_id] += marks
            marked_group_students[group_key].add(student_id)

        submitted_by_group = {
            (row["assignment_no"], row["co_id"]): row for row in submitted_rows
        }
        for group_key, student_ids in marked_group_students.items():
            new_row = submitted_by_group.get(group_key)
            if new_row is None:
                messages.error(
                    request,
                    "This change would remove a CO group that already has student "
                    "marks. Clear or retain those marks before removing the group.",
                )
                return redirect("assignment_tutorial_page", tool_id=tool.id)
            if any(
                old_group_marks[group_key][student_id] > new_row["marks"]
                for student_id in student_ids
            ):
                messages.error(
                    request,
                    "A saved student's total is greater than the new maximum for "
                    f"CO{co_by_id[str(group_key[1])].co_number}. Increase the total "
                    "marks or correct the saved marks first.",
                )
                return redirect("assignment_tutorial_page", tool_id=tool.id)

        with transaction.atomic():
            AssignmentTutorialMarks.objects.filter(tool=tool).delete()
            AssignmentTool.objects.filter(tool=tool).delete()

            new_items = {}
            for row in submitted_rows:
                item = AssignmentTool.objects.create(
                    tool=tool,
                    question_no=row["question_no"],
                    co_id=row["co_id"],
                    bl=row["bl"],
                    question_count=row["question_count"],
                    marks=row["marks"],
                )
                new_items[(row["assignment_no"], row["co_id"])] = item

            migrated_marks = []
            for group_key, student_ids in marked_group_students.items():
                item = new_items[group_key]
                for student_id in student_ids:
                    migrated_marks.append(
                        AssignmentTutorialMarks(
                            tool=tool,
                            student_id=student_id,
                            question=item,
                            marks=old_group_marks[group_key][student_id],
                        )
                    )
            AssignmentTutorialMarks.objects.bulk_create(migrated_marks)

        messages.success(request, "Assignment / Tutorial saved successfully.")
        return redirect("assignment_tutorial_page", tool_id=tool.id)

    grouped_details = {}
    for item in existing_details:
        match = re.fullmatch(r"A(\d+)\.\d+", item.question_no or "")
        if not match:
            continue
        assignment_no = int(match.group(1))
        co_id = item.co_id
        group_key = (assignment_no, co_id)
        if group_key not in grouped_details:
            grouped_details[group_key] = {
                "assignment_no": assignment_no,
                "co_id": co_id,
                "bl": item.bl,
                "question_count": 0,
                "marks": 0,
            }
        grouped_details[group_key]["question_count"] += item.question_count
        grouped_details[group_key]["marks"] += item.marks

    saved_rows = []
    assignment_distribution_counts = defaultdict(int)
    for group in sorted(
        grouped_details.values(),
        key=lambda row: (
            row["assignment_no"],
            co_by_id[str(row["co_id"])].co_number
            if str(row["co_id"]) in co_by_id
            else 0,
        ),
    ):
        assignment_distribution_counts[group["assignment_no"]] += 1
        group["question_no"] = (
            f"A{group['assignment_no']}."
            f"{assignment_distribution_counts[group['assignment_no']]}"
        )
        saved_rows.append(group)

    assignment_count = max(assignment_distribution_counts, default=0)
    return render(
        request,
        "tools/assignment_tutorial.html",
        {
            "tool": tool,
            "course": course,
            "cos": cos,
            "saved_rows": saved_rows,
            "assignment_count": assignment_count,
            "co_count": len(cos),
            "range": range(1, 16),
        }
    )

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from .models import AssessmentTool, CourseOutcome, ExamDetail,UniversityExam, UniversityExamMarks


def _exam_question_sort_key(item):
    match = re.match(r"Q(\d+)(?:\.([A-Za-z]+))?$", item.question_no or "")
    if not match:
        return (9999, item.question_no or "")

    main_no = int(match.group(1))
    sub_part = match.group(2) or ""
    return (main_no, sub_part.lower())


def _exam_main_no(question_no):
    match = re.match(r"Q(\d+)", question_no or "")
    return int(match.group(1)) if match else 0


def _effective_exam_detail_ids(exam_details, marks_by_question_id=None):
    grouped = defaultdict(list)

    for detail in exam_details:
        grouped[_exam_main_no(detail.question_no)].append(detail)

    selected_ids = set()

    for main_no, details in grouped.items():
        details = sorted(details, key=_exam_question_sort_key)
        allowed = next((detail.solve_any for detail in details if detail.solve_any), 0) or len(details)

        if marks_by_question_id is None:
            ranked = sorted(details, key=lambda detail: (detail.marks or 0, -_exam_question_sort_key(detail)[0]), reverse=True)
        else:
            ranked = [
                detail
                for detail in details
                if marks_by_question_id.get(detail.id) is not None
            ]
            ranked = sorted(
                ranked,
                key=lambda detail: (marks_by_question_id.get(detail.id) or 0, detail.marks or 0),
                reverse=True
            )

        selected_ids.update(detail.id for detail in ranked[:allowed])

    return selected_ids


@login_required
def exam_details(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    course = tool.course
    cos = list(
        CourseOutcome.objects.filter(course=course).order_by("co_number")
    )

    details = sorted(
        ExamDetail.objects.filter(tool=tool).select_related("co"),
        key=_exam_question_sort_key
    )

    if request.method == "POST":
        try:
            distribution_count = int(request.POST.get("distribution_count", ""))
        except ValueError:
            distribution_count = 0

        if not 1 <= distribution_count <= len(cos):
            messages.error(request, "Select a valid number of CO distributions.")
            return redirect("exam_details", tool_id=tool.id)

        co_by_id = {str(co.id): co for co in cos}
        submitted_rows = []
        invalid = False

        for index in range(1, distribution_count + 1):
            key = f"Q{index}"
            co_id = request.POST.get(f"co_{key}", "")
            bl = request.POST.get(f"bl_{key}", "")
            try:
                marks = int(request.POST.get(f"marks_{key}", "").strip())
            except ValueError:
                marks = -1

            if (
                co_id not in co_by_id
                or bl not in {f"BL{level}" for level in range(1, 7)}
                or marks < 0
            ):
                invalid = True
                break

            submitted_rows.append({
                "question_no": key,
                "co_id": int(co_id),
                "bl": bl,
                "marks": marks,
            })

        if invalid or len(submitted_rows) != distribution_count:
            messages.error(
                request,
                "Select a CO and Bloom level, and enter valid marks for every row.",
            )
            return redirect("exam_details", tool_id=tool.id)

        from .models import ExamMarks

        for detail, row in zip(details, submitted_rows):
            if ExamMarks.objects.filter(
                question=detail,
                marks__gt=row["marks"],
            ).exists():
                messages.error(
                    request,
                    f"Saved student marks exceed the new maximum for "
                    f"{detail.question_no}. Correct those marks or increase the "
                    "maximum before saving.",
                )
                return redirect("exam_details", tool_id=tool.id)

        removed_details = details[distribution_count:]
        if any(
            ExamMarks.objects.filter(question=detail).exists()
            for detail in removed_details
        ):
            messages.error(
                request,
                "These CO distributions have saved student marks. Keep them or "
                "clear/transfer those marks before reducing the distributions.",
            )
            return redirect("exam_details", tool_id=tool.id)

        with transaction.atomic():
            for index, detail in enumerate(details, start=1):
                detail.question_no = f"TEMP{index}"
                detail.save(update_fields=["question_no"])

            for index, row in enumerate(submitted_rows):
                if index < len(details):
                    detail = details[index]
                    detail.question_no = row["question_no"]
                    detail.co_id = row["co_id"]
                    detail.bl = row["bl"]
                    detail.marks = row["marks"]
                    detail.solve_any = 0
                    detail.save()
                else:
                    ExamDetail.objects.create(
                        tool=tool,
                        question_no=row["question_no"],
                        co_id=row["co_id"],
                        bl=row["bl"],
                        marks=row["marks"],
                        solve_any=0,
                    )

            for detail in details[distribution_count:]:
                detail.delete()

        messages.success(request, "Exam CO distributions saved successfully.")
        return redirect("exam_details", tool_id=tool.id)

    return render(
        request,
        "tools/exam_details.html",
        {
            "tool": tool,
            "course": course,
            "cos": cos,
            "saved_rows": [
                {
                    "co_id": detail.co_id,
                    "bl": detail.bl,
                    "marks": detail.marks,
                }
                for detail in details
            ],
            "distribution_count": len(details),
            "range": range(1, len(cos) + 1),
            "is_saved": bool(details),
        }
    )
@login_required
def university_exam_page(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    course = tool.course
    assessment_label = tool.sub_tool or "University Exam"
    edit_mode = request.GET.get("edit") == "1"

    cos = CourseOutcome.objects.filter(
        course=course
    ).order_by("co_number")

    saved = UniversityExam.objects.filter(tool=tool).select_related("co")
    is_locked = saved.exists() and not edit_mode
    saved_by_co = {item.co_id: item.marks for item in saved}
    total_marks = sum(saved_by_co.values())
    co_rows = [
        {
            "co": co,
            "saved_marks": saved_by_co.get(co.id),
        }
        for co in cos
    ]

    if request.method == "POST":

        total_marks = request.POST.get("total_marks", "").strip()
        try:
            total_marks = float(total_marks)
        except ValueError:
            messages.error(request, f"Enter a valid total for {assessment_label}.")
            return redirect("university_exam_page", tool_id=tool.id)

        if not math.isfinite(total_marks) or total_marks < 0:
            messages.error(
                request,
                f"{assessment_label} total must be a finite, non-negative number.",
            )
            return redirect("university_exam_page", tool_id=tool.id)

        course_cos = list(cos)
        if not course_cos:
            messages.error(request, f"Add course outcomes before saving {assessment_label} marks.")
            return redirect("university_exam_page", tool_id=tool.id)

        equal_marks = total_marks / len(course_cos)
        with transaction.atomic():
            for co in course_cos:
                UniversityExam.objects.update_or_create(
                    tool=tool,
                    co=co,
                    defaults={"marks": equal_marks},
                )

        messages.success(request, f"{assessment_label} saved successfully")

        return redirect("university_exam_page", tool_id=tool.id)

    return render(
        request,
        "tools/university_exam.html",
        {
            "tool": tool,
            "course": course,
            "assessment_label": assessment_label,
            "co_rows": co_rows,
            "total_marks": total_marks,
            "is_locked": is_locked,
        }
    )



@login_required
def export_university_exam_excel(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "University Exam"

    ws.append(["CO No", "Description", "Marks"])

    records = {
        record.co_id: record
        for record in UniversityExam.objects.filter(tool=tool).select_related("co")
    }
    cos = CourseOutcome.objects.filter(course=tool.course).order_by("co_number")

    for co in cos:
        record = records.get(co.id)
        ws.append([f"CO{co.co_number}", co.description, record.marks if record else ""])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    response["Content-Disposition"] = f'attachment; filename="university_exam_{tool.course.course_code}_{tool.id}.xlsx"'

    wb.save(response)

    return response


# -------------------------------------------------
# IMPORT EXCEL
# -------------------------------------------------

@login_required
def import_university_exam_excel(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    course = tool.course

    if request.method == "POST" and request.FILES.get("excel_file"):

        file = request.FILES["excel_file"]

        wb = openpyxl.load_workbook(file)
        ws = wb.active

        imported_rows = []
        seen_co_ids = set()
        for row in ws.iter_rows(min_row=2, values_only=True):
            co_label, description, marks = (list(row) + [None, None, None])[:3]
            if not co_label:
                continue

            co_number = str(co_label).upper().replace("CO", "").strip()
            if not co_number.isdigit():
                messages.error(request, f"Invalid course outcome label: {co_label}.")
                return redirect("university_exam_page", tool_id=tool.id)

            co = CourseOutcome.objects.filter(
                course=course,
                co_number=int(co_number)
            ).first()
            if not co:
                messages.error(
                    request,
                    f"CO{co_number} does not belong to this course.",
                )
                return redirect("university_exam_page", tool_id=tool.id)
            if co.id in seen_co_ids:
                messages.error(request, f"CO{co_number} appears more than once.")
                return redirect("university_exam_page", tool_id=tool.id)
            try:
                co_marks = float(marks)
            except (TypeError, ValueError):
                messages.error(
                    request,
                    f"Enter valid marks for CO{co_number}.",
                )
                return redirect("university_exam_page", tool_id=tool.id)
            if not math.isfinite(co_marks) or co_marks < 0:
                messages.error(
                    request,
                    f"Marks for CO{co_number} must be finite and non-negative.",
                )
                return redirect("university_exam_page", tool_id=tool.id)
            seen_co_ids.add(co.id)
            imported_rows.append((co, co_marks))

        if not imported_rows:
            messages.error(request, "The workbook contains no valid CO marks.")
            return redirect("university_exam_page", tool_id=tool.id)

        with transaction.atomic():
            for co, co_marks in imported_rows:
                UniversityExam.objects.update_or_create(
                    tool=tool,
                    co=co,
                    defaults={"marks": co_marks},
                )

        messages.success(request, "University exam imported successfully")

    return redirect("university_exam_page", tool_id=tool.id)


@login_required
def university_exam_marks(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    assessment_label = tool.sub_tool or "University Exam"
    academic_class = tool.course.academic_class
    edit_mode = request.GET.get("edit") == "1"
    is_locked = not edit_mode

    students = Student.objects.filter(
        academic_class=academic_class
    ).order_by("list_order", "pk")

    marks_records = {
        record.student_id: record.marks
        for record in UniversityExamMarks.objects.filter(tool=tool)
    }

    if request.method == "POST":

        if "edit_mode" in request.POST:
            return redirect(f"{request.path}?edit=1")

        if "save_marks" in request.POST:

            for student in students:

                val = request.POST.get(f"marks_{student.id}")
                marks_value = None if val in ("", None) else float(val)

                UniversityExamMarks.objects.update_or_create(
                    tool=tool,
                    student=student,
                    defaults={"marks": marks_value}
                )

            messages.success(request, f"{assessment_label} student marks saved successfully")

            return redirect("university_exam_marks", tool_id=tool.id)

        if "export_excel" in request.POST:

            wb = Workbook()
            ws = wb.active
            ws.title = f"{assessment_label} Marks"[:31]
            ws.append(["Roll No", "Student Name", "Obtained Marks"])

            for student in students:
                ws.append([
                    student.roll_no,
                    student.name,
                    marks_records.get(student.id, "")
                ])

            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            filename = assessment_label.lower().replace(" ", "_")
            response["Content-Disposition"] = f"attachment; filename={filename}_student_marks.xlsx"
            wb.save(response)
            return response

        if "import_excel" in request.POST:

            excel_file = request.FILES.get("excel_file")

            if not excel_file:
                messages.error(request, f"Upload an Excel file for {assessment_label} marks.")
                return redirect("university_exam_marks", tool_id=tool.id)

            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active

            for row in ws.iter_rows(min_row=2, values_only=True):

                roll_no, name, marks = (list(row) + [None, None, None])[:3]

                if not roll_no:
                    continue

                student = Student.objects.filter(
                    roll_no=str(roll_no),
                    academic_class=academic_class
                ).first()

                if not student:
                    continue

                marks_value = None if marks in ("", None) else float(marks)

                UniversityExamMarks.objects.update_or_create(
                    tool=tool,
                    student=student,
                    defaults={"marks": marks_value}
                )

            messages.success(request, f"{assessment_label} student marks imported successfully")

            return redirect("university_exam_marks", tool_id=tool.id)

    student_rows = [
        {
            "student": student,
            "marks": marks_records.get(student.id, ""),
        }
        for student in students
    ]

    return render(
        request,
        "Marks/university_exam_marks.html",
        {
            "tool": tool,
            "assessment_label": assessment_label,
            "student_rows": student_rows,
            "is_locked": is_locked,
        }
    )


import openpyxl
from openpyxl import Workbook

from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import IntegerField
from django.db.models.functions import Cast

from .models import (
    AssessmentTool,
    IcaStudentMarks,
    IcaAssignmentExp,
    Student,
    CourseOutcome,
    AssignmentTutorialMarks
)


# =========================================================
# ICA STUDENT MARKS
# =========================================================
@login_required
def ica_student_marks(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    course = tool.course
    academic_class = course.academic_class

    # Sort roll numbers numerically
    students = Student.objects.filter(
        academic_class=academic_class
    ).order_by("list_order", "pk")

    subtools = IcaAssignmentExp.objects.filter(
        tool=tool
    ).order_by("sub_tool_no")

    edit_mode = request.GET.get("edit") == "1"
    is_locked = not edit_mode


    # =====================================================
    # POST REQUEST
    # =====================================================

    if request.method == "POST":

        # ---------------------------
        # EDIT MODE
        # ---------------------------

        if "edit_mode" in request.POST:
            return redirect(f"{request.path}?edit=1")


        # ---------------------------
        # SAVE MARKS
        # ---------------------------

        if "save_marks" in request.POST:

            for student in students:
                for sub in subtools:

                    field_name = f"marks_{student.id}_{sub.sub_tool_no}"
                    marks_value = request.POST.get(field_name)

                    # Important logic
                    if marks_value == "" or marks_value is None:
                        marks_value = None
                    else:
                        marks_value = int(marks_value)
                        if marks_value > sub.marks:
                            messages.error(
                                request,
                                f"{student.roll_no} - {tool.sub_tool} {sub.sub_tool_no}: marks cannot exceed {sub.marks}"
                            )
                            return redirect(f"{request.path}?edit=1")

                    IcaStudentMarks.objects.update_or_create(
                        tool=tool,
                        student=student,
                        subtool=sub,
                        defaults={"marks": marks_value}
                    )

            messages.success(request, "Marks saved successfully")
            return redirect("ica_student_marks", tool_id=tool.id)


        # ---------------------------
        # EXPORT EXCEL
        # ---------------------------

        if "export_excel" in request.POST:

            wb = Workbook()
            ws = wb.active
            ws.title = "ICA Marks"

            headers = ["Roll No", "Student Name"]

            for sub in subtools:
                headers.append(f"{tool.sub_tool} {sub.sub_tool_no}")

            ws.append(headers)

            for student in students:

                row = [student.roll_no, student.name]

                for sub in subtools:

                    mark_obj = IcaStudentMarks.objects.filter(
                        tool=tool,
                        student=student,
                        subtool=sub
                    ).first()

                    if mark_obj and mark_obj.marks is not None:
                        marks = mark_obj.marks
                    else:
                        marks = ""

                    row.append(marks)

                ws.append(row)

            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            response["Content-Disposition"] = f'attachment; filename="{tool.sub_tool}_marks.xlsx"'

            wb.save(response)

            return response


        # ---------------------------
        # IMPORT EXCEL
        # ---------------------------

        if "import_excel" in request.POST:

            excel_file = request.FILES.get("excel_file")

            if not excel_file:
                messages.error(request, "No file uploaded")
                return redirect("ica_student_marks", tool_id=tool.id)

            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active
            skipped_cells = 0
            skipped_fields = []

            for row in ws.iter_rows(min_row=2, values_only=True):

                roll_no = row[0]

                student = Student.objects.filter(
                    roll_no=str(roll_no),
                    academic_class=academic_class
                ).first()

                if not student:
                    continue

                for i, sub in enumerate(subtools):

                    try:
                        marks_cell = row[i + 2]
                    except IndexError:
                        marks_cell = None

                    if marks_cell == "" or marks_cell is None:
                        marks_value = None
                    else:
                        marks_value = int(marks_cell)
                        if marks_value > sub.marks:
                            skipped_cells += 1
                            skipped_fields.append(f"marks_{student.id}_{sub.sub_tool_no}")
                            continue

                    IcaStudentMarks.objects.update_or_create(
                        tool=tool,
                        student=student,
                        subtool=sub,
                        defaults={"marks": marks_value}
                    )

            if skipped_cells:
                request.session[f"skipped_ica_marks_{tool.id}"] = skipped_fields
                messages.warning(request, f"Excel imported. {skipped_cells} marks were skipped because they exceed max marks.")
            else:
                request.session.pop(f"skipped_ica_marks_{tool.id}", None)
                messages.success(request, "Excel marks imported successfully")

            return redirect("ica_student_marks", tool_id=tool.id)


    # =====================================================
    # PREPARE DATA FOR TEMPLATE
    # =====================================================

    marks_matrix = {}
    skipped_fields = set(request.session.pop(f"skipped_ica_marks_{tool.id}", [])) if hasattr(request, "session") else set()
    skipped_matrix = {}

    for field in skipped_fields:
        parts = field.split("_")
        if len(parts) >= 3:
            skipped_matrix.setdefault(int(parts[1]), {})[int(parts[2])] = True

    for m in IcaStudentMarks.objects.filter(tool=tool):

        student_id = m.student_id
        subtool_no = m.subtool.sub_tool_no

        if student_id not in marks_matrix:
            marks_matrix[student_id] = {}

        marks_matrix[student_id][subtool_no] = m.marks


    # =====================================================
    # RENDER TEMPLATE
    # =====================================================

    return render(request, "Marks/ica_student_marks.html", {
        "tool": tool,
        "students": students,
        "subtools": subtools,
        "marks_matrix": marks_matrix,
        "skipped_matrix": skipped_matrix,
        "is_locked": is_locked,
    })

import openpyxl
from openpyxl import Workbook

from django.http import HttpResponse
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models.functions import Cast
from django.db.models import IntegerField

from .models import (
    AssessmentTool,
    AssignmentTool,
    AssignmentTutorialMarks,
    Student, ExamMarks
)
@login_required
def assignment_tutorial_marks(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    academic_class = tool.course.academic_class
    edit_mode = request.GET.get("edit") == "1"
    is_locked = not edit_mode

    # Sort roll numbers numerically
    students = Student.objects.filter(
        academic_class=academic_class
    ).order_by("list_order", "pk")

    def assignment_question_sort_key(question):
        match = re.fullmatch(r"A(\d+)\.(\d+)", question.question_no or "")
        if match:
            return (0, int(match.group(1)), int(match.group(2)), "")
        return (1, 0, 0, question.question_no or "")

    questions = sorted(
        AssignmentTool.objects.filter(tool=tool).select_related("co"),
        key=assignment_question_sort_key,
    )
    assignment_groups = []
    for question in questions:
        match = re.fullmatch(r"A(\d+)\.\d+", question.question_no or "")
        assignment_key = match.group(1) if match else question.question_no
        assignment_label = (
            f"Assignment {assignment_key}" if match else "Assignment"
        )
        if (
            not assignment_groups
            or assignment_groups[-1]["key"] != assignment_key
        ):
            assignment_groups.append({
                "key": assignment_key,
                "label": assignment_label,
                "questions": [],
            })
        assignment_groups[-1]["questions"].append(question)

    marks_records = AssignmentTutorialMarks.objects.filter(tool=tool)

    marks_dict = {}

    for m in marks_records:
        marks_dict.setdefault(m.student_id, {})[m.question_id] = m.marks


    # ================= POST =================

    if request.method == "POST":

        if "edit_mode" in request.POST:
            return redirect(f"{request.path}?edit=1")

        # ================= SAVE MARKS =================

        if "save_marks" in request.POST:

            for student in students:
                for q in questions:

                    field = f"marks_{student.id}_{q.id}"
                    val = request.POST.get(field)

                    # Important logic
                    if val == "" or val is None:
                        marks_value = None
                    else:
                        marks_value = int(val)
                        if marks_value > q.marks:
                            messages.error(
                                request,
                                f"{student.roll_no} - {q.question_no}: marks cannot exceed {q.marks}"
                            )
                            return redirect(f"{request.path}?edit=1")

                    AssignmentTutorialMarks.objects.update_or_create(
                        tool=tool,
                        student=student,
                        question=q,
                        defaults={"marks": marks_value}
                    )

            messages.success(request, "Marks saved successfully")
            return redirect("assignment_tutorial_marks", tool_id=tool.id)


        # ================= EXPORT EXCEL =================

        if "export_excel" in request.POST:

            wb = Workbook()
            ws = wb.active
            ws.title = "Assignment Marks"

            assignment_headers = ["Assignment", ""]
            assignment_headers.extend(
                f"Assignment {match.group(1)}"
                if (match := re.fullmatch(r"A(\d+)\.\d+", q.question_no))
                else "Assignment"
                for q in questions
            )
            assignment_headers.append("")
            ws.append(assignment_headers)

            co_headers = ["Roll No", "Student Name"]
            co_headers.extend(
                f"CO{q.co.co_number}" if q.co else "No CO"
                for q in questions
            )
            co_headers.append("Total")
            ws.append(co_headers)

            max_marks_row = ["Total Marks", ""]
            max_marks_row.extend(q.marks for q in questions)
            max_marks_row.append("-")
            ws.append(max_marks_row)

            for student in students:
                row = [student.roll_no, student.name]
                total = 0

                for q in questions:
                    mark = marks_dict.get(student.id, {}).get(q.id)
                    if mark is None:
                        mark = ""
                    else:
                        total += mark
                    row.append(mark)

                row.append(total)
                ws.append(row)

            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            response["Content-Disposition"] = "attachment; filename=assignment_marks.xlsx"

            wb.save(response)

            return response


        # ================= IMPORT EXCEL =================

        if "import_excel" in request.POST:

            excel_file = request.FILES.get("excel_file")

            if not excel_file:
                messages.error(request, "No file uploaded")
                return redirect("assignment_tutorial_marks", tool_id=tool.id)

            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active
            skipped_cells = 0
            skipped_fields = []

            header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            second_row = next(ws.iter_rows(min_row=2, max_row=2, values_only=True), ())
            has_assignment_header = bool(header_row) and header_row[0] == "Assignment"
            has_old_co_header = any(
                header_row[index] == "CO"
                for index in range(min(2, len(header_row)))
            ) and any(q.question_no in second_row for q in questions)
            if has_assignment_header:
                data_start_row = 4
                question_columns = {}
                for column, assignment_label in enumerate(header_row):
                    match = re.fullmatch(r"Assignment (\d+)", str(assignment_label or ""))
                    if not match or column >= len(second_row):
                        continue
                    co_label = second_row[column]
                    question = next(
                        (
                            q for q in questions
                            if re.fullmatch(
                                rf"A{match.group(1)}\.\d+",
                                q.question_no,
                            )
                            and (
                                f"CO{q.co.co_number}" if q.co else "No CO"
                            ) == co_label
                        ),
                        None,
                    )
                    if question:
                        question_columns[question.question_no] = column
            else:
                question_header_row = second_row if has_old_co_header else header_row
                data_start_row = 4 if has_old_co_header else 2
                question_columns = {
                    value: index
                    for index, value in enumerate(question_header_row)
                    if value in {q.question_no for q in questions}
                }

            for row in ws.iter_rows(min_row=data_start_row, values_only=True):

                roll_no = row[0]

                if roll_no is None or str(roll_no).strip() in {"", "Max Marks"}:
                    continue

                student = Student.objects.filter(
                    roll_no=str(roll_no),
                    academic_class=academic_class
                ).first()

                if not student:
                    continue

                for q in questions:
                    column = question_columns.get(q.question_no)
                    mark = row[column] if column is not None and column < len(row) else None

                    if mark == "" or mark is None:
                        marks_value = None
                    else:
                        marks_value = int(mark)
                        if marks_value > q.marks:
                            skipped_cells += 1
                            skipped_fields.append(f"marks_{student.id}_{q.id}")
                            continue

                    AssignmentTutorialMarks.objects.update_or_create(
                        tool=tool,
                        student=student,
                        question=q,
                        defaults={"marks": marks_value}
                    )

            if skipped_cells:
                request.session[f"skipped_assignment_marks_{tool.id}"] = skipped_fields
                messages.warning(request, f"Excel imported. {skipped_cells} marks were skipped because they exceed max marks.")
            else:
                request.session.pop(f"skipped_assignment_marks_{tool.id}", None)
                messages.success(request, "Excel marks imported successfully")

            return redirect("assignment_tutorial_marks", tool_id=tool.id)


    # ================= TABLE DATA =================

    student_rows = []
    skipped_fields = set(request.session.pop(f"skipped_assignment_marks_{tool.id}", [])) if hasattr(request, "session") else set()

    for student in students:

        row_marks = []
        total = 0

        for q in questions:

            mark = marks_dict.get(student.id, {}).get(q.id)

            if mark is None:
                display_mark = ""
            else:
                display_mark = mark
                total += mark

            row_marks.append({
                "q_id": q.id,
                "mark": display_mark,
                "max_marks": q.marks,
                "is_skipped": f"marks_{student.id}_{q.id}" in skipped_fields,
            })

        student_rows.append({
            "student": student,
            "marks": row_marks,
            "total": total
        })


    return render(
        request,
        "Marks/assignment_tutorial_marks.html",
        {
            "tool": tool,
            "questions": questions,
            "assignment_groups": assignment_groups,
            "student_rows": student_rows,
            "is_locked": is_locked,
        }
    )
import openpyxl
from openpyxl import Workbook
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models.functions import Cast
from django.db.models import IntegerField
@login_required
def exam_marks(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    academic_class = tool.course.academic_class
    edit_mode = request.GET.get("edit") == "1"
    is_locked = not edit_mode

    # Sort roll numbers numerically
    students = Student.objects.filter(
        academic_class=academic_class
    ).order_by("list_order", "pk")

    exam_details = sorted(
        ExamDetail.objects.filter(tool=tool),
        key=_exam_question_sort_key
    )

    marks_records = ExamMarks.objects.filter(tool=tool)

    marks_dict = {}

    for m in marks_records:
        marks_dict.setdefault(m.student_id, {})[m.question_id] = m.marks


    # =================================================
    # POST REQUEST
    # =================================================

    if request.method == "POST":

        if "edit_mode" in request.POST:
            return redirect(f"{request.path}?edit=1")

        # ================= SAVE MARKS =================

        if "save_marks" in request.POST:

            for student in students:
                for q in exam_details:

                    field = f"marks_{student.id}_{q.id}"
                    val = request.POST.get(field)

                    # Important logic
                    if val == "" or val is None:
                        marks_value = None
                    else:
                        marks_value = int(val)
                        if marks_value > q.marks:
                            messages.error(
                                request,
                                f"{student.roll_no} - {q.question_no}: marks cannot exceed {q.marks}"
                            )
                            return redirect(f"{request.path}?edit=1")

                    ExamMarks.objects.update_or_create(
                        tool=tool,
                        student=student,
                        question=q,
                        defaults={"marks": marks_value}
                    )

            messages.success(request, "Marks saved successfully")

            return redirect("exam_marks", tool_id=tool.id)


        # ================= EXPORT EXCEL =================

        if "export_excel" in request.POST:

            wb = Workbook()
            ws = wb.active
            ws.title = "Exam Marks"

            exam_title = tool.sub_tool or tool.main_tool
            exam_header = ["", "", exam_title]
            if len(exam_details) > 1:
                exam_header.extend([""] * (len(exam_details) - 1))
            exam_header.append("")
            ws.append(exam_header)
            if exam_details:
                ws.merge_cells(
                    start_row=1,
                    start_column=3,
                    end_row=1,
                    end_column=2 + len(exam_details),
                )

            co_headers = ["Roll No", "Student Name"]
            co_headers.extend(
                f"CO{q.co.co_number}" if q.co else "No CO"
                for q in exam_details
            )
            co_headers.append("Total")
            ws.append(co_headers)

            max_marks_row = ["Max Marks", ""]
            max_marks_row.extend(q.marks for q in exam_details)
            max_marks_row.append("-")
            ws.append(max_marks_row)

            for student in students:
                row = [student.roll_no, student.name]
                total = 0
                effective_question_ids = _effective_exam_detail_ids(
                    exam_details,
                    marks_dict.get(student.id, {}),
                )

                for q in exam_details:
                    mark = marks_dict.get(student.id, {}).get(q.id)
                    if mark is None:
                        mark = ""
                    elif q.id in effective_question_ids:
                        total += mark
                    row.append(mark)

                row.append(total)
                ws.append(row)

            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            response["Content-Disposition"] = "attachment; filename=exam_marks.xlsx"

            wb.save(response)

            return response


        # ================= IMPORT EXCEL =================

        if "import_excel" in request.POST:

            excel_file = request.FILES.get("excel_file")
            skipped_fields = []

            if not excel_file:
                messages.error(request, "Upload Excel file")
                return redirect("exam_marks", tool_id=tool.id)

            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active
            skipped_cells = 0

            first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            second_row = next(ws.iter_rows(min_row=2, max_row=2, values_only=True), ())
            third_row = next(ws.iter_rows(min_row=3, max_row=3, values_only=True), ())
            exam_title = tool.sub_tool or tool.main_tool
            has_exam_title = (
                len(first_row) > 2
                and first_row[2] in {
                    exam_title,
                    f"{tool.main_tool} - {tool.sub_tool}",
                }
            )
            has_co_only_header = (
                has_exam_title
                and len(second_row) > 1
                and second_row[0] == "Roll No"
                and third_row[0] == "Max Marks"
            )
            has_legacy_co_header = any(
                value == "CO"
                for value in (second_row[:3] if has_exam_title else first_row[:3])
            ) and any(
                q.question_no in (third_row if has_exam_title else second_row)
                for q in exam_details
            )
            if has_co_only_header:
                data_start_row = 4
                question_columns = {
                    question.question_no: index + 2
                    for index, question in enumerate(exam_details)
                }
            else:
                question_header_row = (
                    third_row
                    if has_exam_title
                    else second_row if has_legacy_co_header else first_row
                )
                data_start_row = (
                    5 if has_exam_title and has_legacy_co_header
                    else 4 if has_legacy_co_header
                    else 2
                )
                question_columns = {
                    value: index
                    for index, value in enumerate(question_header_row)
                    if value in {q.question_no for q in exam_details}
                }

            for row in ws.iter_rows(min_row=data_start_row, values_only=True):

                roll_no = row[0]

                if roll_no is None or str(roll_no).strip() in {"", "Max Marks"}:
                    continue

                student = Student.objects.filter(
                    roll_no=str(roll_no),
                    academic_class=academic_class
                ).first()

                if not student:
                    continue

                for q in exam_details:
                    column = question_columns.get(q.question_no)
                    mark = row[column] if column is not None and column < len(row) else None

                    if mark == "" or mark is None:
                        marks_value = None
                    else:
                        marks_value = int(mark)
                        if marks_value < 0 or marks_value > q.marks:
                            skipped_cells += 1
                            skipped_fields.append(f"marks_{student.id}_{q.id}")
                            continue

                    ExamMarks.objects.update_or_create(
                        tool=tool,
                        student=student,
                        question=q,
                        defaults={"marks": marks_value}
                    )

            if skipped_cells:
                request.session[f"skipped_exam_marks_{tool.id}"] = skipped_fields
                messages.warning(request, f"Excel imported. {skipped_cells} marks were skipped because they are negative or exceed max marks.")
            else:
                request.session.pop(f"skipped_exam_marks_{tool.id}", None)
                messages.success(request, "Excel imported successfully")

            return redirect("exam_marks", tool_id=tool.id)


    # =================================================
    # PREPARE TABLE DATA
    # =================================================

    student_rows = []
    skipped_fields = set(request.session.pop(f"skipped_exam_marks_{tool.id}", [])) if hasattr(request, "session") else set()

    for student in students:

        row_marks = []
        total = 0
        effective_question_ids = _effective_exam_detail_ids(
            exam_details,
            marks_dict.get(student.id, {})
        )

        for q in exam_details:

            mark = marks_dict.get(student.id, {}).get(q.id)

            if mark is None:
                display_mark = ""
            else:
                display_mark = mark
                if q.id in effective_question_ids:
                    total += mark

            row_marks.append({
                "q_id": q.id,
                "mark": display_mark,
                "max_marks": q.marks,
                "is_skipped": f"marks_{student.id}_{q.id}" in skipped_fields,
            })

        student_rows.append({
            "student": student,
            "marks": row_marks,
            "total": total
        })


    return render(
        request,
        "Marks/exam_marks.html",
        {
            "tool": tool,
            "exam_details": exam_details,
            "student_rows": student_rows,
            "is_locked": is_locked,
        }
    )


from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.db.models import Sum

@login_required
def assessment_pattern(request, course_id, *, return_report_context=False):

    course = get_object_or_404(Course, id=course_id)

    if request.user.role == "FACULTY" and course.faculty != request.user:
        return HttpResponseForbidden("Not authorized")
    if request.user.role == "HOD" and course.academic_class.department != request.user.department:
        return HttpResponseForbidden("Not authorized")

    tools = AssessmentTool.objects.filter(course=course)

    # ----------------------------
    # GROUP COLUMNS
    # ----------------------------
    grouped_columns = {}

    for tool in tools:

        main = tool.main_tool
        sub = tool.sub_tool

        # ❌ Skip ESE tools
        if main.strip().upper() == "ESE":
            continue

        if main not in grouped_columns:
            grouped_columns[main] = []

        grouped_columns[main].append({
            "key": f"tool_{tool.id}",
            "sub": sub if sub else main,
            "tool": tool
        })
    # ----------------------------
    # CO TABLE
    # ----------------------------
    cos = CourseOutcome.objects.filter(course=course).order_by("co_number")

    co_table = {}

    for co in cos:

        row = {}
        total = 0

        for main, cols in grouped_columns.items():

            for col in cols:

                tool = col["tool"]
                key = col["key"]

                marks = 0

                marks += ExamDetail.objects.filter(
                    tool=tool,
                    co=co
                ).aggregate(Sum("marks"))["marks__sum"] or 0

                marks += AssignmentTool.objects.filter(
                    tool=tool,
                    co=co
                ).aggregate(Sum("marks"))["marks__sum"] or 0

                marks += IcaAssignmentExp.objects.filter(
                    tool=tool,
                    co=co
                ).aggregate(Sum("marks"))["marks__sum"] or 0

                if tool.main_tool.strip().lower() == "mock oral":
                    marks += UniversityExam.objects.filter(
                        tool=tool,
                        co=co,
                    ).aggregate(Sum("marks"))["marks__sum"] or 0

                row[key] = marks
                total += marks

        row["TOTAL"] = total
        co_table[f"CO{co.co_number}"] = row

    # ----------------------------
    # BLOOM TABLE
    # ----------------------------
    bl_levels = {
        "Remember": "BL1",
        "Understanding": "BL2",
        "Apply": "BL3",
        "Analyse": "BL4",
        "Evaluate": "BL5",
        "Create": "BL6",
    }

    bl_table = {}

    for name, bl in bl_levels.items():

        row = {}
        total = 0

        for main, cols in grouped_columns.items():

            for col in cols:

                tool = col["tool"]
                key = col["key"]

                marks = 0

                marks += ExamDetail.objects.filter(
                    tool=tool,
                    bl=bl
                ).aggregate(Sum("marks"))["marks__sum"] or 0

                marks += AssignmentTool.objects.filter(
                    tool=tool,
                    bl=bl
                ).aggregate(Sum("marks"))["marks__sum"] or 0

                marks += IcaAssignmentExp.objects.filter(
                    tool=tool,
                    bl=bl
                ).aggregate(Sum("marks"))["marks__sum"] or 0

                row[key] = marks
                total += marks

        row["TOTAL"] = total
        bl_table[name] = row

    # ----------------------------
    # CO CHART
    # ----------------------------
    co_chart = None
    bl_chart = None

    if plt is not None:
        labels = list(co_table.keys())
        values = [co_table[c]["TOTAL"] for c in labels]

        fig, ax = plt.subplots()
        bars = ax.bar(labels, values)
        ax.bar_label(bars, fmt="%.2f", padding=3)
        ax.set_title("CO Wise Marks")
        ax.margins(y=0.12)
        fig.tight_layout()

        buffer = io.BytesIO()
        plt.savefig(buffer, format="png")
        buffer.seek(0)

        co_chart = base64.b64encode(buffer.getvalue()).decode()
        buffer.close()
        plt.close()

    # ----------------------------
    # BL CHART
    # ----------------------------
        labels = list(bl_table.keys())
        values = [bl_table[b]["TOTAL"] for b in labels]

        fig, ax = plt.subplots(figsize=(8,4))

        bars = ax.bar(labels, values)
        ax.bar_label(bars, fmt="%.2f", padding=3)

        ax.set_title("Bloom Level Distribution")
        ax.margins(y=0.12)

        # Rotate labels 30 degrees
        plt.xticks(rotation=30, ha="right")

        # Prevent label cut-off
        plt.tight_layout()

        buffer = io.BytesIO()
        plt.savefig(buffer, format="png")
        buffer.seek(0)

        bl_chart = base64.b64encode(buffer.getvalue()).decode()

        buffer.close()
        plt.close()

    # ----------------------------
    # CONTEXT
    # ----------------------------
    context = {
        "course": course,
        "cos": list(cos),
        "tools": list(tools),
        "grouped_columns": grouped_columns,
        "co_table": co_table,
        "bl_table": bl_table,
        "charts_available": plt is not None,
        "co_chart": co_chart,
        "bl_chart": bl_chart,
    }

    if return_report_context:
        return context

    return render(
        request,
        "reports/assessment_pattern.html",
        context
    )

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Max
from .models import Course, CourseOutcome, COTarget, AttainmentWeightage, CourseExitSurvey


@login_required
def co_target_page(request, course_id):

    course = get_object_or_404(Course, id=course_id)

    if request.user.role == "FACULTY" and course.faculty != request.user:
        return HttpResponseForbidden("Not authorized")
    if request.user.role == "HOD" and course.academic_class.department != request.user.department:
        return HttpResponseForbidden("Not authorized")

    cos = CourseOutcome.objects.filter(
        course=course
    ).order_by("co_number")

    existing_targets = {
        t.course_outcome_id: t
        for t in COTarget.objects.filter(course=course)
    }

    weightage, created = AttainmentWeightage.objects.get_or_create(
        course=course
    )

    bl_levels = ["BL1", "BL2", "BL3", "BL4", "BL5", "BL6"]

    if request.method == "POST":
        weightage_fields = (
            "direct_attainment",
            "indirect_attainment",
            "cie_weightage",
            "ese_weightage",
        )
        submitted_weightage = {}
        invalid_weightage = False

        for field in weightage_fields:
            raw_value = request.POST.get(field, "").strip()
            try:
                value = int(raw_value)
            except ValueError:
                messages.error(request, "Enter a whole-number weight for every attainment field.")
                invalid_weightage = True
                continue

            if not 0 <= value <= 100:
                messages.error(request, "Attainment weights must be between 0 and 100.")
                invalid_weightage = True
                continue

            submitted_weightage[field] = value

        if not invalid_weightage and (
            submitted_weightage["direct_attainment"]
            + submitted_weightage["indirect_attainment"] != 100
        ):
            messages.error(request, "Direct and indirect attainment weights must add up to 100%.")
            invalid_weightage = True

        if not invalid_weightage and (
            submitted_weightage["cie_weightage"]
            + submitted_weightage["ese_weightage"] != 100
        ):
            messages.error(request, "CIE and ESE weights must add up to 100% of direct attainment.")
            invalid_weightage = True

        if invalid_weightage:
            return redirect("co_target_page", course_id=course.id)

        for field, value in submitted_weightage.items():
            setattr(weightage, field, value)

        # Course Exit Survey is the complete indirect-attainment component.
        weightage.survey_weightage = weightage.indirect_attainment

        weightage.save()

        # SAVE CO TARGET

        for co in cos:

            target = request.POST.get(f"target_{co.id}")
            bl = request.POST.get(f"bl_{co.id}")

            if not target:
                continue

            COTarget.objects.update_or_create(
                course=course,
                course_outcome=co,
                defaults={
                    "target_percentage": int(target),
                    "bl_level": bl
                }
            )

        messages.success(request, "CO Targets saved successfully")

        return redirect("co_target_page", course_id=course.id)

    return render(
        request,
        "reports/set_co_targets.html",
        {
            "course": course,
            "cos": cos,
            "existing_targets": existing_targets,
            "weightage": weightage,
            "bl_levels": bl_levels
        }
    )

@login_required
def course_exit_survey(request, course_id):

    course = get_object_or_404(Course, id=course_id)

    if request.user.role == "FACULTY" and course.faculty != request.user:
        return HttpResponseForbidden("Not authorized")
    if request.user.role == "HOD" and course.academic_class.department != request.user.department:
        return HttpResponseForbidden("Not authorized")

    cos = CourseOutcome.objects.filter(course=course).order_by("co_number")
    saved_records = {
        record.course_outcome_id: record
        for record in CourseExitSurvey.objects.filter(course=course)
    }
    edit_mode = request.GET.get("edit") == "1"
    is_locked = bool(saved_records) and not edit_mode

    def clean_survey_question(text, co):
        question = (text or co.description or "").strip()
        prefix = "Are you able to:"

        if question.lower().startswith(prefix.lower()):
            question = question[len(prefix):].strip()

        return question

    if request.method == "POST":

        if "export_excel" in request.POST:

            wb = Workbook()
            ws = wb.active
            ws.title = "Course Exit Survey"
            ws.append([
                "CO No",
                "Question",
                "Strongly Agree (5)",
                "Agree (4)",
                "Neutral (3)",
                "Disagree (2)",
                "Strongly Disagree (1)",
                "Average",
                "Percentage",
            ])

            for co in cos:
                record = saved_records.get(co.id)
                strongly_agree = record.strongly_agree if record else 0
                agree = record.agree if record else 0
                neutral = record.neutral if record else 0
                disagree = record.disagree if record else 0
                strongly_disagree = record.strongly_disagree if record else 0
                total = strongly_agree + agree + neutral + disagree + strongly_disagree
                weighted_total = (
                    strongly_agree * 5
                    + agree * 4
                    + neutral * 3
                    + disagree * 2
                    + strongly_disagree
                )
                average = weighted_total / total if total else 0

                ws.append([
                    f"CO{co.co_number}",
                    clean_survey_question(record.question_text if record else "", co),
                    strongly_agree,
                    agree,
                    neutral,
                    disagree,
                    strongly_disagree,
                    round(average, 9) if average else "",
                    round(average * 20, 4) if average else "",
                ])

            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = f'attachment; filename="course_exit_survey_{course.course_code}.xlsx"'
            wb.save(response)
            return response

        if "import_excel" in request.POST:

            excel_file = request.FILES.get("excel_file")

            if not excel_file:
                messages.error(request, "Upload Excel file")
                return redirect("course_exit_survey", course_id=course.id)

            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active

            for row in ws.iter_rows(min_row=2, values_only=True):

                co_label, question, strongly_agree, agree, neutral, disagree, strongly_disagree = (list(row) + [None] * 7)[:7]

                if not co_label:
                    continue

                co_number = str(co_label).upper().replace("CO", "").strip()

                if not co_number.isdigit():
                    continue

                co = CourseOutcome.objects.filter(
                    course=course,
                    co_number=int(co_number)
                ).first()

                if not co:
                    continue

                CourseExitSurvey.objects.update_or_create(
                    course=course,
                    course_outcome=co,
                    defaults={
                        "question_text": co.description,
                        "strongly_agree": int(strongly_agree or 0),
                        "agree": int(agree or 0),
                        "neutral": int(neutral or 0),
                        "disagree": int(disagree or 0),
                        "strongly_disagree": int(strongly_disagree or 0),
                    }
                )

            messages.success(request, "Course Exit Survey imported successfully")
            return redirect("course_exit_survey", course_id=course.id)

        for co in cos:
            default_question = co.description
            question_text = clean_survey_question(
                request.POST.get(f"question_{co.id}") or default_question,
                co
            )

            CourseExitSurvey.objects.update_or_create(
                course=course,
                course_outcome=co,
                defaults={
                    "question_text": question_text,
                    "strongly_agree": int(request.POST.get(f"strongly_agree_{co.id}") or 0),
                    "agree": int(request.POST.get(f"agree_{co.id}") or 0),
                    "neutral": int(request.POST.get(f"neutral_{co.id}") or 0),
                    "disagree": int(request.POST.get(f"disagree_{co.id}") or 0),
                    "strongly_disagree": int(request.POST.get(f"strongly_disagree_{co.id}") or 0),
                }
            )

        messages.success(request, "Course Exit Survey saved successfully")
        return redirect("course_exit_survey", course_id=course.id)

    rows = []

    for co in cos:
        record = saved_records.get(co.id)

        strongly_agree = record.strongly_agree if record else 0
        agree = record.agree if record else 0
        neutral = record.neutral if record else 0
        disagree = record.disagree if record else 0
        strongly_disagree = record.strongly_disagree if record else 0
        total = strongly_agree + agree + neutral + disagree + strongly_disagree
        weighted_total = (
            strongly_agree * 5
            + agree * 4
            + neutral * 3
            + disagree * 2
            + strongly_disagree
        )
        average = weighted_total / total if total else 0

        rows.append({
            "co": co,
            "question_text": clean_survey_question(record.question_text if record else "", co),
            "strongly_agree": strongly_agree,
            "agree": agree,
            "neutral": neutral,
            "disagree": disagree,
            "strongly_disagree": strongly_disagree,
            "average": round(average, 9) if average else "",
            "percentage": round(average * 20, 4) if average else "",
            "total": total,
        })

    submitted_answers = max([row["total"] for row in rows], default=0)

    return render(
        request,
        "reports/course_exit_survey.html",
        {
            "course": course,
            "rows": rows,
            "submitted_answers": submitted_answers,
            "is_locked": is_locked,
        }
    )

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseForbidden
from django.db.models import Avg, IntegerField
from django.db.models.functions import Cast
from collections import defaultdict

from .models import (
    AssessmentTool, Student,
    IcaStudentMarks, AssignmentTutorialMarks, ExamMarks,
    IcaAssignmentExp, AssignmentTool, ExamDetail,
    UniversityExam, UniversityExamMarks,
    CourseExitSurvey, COTarget, COQualityLoop, AttainmentLevelThreshold,
    COPOMapping, COPSOMapping
)


@login_required
def tool_marks_co_summary(request, tool_id):

    tool = get_object_or_404(AssessmentTool, id=tool_id)
    course = tool.course
    academic_class = course.academic_class

    if not (request.user == course.faculty or request.user.role == "HOD"):
        return HttpResponseForbidden("Not authorized")

    students = Student.objects.filter(
        academic_class=academic_class
    ).order_by("list_order", "pk")

    # ----------------------------
    # Detect tool type
    # ----------------------------
    sub_items = []
    marks_model = None
    sub_field = None
    merge_by_co = False
    merge_by_co_direct = False
    distribute_student_total = False
    exam_solve_any = False
    selected_exam_max_ids = set()

    if tool.main_tool.lower() in ["ica", "experiment", "practical"]:
        sub_items = IcaAssignmentExp.objects.filter(tool=tool).order_by("sub_tool_no")
        marks_model = IcaStudentMarks
        sub_field = "subtool"

    elif tool.main_tool.lower() in ["ise assignment", "assignment", "tutorial"]:
        sub_items = AssignmentTool.objects.filter(tool=tool).order_by("question_no")
        marks_model = AssignmentTutorialMarks
        sub_field = "question"
        merge_by_co = True

    elif tool.main_tool.lower() in ["ese", "university exam theory", "mock oral"]:
        sub_items = UniversityExam.objects.filter(tool=tool).select_related("co").order_by("co__co_number")
        marks_model = UniversityExamMarks
        distribute_student_total = True

    elif tool.main_tool.lower() in ["ise exam", "ut1", "ut2", "ut3", "prelim", "exam"]:
        sub_items = sorted(
            ExamDetail.objects.filter(tool=tool),
            key=_exam_question_sort_key
        )
        selected_exam_max_ids = _effective_exam_detail_ids(sub_items)
        marks_model = ExamMarks
        sub_field = "question"
        merge_by_co_direct = True
        exam_solve_any = True

    else:
        return render(request, "errors/unsupported_tool.html", {"tool": tool})

    # ----------------------------
    # Build Columns
    # ----------------------------
    columns = []

    if distribute_student_total:
        columns.append({
            "co": None,
            "label": "Total",
            "max_marks": sum(item.marks or 0 for item in sub_items),
            "sub_items": sub_items,
        })

    elif merge_by_co:

        subtool_groups = defaultdict(list)

        for item in sub_items:
            key = item.question_no.split('.')[0]
            subtool_groups[key].append(item)

        for subtool_key, items in subtool_groups.items():

            co_groups = defaultdict(list)

            for item in items:
                co_groups[item.co].append(item)

            for co, co_items in co_groups.items():

                assignment_match = re.fullmatch(
                    r"A(\d+)",
                    subtool_key,
                    re.IGNORECASE,
                )
                assignment_label = (
                    f"{tool.sub_tool} {assignment_match.group(1)}"
                    if assignment_match
                    else subtool_key
                )
                label = (
                    f"{assignment_label} - CO{co.co_number}"
                    if co
                    else f"{assignment_label} - No CO"
                )

                max_marks = sum(i.marks or 0 for i in co_items)

                columns.append({
                    "co": co,
                    "label": label,
                    "max_marks": max_marks,
                    "sub_items": co_items
                })

    elif merge_by_co_direct:

        co_groups = defaultdict(list)

        for item in sub_items:
            co_groups[item.co].append(item)

        for co, items in co_groups.items():

            label = f"CO{co.co_number}" if co else "No CO"
            max_marks = sum(
                i.marks or 0
                for i in items
                if not selected_exam_max_ids or i.id in selected_exam_max_ids
            )

            columns.append({
                "co": co,
                "label": label,
                "max_marks": max_marks,
                "sub_items": items
            })

    else:

        for item in sub_items:

            label = (
                f"{tool.sub_tool} {item.sub_tool_no} - CO{item.co.co_number}"
                if item.co
                else f"{tool.sub_tool} {item.sub_tool_no} - No CO"
            )

            columns.append({
                "co": item.co,
                "label": label,
                "max_marks": item.marks or 0,
                "sub_items": [item]
            })

    # ----------------------------
    # Targets
    # ----------------------------
    targets = {
        t.course_outcome_id: t.target_percentage
        for t in COTarget.objects.filter(course=course)
    }

    # ----------------------------
    # Student Rows
    # ----------------------------
    student_data = []

    for student in students:

        row_marks = []
        total = 0

        if distribute_student_total:

            mark_obj = marks_model.objects.filter(
                tool=tool,
                student=student,
            ).first()

            if mark_obj and mark_obj.marks is not None:
                row_marks = [mark_obj.marks]
                total = mark_obj.marks
            else:
                row_marks = ["-"]

            student_data.append({
                "roll_no": student.roll_no,
                "name": student.name,
                "marks": row_marks,
                "total_obtained": total
            })

            continue

        effective_question_ids = set()

        if exam_solve_any:
            student_exam_marks = {
                mark.question_id: mark.marks
                for mark in ExamMarks.objects.filter(
                    tool=tool,
                    student=student,
                    marks__isnull=False
                )
            }
            effective_question_ids = _effective_exam_detail_ids(sub_items, student_exam_marks)

        for col in columns:

            merged = 0
            valid = False

            for item in col["sub_items"]:

                if exam_solve_any and item.id not in effective_question_ids:
                    continue

                mark_obj = marks_model.objects.filter(
                    tool=tool,
                    student=student,
                    **{sub_field: item.id}
                ).first()

                if mark_obj and mark_obj.marks is not None:
                    merged += mark_obj.marks
                    valid = True

            value = merged if valid else "-"
            row_marks.append(value)

            if valid:
                total += merged

        student_data.append({
            "roll_no": student.roll_no,
            "name": student.name,
            "marks": row_marks,
            "total_obtained": total
        })

    # ----------------------------
    # Summary Rows
    # ----------------------------
    summary_rows = []

    attempted = []

    for col in columns:

        count = 0

        if distribute_student_total:

            count = marks_model.objects.filter(
                tool=tool,
                marks__isnull=False
            ).count()

        else:

            for student in students:

                effective_question_ids = set()

                if exam_solve_any:
                    student_exam_marks = {
                        mark.question_id: mark.marks
                        for mark in ExamMarks.objects.filter(
                            tool=tool,
                            student=student,
                            marks__isnull=False
                        )
                    }
                    effective_question_ids = _effective_exam_detail_ids(sub_items, student_exam_marks)

                for item in col["sub_items"]:

                    if exam_solve_any and item.id not in effective_question_ids:
                        continue

                    if marks_model.objects.filter(
                        tool=tool,
                        student=student,
                        **{sub_field: item.id},
                        marks__isnull=False
                    ).exists():
                        count += 1
                        break

        attempted.append(count)

    summary_rows.append({
        "label": "No. of Students Attempted",
        "values": attempted
    })

    # Average
    avg_values = []

    for i, col in enumerate(columns):

        total_marks = 0
        count = 0

        for s in student_data:

            val = s["marks"][i]

            if val != "-":
                total_marks += val
                count += 1

        avg = total_marks / count if count else 0
        avg_values.append(round(avg, 2))

    summary_rows.append({
        "label": "Average",
        "values": avg_values
    })

    # Attainment %
    attainment = []

    for i, col in enumerate(columns):

        max_m = col["max_marks"]
        perc = (avg_values[i] / max_m * 100) if max_m else 0
        attainment.append(round(perc, 2))

    summary_rows.append({
        "label": "Attainment %",
        "values": attainment
    })

    if not distribute_student_total:
        target_values = []

        for col in columns:
            co = col["co"]
            target_values.append(targets.get(co.id, 0) if co else 0)

        summary_rows.append({
            "label": "Target %",
            "values": target_values
        })

        status = []

        for i in range(len(columns)):
            status.append(
                "Achieved" if attainment[i] >= target_values[i] and target_values[i] > 0 else "Not Achieved"
            )

        summary_rows.append({
            "label": "Status",
            "values": status
        })

    context = {
        "tool": tool,
        "course": course,
        "columns": columns,
        "students": student_data,
        "total_max": sum(col["max_marks"] for col in columns),
        "summary_rows": summary_rows
    }

    return render(request, "reports/tool_marks_co_summary.html", context)

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponseForbidden
from django.db.models import Sum, Avg


def _build_co_po_pso_docx_response(course, report_data):
    import struct

    from docx import Document
    from docx.enum.section import WD_ORIENT, WD_SECTION
    from docx.enum.table import (
        WD_CELL_VERTICAL_ALIGNMENT,
        WD_ROW_HEIGHT_RULE,
        WD_TABLE_ALIGNMENT,
    )
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    rows = report_data["po_pso_attainment_rows"]
    thresholds = report_data["attainment_thresholds"]
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.top_margin = Inches(1.85)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)
    section.header_distance = Inches(0.08)

    normal_style = document.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style.font.size = Pt(9)
    normal_style.font.color.rgb = RGBColor(20, 20, 20)

    def shade_cell(cell, fill):
        properties = cell._tc.get_or_add_tcPr()
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), fill)
        properties.append(shading)

    def set_cell(
        cell,
        text,
        *,
        bold=False,
        fill=None,
        size=9,
        alignment=WD_ALIGN_PARAGRAPH.CENTER,
        no_wrap=False,
    ):
        cell.text = "" if text is None else str(text)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        if fill:
            shade_cell(cell, fill)
        if no_wrap:
            cell_properties = cell._tc.get_or_add_tcPr()
            no_wrap_element = OxmlElement("w:noWrap")
            no_wrap_element.set(qn("w:val"), "true")
            cell_properties.append(no_wrap_element)
        for paragraph in cell.paragraphs:
            paragraph.alignment = alignment
            paragraph.paragraph_format.space_before = Pt(3)
            paragraph.paragraph_format.space_after = Pt(3)
            for run in paragraph.runs:
                run.font.name = "Times New Roman"
                run.font.size = Pt(size)
                run.font.bold = bold

    def add_section_heading(text, *, new_page=True, level=1):
        if new_page:
            document.add_page_break()
        paragraph = document.add_heading(text, level=level)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = Pt(3)
        paragraph.paragraph_format.space_after = Pt(6)
        for run in paragraph.runs:
            run.font.name = "Times New Roman"
            run.font.color.rgb = RGBColor(31, 50, 76)
        return paragraph

    def add_report_table(headers, rows, *, widths=None, font_size=8):
        rows = list(rows)
        table = document.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        total_width = 5.8
        widths = widths or [total_width / len(headers)] * len(headers)
        requested_width = sum(widths)
        if requested_width > total_width:
            width_scale = total_width / requested_width
            widths = [width * width_scale for width in widths]

        table.rows[0].height = Inches(0.42)
        table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for column_index, (header, width) in enumerate(zip(headers, widths)):
            table.columns[column_index].width = Inches(width)
            table.rows[0].cells[column_index].width = Inches(width)
            set_cell(
                table.rows[0].cells[column_index],
                header,
                bold=True,
                fill="FFFFFF",
                size=font_size,
            )

        header_properties = table.rows[0]._tr.get_or_add_trPr()
        repeat_header = OxmlElement("w:tblHeader")
        repeat_header.set(qn("w:val"), "true")
        header_properties.append(repeat_header)

        for row_values in rows:
            row = table.add_row()
            row.height = Inches(0.38)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            cells = row.cells
            for column_index, (cell, value, width) in enumerate(zip(cells, row_values, widths)):
                cell.width = Inches(width)
                set_cell(
                    cell,
                    value,
                    bold=column_index == 0,
                    fill="FFFFFF",
                    size=font_size,
                    alignment=WD_ALIGN_PARAGRAPH.LEFT if column_index == 1 else WD_ALIGN_PARAGRAPH.CENTER,
                )
        return table

    def add_unavailable_section(title, detail):
        add_section_heading(title, level=2)
        paragraph = document.add_paragraph(detail)
        paragraph.paragraph_format.space_after = Pt(4)
        for run in paragraph.runs:
            run.font.italic = True
            run.font.color.rgb = RGBColor(100, 100, 100)

    def format_header_paragraph(paragraph, *, alignment=WD_ALIGN_PARAGRAPH.CENTER):
        paragraph.alignment = alignment
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1

    def add_header_line(cell, text, *, size, color, bold=True, font="Arial"):
        paragraph = cell.paragraphs[0] if not cell.paragraphs[0].text else cell.add_paragraph()
        format_header_paragraph(paragraph)
        run = paragraph.add_run(text)
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor(*color)

    def set_table_bottom_border(table, *, size):
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            border = OxmlElement(f"w:{edge}")
            border.set(qn("w:val"), "single" if edge == "bottom" else "nil")
            if edge == "bottom":
                border.set(qn("w:sz"), str(size))
                border.set(qn("w:color"), "000000")
            borders.append(border)
        table._tbl.tblPr.append(borders)

    department = course.academic_class.department
    department_display_name = (
        department.report_department_name.strip()
        or f"Department of {department.name}"
    )
    college_settings, _ = CollegeReportSettings.objects.get_or_create(pk=1)
    official_details = (
        ("Dr. K. J. Karande", "M. Tech., Ph.D. (E&TC Engg.)", "PRINCIPAL"),
        (department.report_hod_name, department.report_hod_qualification, "HOD"),
    )

    def add_institution_header(header, *, table_width, logo_width, scale):
        header.paragraphs[0].paragraph_format.space_after = Pt(0)
        header.paragraphs[0].paragraph_format.line_spacing = 1
        text_width = table_width - logo_width
        header_table = header.add_table(rows=1, cols=2, width=Inches(table_width))
        header_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        header_table.autofit = False
        header_table.columns[0].width = Inches(logo_width)
        header_table.columns[1].width = Inches(text_width)
        header_logo_cell, header_text_cell = header_table.rows[0].cells
        header_logo_cell.width = Inches(logo_width)
        header_text_cell.width = Inches(text_width)
        header_logo_paragraph = header_logo_cell.paragraphs[0]
        format_header_paragraph(header_logo_paragraph)
        header_logo_paragraph.paragraph_format.space_before = Pt(20 * scale)
        header_logo_paragraph.add_run().add_picture(
            str(Path(__file__).resolve().parent / "static" / "accounts" / "images" / "spspm-logo.png"),
            width=Inches(1.2 * scale),
        )

        def add_scaled_line(text, size, color, *, bold=True, font="Arial"):
            add_header_line(
                header_text_cell,
                text,
                size=max(7, round(size * scale)),
                color=color,
                bold=bold,
                font=font,
            )

        add_scaled_line("Savitribai Phule Shikshan Prasarak Mandal’s", 15, (0, 0, 0))
        add_scaled_line("SKN SINHGAD COLLEGE OF ENGINEERING", 25, (204, 0, 0))
        add_scaled_line(
            "(Approved by AICTE & Affiliated to PAH Solapur University, Solapur)",
            14,
            (0, 0, 0),
        )
        add_scaled_line("Accredited with ‘A+’ Grade by NAAC", 15, (204, 0, 0))
        add_scaled_line(
            "A/p- Korti, Tal- Pandharpur, Pin- 413304, Dist.- Solapur.",
            14,
            (0, 0, 0),
            bold=False,
        )
        add_scaled_line(
            department_display_name,
            24,
            (204, 0, 0),
            font="Times New Roman",
        )
        if department.report_accreditation:
            add_scaled_line(department.report_accreditation, 15, (204, 0, 0))
        if department.report_email or college_settings.website:
            contact_paragraph = header_text_cell.add_paragraph()
            format_header_paragraph(contact_paragraph)
            contact_items = []
            if department.report_email:
                contact_items.extend((
                    ("e-mail: ", (0, 0, 0), True),
                    (department.report_email, (5, 99, 193), False),
                ))
            if college_settings.website:
                if contact_items:
                    contact_items.append(("   ", (0, 0, 0), False))
                contact_items.extend((
                    ("Website: ", (0, 0, 0), True),
                    (college_settings.website, (5, 99, 193), False),
                ))
            for text, color, bold in contact_items:
                run = contact_paragraph.add_run(text)
                run.font.name = "Arial"
                run.font.size = Pt(max(7, round(14 * scale)))
                run.font.bold = bold
                run.font.color.rgb = RGBColor(*color)
                if color == (5, 99, 193):
                    run.underline = True

        separator = header.add_paragraph()
        separator.paragraph_format.left_indent = Inches(max(0.12, (table_width - 10.0 * scale) / 2))
        separator.paragraph_format.right_indent = separator.paragraph_format.left_indent
        separator.paragraph_format.space_before = Pt(0)
        separator.paragraph_format.space_after = Pt(7 * scale)
        separator.paragraph_format.line_spacing = Pt(1)
        separator_run = separator.add_run()
        separator_run.font.size = Pt(1)
        separator_properties = separator._p.get_or_add_pPr()
        separator_borders = OxmlElement("w:pBdr")
        separator_border = OxmlElement("w:bottom")
        separator_border.set(qn("w:val"), "single")
        separator_border.set(qn("w:sz"), "18")
        separator_border.set(qn("w:space"), "1")
        separator_border.set(qn("w:color"), "000000")
        separator_borders.append(separator_border)
        separator_properties.append(separator_borders)

        officials_table = header.add_table(rows=1, cols=2, width=Inches(table_width))
        officials_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        officials_table.autofit = False
        officials_table.columns[0].width = Inches(table_width / 2)
        officials_table.columns[1].width = Inches(table_width / 2)
        for column, details in enumerate(official_details):
            officials_cell = officials_table.cell(0, column)
            for index, detail in enumerate(details):
                paragraph = officials_cell.paragraphs[0] if index == 0 else officials_cell.add_paragraph()
                format_header_paragraph(paragraph)
                run = paragraph.add_run(detail)
                run.font.name = "Times New Roman"
                run.font.size = Pt(max(7, round((13 if index == 1 else 15) * scale)))
                run.font.bold = index != 1
                run.font.color.rgb = RGBColor(204, 0, 0) if index == 0 else RGBColor(0, 0, 0)
        set_table_bottom_border(officials_table, size=18)

    add_institution_header(
        section.header,
        table_width=6.97,
        logo_width=0.95,
        scale=0.75,
    )

    def add_bar_chart(
        title,
        labels,
        values,
        *,
        color="#ED7D31",
        y_label="MARKS",
        figsize=(6.3, 2.8),
        image_width=6.5,
        label_rotation=0,
        tick_font_size=7,
    ):
        if plt is None or not labels:
            document.add_paragraph(f"{title}: chart data unavailable.")
            return
        figure, axis = plt.subplots(figsize=figsize)
        bars = axis.bar(labels, values, color=color, edgecolor="#333333", linewidth=0.6)
        axis.bar_label(bars, fmt="%.2f", padding=3)
        axis.set_title(title, fontsize=9, pad=6)
        axis.set_ylabel(y_label, fontsize=7)
        axis.set_xlabel(
            "COURSE OUTCOMES" if labels and labels[0].startswith("CO") else "COGNITIVE LEVEL",
            fontsize=7,
            labelpad=3,
        )
        axis.tick_params(axis="x", labelsize=tick_font_size, pad=2)
        axis.tick_params(axis="y", labelsize=6, pad=2)
        if label_rotation:
            axis.tick_params(axis="x", labelrotation=label_rotation)
            for tick in axis.get_xticklabels():
                tick.set_horizontalalignment("right")
        axis.grid(axis="y", color="#D9D9D9", linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        figure.tight_layout()
        image_buffer = io.BytesIO()
        figure.savefig(image_buffer, format="png", dpi=160, bbox_inches="tight")
        plt.close(figure)
        image_buffer.seek(0)
        document.add_picture(image_buffer, width=Inches(image_width))

    def add_gap_chart(gap_rows):
        chart_rows = [row for row in gap_rows if row["target"] is not None]
        if plt is None or not chart_rows:
            document.add_paragraph("CO Attainment Gap chart data unavailable.")
            return
        labels = [row["co"] for row in chart_rows]
        target_values = [row["target"] for row in chart_rows]
        attainment_values = [row["attainment"] for row in chart_rows]
        positions = list(range(len(labels)))
        width = 0.36
        figure, axis = plt.subplots(figsize=(6.3, 3.0))
        targets = axis.bar(
            [position - width / 2 for position in positions],
            target_values,
            width,
            label="Target",
            color="#5B9BD5",
        )
        attainments = axis.bar(
            [position + width / 2 for position in positions],
            attainment_values,
            width,
            label="CO Attainment",
            color="#ED7D31",
        )
        axis.bar_label(targets, padding=3, fontsize=9)
        axis.bar_label(attainments, padding=3, fontsize=9)
        axis.set_title(
            "CO Attainment Gap",
            fontsize=13,
            fontweight="bold",
            color="#1F324C",
            pad=10,
        )
        axis.set_ylabel("PERCENTAGE", fontsize=9)
        axis.set_xticks(positions, labels)
        axis.set_ylim(0, 105)
        axis.grid(axis="y", color="#D9D9D9", linewidth=0.7)
        axis.set_axisbelow(True)
        axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        figure.tight_layout()
        image_buffer = io.BytesIO()
        figure.savefig(image_buffer, format="png", dpi=160, bbox_inches="tight")
        plt.close(figure)
        image_buffer.seek(0)
        document.add_picture(image_buffer, width=Inches(6.5))

    cover_spacing = document.add_paragraph()
    cover_spacing.paragraph_format.space_after = Pt(0)
    cover_spacing.paragraph_format.line_spacing = 1
    cover_spacing.paragraph_format.space_before = Pt(72)

    cover_table = document.add_table(rows=1, cols=1)
    cover_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cover_table.autofit = False
    cover_table.columns[0].width = Inches(6.5)
    cover_cell = cover_table.cell(0, 0)
    cover_cell.width = Inches(6.5)
    cover_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    cover_borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right"):
        border = OxmlElement(f"w:{edge}")
        border.set(qn("w:val"), "double")
        border.set(qn("w:sz"), "12")
        border.set(qn("w:space"), "5")
        border.set(qn("w:color"), "000000")
        cover_borders.append(border)
    cover_table._tbl.tblPr.append(cover_borders)
    cover_lines = (
        ("CO-PO-PSO ATTAINMENT", 17),
        (f"SUBJECT :- {course.course_name}", 16),
        (f"ACADEMIC YEAR :- {course.academic_class.academic_year}", 16),
    )
    for index, (text, size) in enumerate(cover_lines):
        paragraph = cover_cell.paragraphs[0] if index == 0 else cover_cell.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = Pt(16)
        paragraph.paragraph_format.space_after = Pt(16)
        run = paragraph.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(size)
        run.font.bold = True

    course_teacher = (
        course.faculty.get_full_name() or course.faculty.username
        if course.faculty
        else "Not configured in course data"
    )
    cover_details = document.add_paragraph()
    cover_details.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cover_details.paragraph_format.space_before = Pt(10)
    cover_details.paragraph_format.space_after = Pt(0)
    cover_details_run = cover_details.add_run(
        f"Subject Code: {course.course_code}  |  Semester: {course.academic_class.semester}"
        f"  |  Department: {course.academic_class.department.name}"
        f"  |  Subject Teacher: {course_teacher}"
    )
    cover_details_run.font.name = "Times New Roman"
    cover_details_run.font.size = Pt(9)

    information_section = document.add_section(WD_SECTION.NEW_PAGE)
    information_section.orientation = WD_ORIENT.PORTRAIT
    information_section.page_width = Inches(8.27)
    information_section.page_height = Inches(11.69)
    information_section.top_margin = Inches(1.85)
    information_section.bottom_margin = Inches(0.55)
    information_section.left_margin = Inches(0.65)
    information_section.right_margin = Inches(0.65)
    information_section.header_distance = Inches(0.08)
    information_section.header.is_linked_to_previous = False
    add_institution_header(
        information_section.header,
        table_width=6.97,
        logo_width=0.95,
        scale=0.75,
    )

    information_title = document.add_paragraph()
    information_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    information_title.paragraph_format.space_before = Pt(0)
    information_title.paragraph_format.space_after = Pt(14)
    title_run = information_title.add_run("CO-PO-PSO ATTAINMENT")
    title_run.font.name = "Times New Roman"
    title_run.font.size = Pt(15)
    title_run.font.bold = True

    information_rows = (
        ("Name of Department", department_display_name),
        ("Title of Course", course.course_name),
        ("Course Code", course.course_code),
        ("Academic year", course.academic_class.academic_year),
        ("Name of Subject Teacher", course_teacher),
    )
    information_table = document.add_table(rows=len(information_rows), cols=2)
    information_table.style = "Table Grid"
    information_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    information_table.autofit = False
    information_widths = (1.95, 3.85)
    for column, width in enumerate(information_widths):
        information_table.columns[column].width = Inches(width)
    for row_index, values in enumerate(information_rows):
        information_table.rows[row_index].height = Inches(0.55)
        information_table.rows[row_index].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for column, value in enumerate(values):
            cell = information_table.cell(row_index, column)
            cell.width = Inches(information_widths[column])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell(
                cell,
                value,
                bold=column == 0,
                size=10,
                alignment=(
                    WD_ALIGN_PARAGRAPH.CENTER
                    if column == 0
                    else WD_ALIGN_PARAGRAPH.LEFT
                ),
            )
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(12)
                paragraph.paragraph_format.space_after = Pt(12)

    report_section = document.add_section(WD_SECTION.NEW_PAGE)
    report_section.orientation = WD_ORIENT.PORTRAIT
    report_section.page_width = Inches(8.27)
    report_section.page_height = Inches(11.69)
    report_section.top_margin = Inches(1.85)
    report_section.bottom_margin = Inches(0.55)
    report_section.left_margin = Inches(0.65)
    report_section.right_margin = Inches(0.65)
    report_section.header_distance = Inches(0.08)
    report_section.header.is_linked_to_previous = False
    add_institution_header(
        report_section.header,
        table_width=6.97,
        logo_width=0.95,
        scale=0.75,
    )

    def add_course_outcomes_page():
        heading = add_section_heading("COURSE OUTCOMES (COs)", new_page=False)
        for run in heading.runs:
            run.font.name = "Times New Roman"
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(204, 0, 0)
            run.font.bold = True
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.paragraph_format.space_after = Pt(8)

        table_widths = (1.0, 1.9, 1.0, 1.9)
        information_table = document.add_table(rows=1, cols=4)
        information_table.style = "Table Grid"
        information_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        information_table.autofit = False
        for column, width in enumerate(table_widths):
            information_table.columns[column].width = Inches(width)

        institution_rows = (
            "Savitribai Phule Shikshan Prasarak Mandal's",
            "SKN Sinhgad College of Engineering, Pandharpur",
            department_display_name.upper(),
        )
        for row_index, text in enumerate(institution_rows):
            row = information_table.rows[0] if row_index == 0 else information_table.add_row()
            row.height = Inches(0.34)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            cell = row.cells[0].merge(row.cells[3])
            set_cell(
                cell,
                text,
                bold=True,
                fill="FFFFFF",
                size=9 if row_index else 8,
            )
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        course_info_row = information_table.add_row()
        course_info_row.height = Inches(0.34)
        course_info_row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        course_info_cell = course_info_row.cells[0].merge(course_info_row.cells[3])
        set_cell(
            course_info_cell,
            "Course Information",
            bold=True,
            fill="F4C7A8",
            size=9,
        )

        teacher_name = (
            course.faculty.get_full_name() or course.faculty.username
            if course.faculty
            else "Not configured"
        )
        course_info_rows = (
            ("Course Name", course.course_name, "Course Code", course.course_code),
            ("Class", course.academic_class.name, "Semester", course.academic_class.semester),
            ("Academic Year", course.academic_class.academic_year, "Subject Teacher", teacher_name),
        )
        for values in course_info_rows:
            row = information_table.add_row()
            row.height = Inches(0.4)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            for column, (cell, value) in enumerate(zip(row.cells, values)):
                cell.width = Inches(table_widths[column])
                set_cell(
                    cell,
                    value,
                    bold=column in (0, 2),
                    fill="FFFFFF",
                    size=8,
                    alignment=(
                        WD_ALIGN_PARAGRAPH.LEFT
                        if column in (1, 3)
                        else WD_ALIGN_PARAGRAPH.CENTER
                    ),
                )

        bloom_labels = {
            "BL1": "L1: Remember",
            "BL2": "L2: Understand",
            "BL3": "L3: Apply",
            "BL4": "L4: Analyze",
            "BL5": "L5: Evaluate",
            "BL6": "L6: Create",
        }
        cognitive_levels = report_data.get("co_cognitive_levels", {})
        outcome_rows = [
            (
                f"{course.course_code} CO-{co.co_number}",
                co.description,
                bloom_labels.get(
                    cognitive_levels.get(co.id),
                    "Not configured",
                ),
            )
            for co in report_data.get("cos", [])
        ]
        outcome_table = document.add_table(rows=1, cols=3)
        outcome_table.style = "Table Grid"
        outcome_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        outcome_table.autofit = False
        outcome_widths = (1.2, 3.55, 1.05)
        outcome_table.rows[0].height = Inches(0.36)
        outcome_table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for column, (header_text, width) in enumerate(
            zip(("CO", "Course Outcome Statements", "Cognitive Level"), outcome_widths)
        ):
            outcome_table.columns[column].width = Inches(width)
            outcome_table.rows[0].cells[column].width = Inches(width)
            set_cell(
                outcome_table.rows[0].cells[column],
                header_text,
                bold=True,
                fill="FFFFFF",
                size=8,
            )
        for values in outcome_rows:
            row = outcome_table.add_row()
            row.height = Inches(0.4)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            for column, (cell, value, width) in enumerate(
                zip(row.cells, values, outcome_widths)
            ):
                cell.width = Inches(width)
                set_cell(
                    cell,
                    value,
                    bold=column == 0,
                    fill="FFFFFF",
                    size=8,
                    alignment=(
                        WD_ALIGN_PARAGRAPH.LEFT
                        if column == 1
                        else WD_ALIGN_PARAGRAPH.CENTER
                    ),
                )

    add_course_outcomes_page()

    def add_assessment_tools_page():
        heading = add_section_heading("LIST OF ASSESSMENT TOOLS")
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in heading.runs:
            run.font.name = "Times New Roman"
            run.font.size = Pt(11)
            run.font.bold = True
            run.font.color.rgb = RGBColor(0, 0, 0)
        heading.paragraph_format.space_after = Pt(4)

        headers = (
            "Mode of Assessment",
            "Assessment Component",
            "Assessment Tool",
            "Evaluation of CO",
            "Mapping With PO & PSO",
            "Frequency of Assessment",
            "Marks / Weightage",
        )
        widths = (0.82, 0.84, 0.82, 0.8, 1.55, 1.15, 0.99)
        table = document.add_table(rows=2, cols=len(headers))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        for column, width in enumerate(widths):
            table.columns[column].width = Inches(width)

        title_cell = table.cell(0, 0).merge(table.cell(0, len(headers) - 1))
        set_cell(
            title_cell,
            "Assessment Method and Instruments (Direct and Indirect)",
            bold=True,
            fill="F4C7A8",
            size=10,
        )
        table.rows[0].height = Inches(0.34)
        table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        table.rows[1].height = Inches(0.58)
        table.rows[1].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for column, (header_text, width) in enumerate(zip(headers, widths)):
            table.rows[1].cells[column].width = Inches(width)
            set_cell(
                table.rows[1].cells[column],
                header_text,
                bold=True,
                fill="FFFFFF",
                size=7,
            )

        assessment_rows = report_data.get("assessment_tool_rows", [])
        component_labels = {
            "ese": "End Semester Exam",
            "university exam": "End Semester Exam",
        }
        rendered_components = []
        for item in assessment_rows:
            mode = "Indirect Assessment" if item["mode"] == "Indirect" else "Direct Assessment"
            component_key = item["component"].strip().lower()
            component = component_labels.get(
                component_key,
                item["component"].replace(" Exam", "").replace(" exam", ""),
            )
            rendered_components.append(
                (
                    mode,
                    component,
                    item["tool"],
                    item["cos"],
                    item["outcomes"],
                    item["frequency"],
                    item["marks"],
                )
            )

        for values in rendered_components:
            row = table.add_row()
            row.height = Inches(0.34)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            for column, (cell, value, width) in enumerate(
                zip(row.cells, values, widths)
            ):
                cell.width = Inches(width)
                set_cell(
                    cell,
                    value,
                    bold=column == 0,
                    fill="FFFFFF",
                    size=7,
                    alignment=(
                        WD_ALIGN_PARAGRAPH.LEFT
                        if column in (2, 3, 4)
                        else WD_ALIGN_PARAGRAPH.CENTER
                    ),
                )

        def merge_repeated_cells(column):
            start = 2
            while start < len(table.rows):
                value = table.cell(start, column).text
                end = start + 1
                while end < len(table.rows) and table.cell(end, column).text == value:
                    end += 1
                if value and end - start > 1:
                    merged_cell = table.cell(start, column).merge(
                        table.cell(end - 1, column)
                    )
                    set_cell(
                        merged_cell,
                        value,
                        bold=True,
                        fill="FFFFFF",
                        size=7,
                    )
                start = end

        merge_repeated_cells(0)
        merge_repeated_cells(1)

    assessment_columns = report_data.get("cie_display_columns", [])

    def add_assessment_pattern_page():
        assessment_data = report_data["assessment_pattern_data"]

        def add_centered_chart(chart_data, unavailable_message):
            if chart_data:
                document.add_picture(
                    io.BytesIO(base64.b64decode(chart_data)),
                    width=Inches(4.8),
                )
                document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                paragraph = document.add_paragraph(unavailable_message)
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        def image_height(image_data, display_width):
            if not image_data:
                return 0
            image_bytes = base64.b64decode(image_data)
            image_width, image_height_px = struct.unpack(">II", image_bytes[16:24])
            return display_width * image_height_px / image_width

        co_chart_height = image_height(assessment_data.get("co_chart"), 4.8)
        bloom_chart_height = image_height(assessment_data.get("bl_chart"), 4.8)
        co_table_height = 0.72 + len(assessment_data["co_table"]) * 0.42
        bloom_table_height = 0.72 + len(assessment_data["bl_table"]) * 0.42
        heading_and_spacing = 1.6
        chart_spacing = 0.6
        body_height = (
            heading_and_spacing
            + co_table_height
            + bloom_table_height
            + co_chart_height
            + bloom_chart_height
            + chart_spacing
        )
        custom_page_height = min(
            21.9,
            max(
                11.69,
                report_section.top_margin.inches
                + report_section.bottom_margin.inches
                + body_height,
            ),
        )
        assessment_section = document.add_section(WD_SECTION.NEW_PAGE)
        assessment_section.orientation = WD_ORIENT.PORTRAIT
        assessment_section.page_width = Inches(8.27)
        assessment_section.page_height = Inches(custom_page_height)
        assessment_section.top_margin = Inches(1.85)
        assessment_section.bottom_margin = Inches(0.55)
        assessment_section.left_margin = Inches(0.65)
        assessment_section.right_margin = Inches(0.65)
        assessment_section.header_distance = Inches(0.08)
        assessment_section.header.is_linked_to_previous = True

        heading = add_section_heading("Assessment Pattern", new_page=False)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.paragraph_format.space_after = Pt(4)
        for run in heading.runs:
            run.font.name = "Times New Roman"
            run.font.size = Pt(12)
            run.font.bold = True
            run.font.color.rgb = RGBColor(204, 0, 0)

        grouped_columns = assessment_data["grouped_columns"]
        pattern_columns = [
            column
            for columns in grouped_columns.values()
            for column in columns
        ]

        def add_pattern_table(title, first_header, data, total_header):
            def format_pattern_value(value):
                if isinstance(value, float):
                    return f"{value:.2f}"
                return value

            column_count = len(pattern_columns) + 2
            table_width = 6.97
            widths = [0.72]
            widths.extend([5.35 / max(len(pattern_columns), 1)] * len(pattern_columns))
            widths.append(0.9)
            table = document.add_table(rows=2, cols=column_count)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            for column, width in enumerate(widths):
                table.columns[column].width = Inches(width)
            table.rows[0].height = Inches(0.3)
            table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            table.rows[1].height = Inches(0.32)
            table.rows[1].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            for column, header_text in ((0, first_header), (column_count - 1, total_header)):
                cell = table.cell(0, column).merge(table.cell(1, column))
                set_cell(
                    cell,
                    header_text,
                    bold=True,
                    fill="D9EAF7",
                    size=7,
                )
            column_offset = 1
            for group_name, columns in grouped_columns.items():
                group_end = column_offset + len(columns) - 1
                group_cell = table.cell(0, column_offset)
                if group_end > column_offset:
                    group_cell = group_cell.merge(table.cell(0, group_end))
                set_cell(
                    group_cell,
                    group_name,
                    bold=True,
                    fill="D9EAF7",
                    size=7,
                )
                for column_index, column in enumerate(columns, column_offset):
                    subheader = table.cell(1, column_index)
                    subheader.width = Inches(widths[column_index])
                    set_cell(
                        subheader,
                        column["sub"],
                        bold=True,
                        fill="EDF4FA",
                        size=6,
                    )
                column_offset = group_end + 1

            for row_index, (row_label, row_data) in enumerate(data):
                row = table.add_row()
                row.height = Inches(0.32)
                row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
                values = [row_label]
                values.extend(
                    format_pattern_value(row_data.get(column["key"], 0))
                    for column in pattern_columns
                )
                values.append(format_pattern_value(row_data.get("TOTAL", 0)))
                for column, (cell, value, width) in enumerate(zip(row.cells, values, widths)):
                    cell.width = Inches(width)
                    set_cell(
                        cell,
                        value,
                        bold=column == 0,
                        fill=(
                            "EAF2F8" if row_index % 2 else "FFFFFF"
                        ),
                        size=7,
                        alignment=WD_ALIGN_PARAGRAPH.CENTER,
                    )
            return table

        co_rows = list(assessment_data["co_table"].items())
        co_heading = add_section_heading(
            "CO-wise Marks Distribution",
            new_page=False,
            level=2,
        )
        co_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_pattern_table(
            "CO-wise Marks Distribution",
            "Course outcome",
            co_rows,
            "CIE total",
        )
        add_centered_chart(
            assessment_data.get("co_chart"),
            "CO-wise marks chart is unavailable.",
        )

        quality_heading = add_section_heading(
            "Quality of Question Paper & Assignment",
            new_page=False,
            level=2,
        )
        quality_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        bloom_rows = list(assessment_data["bl_table"].items())
        add_pattern_table(
            "Quality of Question Paper & Assignment",
            "Cognitive level",
            bloom_rows,
            "Total",
        )
        add_centered_chart(
            assessment_data.get("bl_chart"),
            "Cognitive-level marks chart is unavailable.",
        )

        following_section = document.add_section(WD_SECTION.NEW_PAGE)
        following_section.orientation = WD_ORIENT.PORTRAIT
        following_section.page_width = Inches(8.27)
        following_section.page_height = Inches(11.69)
        following_section.top_margin = Inches(1.85)
        following_section.bottom_margin = Inches(0.55)
        following_section.left_margin = Inches(0.65)
        following_section.right_margin = Inches(0.65)
        following_section.header_distance = Inches(0.08)
        following_section.header.is_linked_to_previous = True

        setup_heading = add_section_heading(
            "Attainment Weightage and Target",
            new_page=False,
        )
        setup_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in setup_heading.runs:
            run.font.name = "Times New Roman"
            run.font.size = Pt(12)
            run.font.bold = True
            run.font.color.rgb = RGBColor(204, 0, 0)

        weightage = report_data["weightage"]
        setup_title_table = document.add_table(rows=1, cols=2)
        setup_title_table.style = "Table Grid"
        setup_title_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        setup_title_table.autofit = False
        setup_title_table.columns[0].width = Inches(2.9)
        setup_title_table.columns[1].width = Inches(2.9)
        setup_title_table.rows[0].height = Inches(0.3)
        setup_title_table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        setup_title_cell = setup_title_table.cell(0, 0).merge(
            setup_title_table.cell(0, 1)
        )
        set_cell(
            setup_title_cell,
            "Attainment Weightage and Target",
            bold=True,
            fill="F4C7A8",
            size=10,
        )

        setup_table = document.add_table(rows=5, cols=3)
        setup_table.style = "Table Grid"
        setup_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        setup_table.autofit = False
        for column in range(3):
            setup_table.columns[column].width = Inches(1.933)
        setup_cells = [
            (
                setup_table.cell(0, 0).merge(setup_table.cell(0, 2)),
                "Weightage for CO Attainment",
                "FFFFFF",
                True,
            ),
            (
                setup_table.cell(1, 0).merge(setup_table.cell(1, 1)),
                "A] DIRECT ATTAINMENT",
                "F4C7A8",
                True,
            ),
            (
                setup_table.cell(1, 2),
                "B] INDIRECT ATTAINMENT",
                "F4C7A8",
                True,
            ),
            (
                setup_table.cell(2, 0).merge(setup_table.cell(2, 1)),
                f"{weightage.direct_attainment}%",
                "FFFFFF",
                True,
            ),
            (
                setup_table.cell(2, 2),
                f"{weightage.indirect_attainment}%",
                "FFFFFF",
                True,
            ),
            (
                setup_table.cell(3, 0),
                "Continuous Internal Evaluation (CIE)",
                "F4C7A8",
                True,
            ),
            (
                setup_table.cell(3, 1),
                "End Semester Examination (ESE)",
                "F4C7A8",
                True,
            ),
            (
                setup_table.cell(3, 2),
                "COURSE EXIT SURVEY",
                "F4C7A8",
                True,
            ),
            (
                setup_table.cell(4, 0),
                f"{weightage.cie_weightage}%",
                "FFFFFF",
                True,
            ),
            (
                setup_table.cell(4, 1),
                f"{weightage.ese_weightage}%",
                "FFFFFF",
                True,
            ),
            (
                setup_table.cell(4, 2),
                "",
                "FFFFFF",
                False,
            ),
        ]
        for cell, text, fill, bold in setup_cells:
            set_cell(cell, text, bold=bold, fill=fill, size=7.5)
        for row in setup_table.rows:
            row.height = Inches(0.34)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        setup_table.rows[0].height = Inches(0.3)
        setup_table.rows[3].height = Inches(0.42)

        target_rows = [
            (
                f"CO-{co.co_number}",
                co.description,
                {
                    "BL1": "L1: Remember",
                    "BL2": "L2: Understand",
                    "BL3": "L3: Apply",
                    "BL4": "L4: Analyze",
                    "BL5": "L5: Evaluate",
                    "BL6": "L6: Create",
                }.get(report_data.get("co_cognitive_levels", {}).get(co.id), "Not configured"),
                report_data.get("target_map", {}).get(co.id, "Not set"),
            )
            for co in report_data.get("cos", [])
        ]
        target_title_table = document.add_table(rows=1, cols=2)
        target_title_table.style = "Table Grid"
        target_title_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        target_title_table.autofit = False
        target_title_table.columns[0].width = Inches(2.9)
        target_title_table.columns[1].width = Inches(2.9)
        target_title_cell = target_title_table.cell(0, 0).merge(
            target_title_table.cell(0, 1)
        )
        set_cell(
            target_title_cell,
            "CO wise Target (50-70%)",
            bold=True,
            size=8,
        )

        target_table = document.add_table(rows=1, cols=4)
        target_table.style = "Table Grid"
        target_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        target_table.autofit = False
        target_widths = (1.2, 2.75, 1.05, 0.8)
        for column, width in enumerate(target_widths):
            target_table.columns[column].width = Inches(width)
        for column, (header, width) in enumerate(
            zip(
                (
                    "CO Number",
                    "Course Outcome Statements",
                    "Cognitive Level",
                    "Weightage (%)",
                ),
                target_widths,
            )
        ):
            target_table.cell(0, column).width = Inches(width)
            set_cell(
                target_table.cell(0, column),
                header,
                bold=True,
                fill="F4C7A8",
                size=7,
            )
        for row_index, values in enumerate(target_rows):
            row = target_table.add_row()
            row.height = Inches(0.42)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            for column, value in enumerate(values):
                row.cells[column].width = Inches(target_widths[column])
                set_cell(
                    row.cells[column],
                    value,
                    bold=column == 0,
                    fill="FFFFFF",
                    size=7,
                    alignment=(
                        WD_ALIGN_PARAGRAPH.LEFT
                        if column == 1
                        else WD_ALIGN_PARAGRAPH.CENTER
                    ),
                )

    def add_co_class_average_page():
        landscape_section = document.add_section(WD_SECTION.NEW_PAGE)
        landscape_section.orientation = WD_ORIENT.LANDSCAPE
        landscape_section.page_width = Inches(11.69)
        landscape_section.page_height = Inches(8.27)
        landscape_section.top_margin = Inches(0.55)
        landscape_section.bottom_margin = Inches(0.45)
        landscape_section.left_margin = Inches(0.3)
        landscape_section.right_margin = Inches(0.3)
        landscape_section.header_distance = Inches(0.08)
        landscape_section.header.is_linked_to_previous = True

        heading = add_section_heading("CO Attainment Sheet", new_page=False)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in heading.runs:
            run.font.size = Pt(18)
            run.font.bold = True
            run.font.color.rgb = RGBColor(31, 50, 76)
        subtitle = document.add_paragraph(
            "Class-average performance and weighted attainment for each course outcome."
        )
        subtitle.paragraph_format.space_after = Pt(10)
        for run in subtitle.runs:
            run.font.name = "Arial"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(92, 113, 145)

        section_heading = document.add_paragraph("CIE Class Averages")
        section_heading.paragraph_format.space_before = Pt(4)
        section_heading.paragraph_format.space_after = Pt(2)
        for run in section_heading.runs:
            run.font.name = "Arial"
            run.font.size = Pt(11)
            run.font.bold = True
            run.font.color.rgb = RGBColor(31, 50, 76)
        section_subtitle = document.add_paragraph(
            "Class-average percentage for each assessment, with the CIE and final ESE averages."
        )
        section_subtitle.paragraph_format.space_after = Pt(8)
        for run in section_subtitle.runs:
            run.font.name = "Arial"
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(92, 113, 145)

        assessment_count = len(assessment_columns)
        total_columns = assessment_count + 4
        table = document.add_table(rows=2, cols=total_columns)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        base_widths = [0.55, 0.8]
        assessment_width = 6.8 / max(assessment_count, 1)
        widths = base_widths + [assessment_width] * assessment_count + [1.15, 1.15]
        for index, width in enumerate(widths):
            table.columns[index].width = Inches(width)

        course_outcome_cell = table.cell(0, 0).merge(table.cell(1, 0))
        course_outcome_cell.width = Inches(widths[0])
        set_cell(
            course_outcome_cell,
            "COURSE OUTCOMES",
            bold=True,
            fill="EDF2FA",
            size=7,
        )
        class_average_cell = table.cell(0, 1).merge(table.cell(1, 1))
        class_average_cell.width = Inches(widths[1])
        set_cell(
            class_average_cell,
            "",
            bold=True,
            fill="EDF2FA",
            size=7,
        )
        if assessment_count:
            cie_group = table.cell(0, 2).merge(table.cell(0, assessment_count + 1))
            cie_group.width = Inches(sum(widths[2:2 + assessment_count]))
            set_cell(
                cie_group,
                "CONTINUOUS INTERNAL EVALUATION",
                bold=True,
                fill="F4C7A8",
                size=7,
            )
        for index, column in enumerate(assessment_columns, 2):
            table.cell(1, index).width = Inches(widths[index])
            set_cell(
                table.cell(1, index),
                f"{column['sub']} AVERAGE %",
                bold=True,
                fill="EDF2FA",
                size=6,
            )
        final_group = table.cell(0, assessment_count + 2).merge(
            table.cell(0, assessment_count + 3)
        )
        final_group.width = Inches(sum(widths[-2:]))
        set_cell(
            final_group,
            "FINAL AVERAGES",
            bold=True,
            fill="F4C7A8",
            size=7,
        )
        set_cell(
            table.cell(1, assessment_count + 2),
            "CIE AVERAGE %",
            bold=True,
            fill="EDF2FA",
            size=6,
        )
        table.cell(1, assessment_count + 2).width = Inches(widths[-2])
        set_cell(
            table.cell(1, assessment_count + 3),
            "ESE AVERAGE %",
            bold=True,
            fill="EDF2FA",
            size=6,
        )
        table.cell(1, assessment_count + 3).width = Inches(widths[-1])
        for row_index, co in enumerate(report_data.get("cos", [])):
            row = table.add_row()
            row.height = Inches(0.34)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            co_key = f"CO{co.co_number}"
            average_data = report_data.get("display_avg_table", {}).get(co_key, {})
            values = [
                co_key,
                "Class Avg.%",
                *(
                    (
                        f"{average_data[column['key']]:.2f}"
                        if average_data.get(column["key"], "") != ""
                        else ""
                    )
                    for column in assessment_columns
                ),
                (
                    f"{report_data['cie_percentage_table'][co_key]:.2f}"
                    if report_data.get("cie_percentage_table", {}).get(co_key, "") != ""
                    else ""
                ),
                (
                    f"{report_data['ese_percentage_table'][co_key]:.2f}"
                    if report_data.get("ese_percentage_table", {}).get(co_key, "") != ""
                    else ""
                ),
            ]
            for index, value in enumerate(values):
                row.cells[index].width = Inches(widths[index])
                set_cell(
                    row.cells[index],
                    value,
                    bold=index == 0,
                    fill="FFFFFF" if row_index % 2 else "F8FAFD",
                    size=7,
                    alignment=(
                        WD_ALIGN_PARAGRAPH.LEFT
                        if index == 1
                        else WD_ALIGN_PARAGRAPH.CENTER
                    ),
                )

        direct_section = document.add_section(WD_SECTION.NEW_PAGE)
        direct_section.orientation = WD_ORIENT.LANDSCAPE
        direct_section.page_width = Inches(11.69)
        direct_section.page_height = Inches(8.27)
        direct_section.top_margin = Inches(0.55)
        direct_section.bottom_margin = Inches(0.45)
        direct_section.left_margin = Inches(0.45)
        direct_section.right_margin = Inches(0.45)
        direct_section.header_distance = Inches(0.08)
        direct_section.header.is_linked_to_previous = True

        direct_heading = add_section_heading("Direct CO Attainment", new_page=False)
        direct_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in direct_heading.runs:
            run.font.name = "Arial"
            run.font.size = Pt(16)
            run.font.bold = True
            run.font.color.rgb = RGBColor(31, 50, 76)
        direct_subtitle = document.add_paragraph(
            f"{report_data['weightage'].cie_weightage:g}% CIE share and "
            f"{report_data['weightage'].ese_weightage:g}% ESE share."
        )
        direct_subtitle.paragraph_format.space_after = Pt(8)
        for run in direct_subtitle.runs:
            run.font.name = "Arial"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(92, 113, 145)

        direct_meta = document.add_table(rows=2, cols=2)
        direct_meta.style = "Table Grid"
        direct_meta.alignment = WD_TABLE_ALIGNMENT.CENTER
        direct_meta.autofit = False
        for column in range(2):
            direct_meta.columns[column].width = Inches(5.35)
        meta_values = (
            (
                f"Subject: {course.course_name}",
                f"A.Y.: {course.academic_class.academic_year}",
            ),
            (
                f"Subject code: {course.course_code}",
                f"Semester: Sem {course.academic_class.semester}",
            ),
        )
        for row_index, values in enumerate(meta_values):
            for column, value in enumerate(values):
                set_cell(
                    direct_meta.cell(row_index, column),
                    value,
                    bold=True,
                    fill="F8FAFD",
                    size=8,
                    alignment=WD_ALIGN_PARAGRAPH.LEFT,
                )

        direct_table = document.add_table(rows=1, cols=5)
        direct_table.style = "Table Grid"
        direct_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        direct_table.autofit = False
        direct_widths = (1.0, 2.45, 2.45, 2.9, 1.9)
        for column, width in enumerate(direct_widths):
            direct_table.columns[column].width = Inches(width)
        direct_weightage = report_data["weightage"]
        direct_headers = (
            "CO",
            "CIE CLASS AVERAGE %",
            "ESE CLASS AVERAGE %",
            (
                "DIRECT CO ATTAINMENT\n"
                f"({direct_weightage.cie_weightage:g}% CIE + "
                f"{direct_weightage.ese_weightage:g}% ESE)"
            ),
            "DIRECT CO ATTAINMENT %\n(ROUNDED)",
        )
        for column, (header, width) in enumerate(zip(direct_headers, direct_widths)):
            direct_table.cell(0, column).width = Inches(width)
            set_cell(
                direct_table.cell(0, column),
                header,
                bold=True,
                fill="EDF2FA",
                size=7,
            )
        for row_index, values in enumerate(
            (
                (
                    row["co"],
                    row["cie_percentage"],
                    row["ese_percentage"],
                    row["direct_attainment"],
                    row["direct_attainment_rounded"],
                )
                for row in report_data.get("direct_attainment_rows", [])
            )
        ):
            row = direct_table.add_row()
            row.height = Inches(0.38)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            for column, value in enumerate(values):
                set_cell(
                    row.cells[column],
                    value,
                    bold=column in (0, 3, 4),
                    fill=(
                        "FFF8E8"
                        if column == 1
                        else "EAF1FF"
                        if column == 3
                        else "EAF8F2"
                        if column == 4
                        else "FFFFFF"
                    ),
                    size=8,
                )
        formula_row = direct_table.add_row()
        formula_cell = formula_row.cells[0].merge(formula_row.cells[4])
        set_cell(
            formula_cell,
            (
                "Direct CO Attainment = (CIE Class Average × "
                f"{direct_weightage.cie_weightage:g}%) + (ESE Class Average × "
                f"{direct_weightage.ese_weightage:g}%)"
            ),
            bold=True,
            fill="EDF2FA",
            size=8,
            alignment=WD_ALIGN_PARAGRAPH.LEFT,
        )

    def add_course_exit_survey_page():
        survey_section = document.add_section(WD_SECTION.NEW_PAGE)
        survey_section.orientation = WD_ORIENT.LANDSCAPE
        survey_section.page_width = Inches(11.69)
        survey_section.page_height = Inches(8.27)
        survey_section.top_margin = Inches(0.55)
        survey_section.bottom_margin = Inches(0.45)
        survey_section.left_margin = Inches(0.3)
        survey_section.right_margin = Inches(0.3)
        survey_section.header_distance = Inches(0.08)
        survey_section.header.is_linked_to_previous = True

        heading = add_section_heading("Course Exit Survey", new_page=False)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in heading.runs:
            run.font.name = "Arial"
            run.font.size = Pt(18)
            run.font.bold = True
            run.font.color.rgb = RGBColor(31, 50, 76)
        subtitle = document.add_paragraph(
            f"Review course outcome responses and survey attainment for {course.course_name}."
        )
        subtitle.paragraph_format.space_after = Pt(10)
        for run in subtitle.runs:
            run.font.name = "Arial"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(92, 113, 145)

        survey_title = document.add_paragraph(f"Course Exit Survey · {course.course_name}")
        survey_title.paragraph_format.space_after = Pt(2)
        for run in survey_title.runs:
            run.font.name = "Arial"
            run.font.size = Pt(11)
            run.font.bold = True
            run.font.color.rgb = RGBColor(31, 50, 76)
        survey_description = document.add_paragraph(
            "Response counts, averages and attainment are shown for each course outcome."
        )
        survey_description.paragraph_format.space_after = Pt(8)
        for run in survey_description.runs:
            run.font.name = "Arial"
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(92, 113, 145)

        survey_records = {
            record.course_outcome_id: record
            for record in CourseExitSurvey.objects.filter(course=course)
        }
        survey_table = document.add_table(rows=1, cols=9)
        survey_table.style = "Table Grid"
        survey_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        survey_table.autofit = False
        survey_widths = (0.55, 3.45, 0.9, 0.75, 0.75, 0.75, 0.9, 0.8, 0.85)
        for column, width in enumerate(survey_widths):
            survey_table.columns[column].width = Inches(width)
        survey_headers = (
            "CO",
            "COURSE OUTCOME QUESTION",
            "STRONGLY AGREE\n(5)",
            "AGREE\n(4)",
            "NEUTRAL\n(3)",
            "DISAGREE\n(2)",
            "STRONGLY DISAGREE\n(1)",
            "AVERAGE",
            "ATTAINMENT\n%",
        )
        for column, (header, width) in enumerate(zip(survey_headers, survey_widths)):
            survey_table.cell(0, column).width = Inches(width)
            set_cell(
                survey_table.cell(0, column),
                header,
                bold=True,
                fill="EDF2FA",
                size=6.5,
            )
        for row_index, co in enumerate(report_data.get("cos", [])):
            record = survey_records.get(co.id)
            strongly_agree = record.strongly_agree if record else 0
            agree = record.agree if record else 0
            neutral = record.neutral if record else 0
            disagree = record.disagree if record else 0
            strongly_disagree = record.strongly_disagree if record else 0
            total = strongly_agree + agree + neutral + disagree + strongly_disagree
            weighted_total = (
                strongly_agree * 5
                + agree * 4
                + neutral * 3
                + disagree * 2
                + strongly_disagree
            )
            average = round(weighted_total / total, 8) if total else ""
            percentage = round(average * 20, 4) if average != "" else ""
            question = (record.question_text if record else co.description or "").strip()
            if question.lower().startswith("are you able to:"):
                question = question[len("are you able to:"):].strip()
            values = (
                f"CO{co.co_number}",
                question,
                strongly_agree,
                agree,
                neutral,
                disagree,
                strongly_disagree,
                f"{average:.2f}" if average != "" else "",
                f"{percentage:.2f}%" if percentage != "" else "",
            )
            row = survey_table.add_row()
            row.height = Inches(0.42)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            for column, value in enumerate(values):
                set_cell(
                    row.cells[column],
                    value,
                    bold=column in (0, 8),
                    fill="EAF8F2" if column == 8 else (
                        "F8FAFD" if row_index % 2 else "FFFFFF"
                    ),
                    size=7,
                    alignment=(
                        WD_ALIGN_PARAGRAPH.LEFT
                        if column == 1
                        else WD_ALIGN_PARAGRAPH.CENTER
                    ),
                )

    def add_total_co_attainment_page():
        total_section = document.add_section(WD_SECTION.NEW_PAGE)
        total_section.orientation = WD_ORIENT.LANDSCAPE
        total_section.page_width = Inches(11.69)
        total_section.page_height = Inches(8.27)
        total_section.top_margin = Inches(0.55)
        total_section.bottom_margin = Inches(0.45)
        total_section.left_margin = Inches(0.3)
        total_section.right_margin = Inches(0.3)
        total_section.header_distance = Inches(0.08)
        total_section.header.is_linked_to_previous = True

        heading = add_section_heading("Total CO Attainment", new_page=False)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in heading.runs:
            run.font.name = "Arial"
            run.font.size = Pt(16)
            run.font.bold = True
            run.font.color.rgb = RGBColor(31, 50, 76)
        subtitle = document.add_paragraph(
            f"{report_data['weightage'].direct_attainment:g}% direct share and "
            f"{report_data['weightage'].indirect_attainment:g}% indirect share."
        )
        subtitle.paragraph_format.space_after = Pt(8)
        for run in subtitle.runs:
            run.font.name = "Arial"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(92, 113, 145)

        meta = document.add_table(rows=2, cols=2)
        meta.style = "Table Grid"
        meta.alignment = WD_TABLE_ALIGNMENT.CENTER
        meta.autofit = False
        for column in range(2):
            meta.columns[column].width = Inches(5.35)
        meta_values = (
            (
                f"Subject: {course.course_name}",
                f"A.Y.: {course.academic_class.academic_year}",
            ),
            (
                f"Subject code: {course.course_code}",
                f"Semester: Sem {course.academic_class.semester}",
            ),
        )
        for row_index, values in enumerate(meta_values):
            for column, value in enumerate(values):
                set_cell(
                    meta.cell(row_index, column),
                    value,
                    bold=True,
                    fill="F8FAFD",
                    size=8,
                    alignment=WD_ALIGN_PARAGRAPH.LEFT,
                )

        total_table = document.add_table(rows=1, cols=6)
        total_table.style = "Table Grid"
        total_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        total_table.autofit = False
        total_widths = (1.0, 2.15, 2.15, 2.25, 2.15, 1.0)
        for column, width in enumerate(total_widths):
            total_table.columns[column].width = Inches(width)
        total_headers = (
            "CO",
            "DIRECT CO ATTAINMENT",
            "INDIRECT CO ATTAINMENT",
            "TOTAL CO ATTAINMENT %",
            "TOTAL CO ATTAINMENT %\n(ROUNDED)",
            "LEVEL OF WEIGHTED CO",
        )
        for column, (header, width) in enumerate(zip(total_headers, total_widths)):
            total_table.cell(0, column).width = Inches(width)
            set_cell(
                total_table.cell(0, column),
                header,
                bold=True,
                fill="EDF2FA",
                size=6.5,
            )
        for row_index, values in enumerate(
            (
                (
                    row["co"],
                    row["direct_attainment_rounded"],
                    f'{row["indirect_attainment"]:.2f}',
                    f'{row["total_attainment"]:.2f}',
                    row["total_attainment_rounded"],
                    row["weighted_level"],
                )
                for row in report_data.get("total_attainment_rows", [])
            )
        ):
            row = total_table.add_row()
            row.height = Inches(0.38)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            for column, value in enumerate(values):
                set_cell(
                    row.cells[column],
                    value,
                    bold=column in (0, 4, 5),
                    fill=(
                        "FFF8E8"
                        if column in (1, 2)
                        else "EAF1FF"
                        if column == 3
                        else "EAF8F2"
                        if column in (4, 5)
                        else "FFFFFF"
                    ),
                    size=8,
                )
        formula_row = total_table.add_row()
        formula_cell = formula_row.cells[0].merge(total_table.rows[-1].cells[5])
        set_cell(
            formula_cell,
            (
                "Total Attainment of CO = "
                f"{report_data['weightage'].direct_attainment:g}% × Direct Attainment "
                f"of CO + {report_data['weightage'].indirect_attainment:g}% × "
                "Indirect Attainment of CO"
            ),
            bold=True,
            fill="EDF2FA",
            size=8,
            alignment=WD_ALIGN_PARAGRAPH.LEFT,
        )

    add_assessment_tools_page()
    add_assessment_pattern_page()
    add_co_class_average_page()
    add_course_exit_survey_page()
    add_total_co_attainment_page()

    gap_section = document.add_section(WD_SECTION.NEW_PAGE)
    gap_section.orientation = WD_ORIENT.PORTRAIT
    gap_section.page_width = Inches(8.27)
    gap_section.page_height = Inches(11.69)
    gap_section.top_margin = Inches(0.58)
    gap_section.bottom_margin = Inches(0.48)
    gap_section.left_margin = Inches(0.65)
    gap_section.right_margin = Inches(0.65)
    gap_section.header_distance = Inches(0.08)
    gap_section.header.is_linked_to_previous = True

    gap_heading = add_section_heading("CO Attainment GAP", new_page=False)
    gap_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    gap_heading.paragraph_format.space_before = Pt(0)
    gap_heading.paragraph_format.space_after = Pt(3)
    for run in gap_heading.runs:
        run.font.size = Pt(14)
        run.font.bold = True
        run.font.color.rgb = RGBColor(31, 50, 76)

    gap_meta = document.add_table(rows=2, cols=2)
    gap_meta.style = "Table Grid"
    gap_meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    gap_meta.autofit = False
    for column in range(2):
        gap_meta.columns[column].width = Inches(2.9)
    gap_meta_values = (
        (f"Subject: {course.course_name}", f"A.Y.: {course.academic_class.academic_year}"),
        (f"Subject Code: {course.course_code}", f"Semester: Sem {course.academic_class.semester}"),
    )
    for row_index, values in enumerate(gap_meta_values):
        for column, value in enumerate(values):
            set_cell(
                gap_meta.cell(row_index, column),
                value,
                bold=True,
                fill="EEF4FB" if row_index == 0 else "F8FAFD",
                size=7,
                alignment=WD_ALIGN_PARAGRAPH.LEFT,
            )

    gap_table = document.add_table(rows=1, cols=5)
    gap_table.style = "Table Grid"
    gap_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    gap_table.autofit = False
    gap_widths = (0.75, 0.9, 1.2, 1.25, 1.7)
    for column, width in enumerate(gap_widths):
        gap_table.columns[column].width = Inches(width)
    gap_headers = (
        "CO's",
        "Target",
        "CO Attainment",
        "CO Attainment Gap (Target-\nAttainment) %",
        "Focus",
    )
    for column, (header, width) in enumerate(zip(gap_headers, gap_widths)):
        gap_table.cell(0, column).width = Inches(width)
        set_cell(
            gap_table.cell(0, column),
            header,
            bold=True,
            fill="DDEBD0",
            size=6.5,
        )
    for row_index, source_row in enumerate(report_data.get("gap_rows", [])):
        values = (
            source_row["co"],
            source_row["target"] if source_row["target"] is not None else "Not set",
            f'{source_row["attainment"]:.2f}'
            if source_row["attainment"] != ""
            else "",
            source_row["gap"] if source_row["gap"] is not None else "",
            source_row["focus"],
        )
        row = gap_table.add_row()
        row.height = Inches(0.38)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for column, value in enumerate(values):
            set_cell(
                row.cells[column],
                value,
                bold=column in (0, 4),
                fill="FFFFFF" if row_index % 2 else "F5F9F2",
                size=7,
            )
    for row in gap_table.rows:
        row.height = Inches(0.28)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)

    closure_title = document.add_table(rows=1, cols=1)
    closure_title.style = "Table Grid"
    closure_title.alignment = WD_TABLE_ALIGNMENT.CENTER
    closure_title.autofit = False
    closure_title.columns[0].width = Inches(5.8)
    set_cell(
        closure_title.cell(0, 0),
        "Closure of QUALITY Loop",
        bold=True,
        fill="D9EAF7",
        size=8.5,
    )
    for paragraph in closure_title.cell(0, 0).paragraphs:
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)

    closure_table = document.add_table(rows=1, cols=5)
    closure_table.style = "Table Grid"
    closure_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    closure_table.autofit = False
    closure_widths = (0.75, 0.9, 1.15, 1.95, 1.05)
    for column, width in enumerate(closure_widths):
        closure_table.columns[column].width = Inches(width)
    closure_headers = (
        "CO's",
        "Target",
        "CO Attainment Gap\n(Target-Attainment) %",
        "Action Proposed to Bridge Gap\n(Write specific plan for improving attainment of CO for next time course offer)",
        "Modifications of Target\nwhere achieved",
    )
    for column, (header, width) in enumerate(zip(closure_headers, closure_widths)):
        closure_table.cell(0, column).width = Inches(width)
        set_cell(
            closure_table.cell(0, column),
            header,
            bold=True,
            fill="DDEBD0",
            size=5.8,
        )
    for row_index, source_row in enumerate(report_data.get("gap_rows", [])):
        values = (
            source_row["co"],
            source_row["target"] if source_row["target"] is not None else "Not set",
            source_row["gap"] if source_row["gap"] is not None else "",
            source_row["action_proposed"] or "",
            source_row["target_modification"] or "",
        )
        row = closure_table.add_row()
        row.height = Inches(0.42)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for column, value in enumerate(values):
            set_cell(
                row.cells[column],
                value,
                bold=column == 0,
                fill="FFFFFF" if row_index % 2 else "F8FBFD",
                size=6.5,
                alignment=(
                    WD_ALIGN_PARAGRAPH.LEFT
                    if column in (3, 4)
                    else WD_ALIGN_PARAGRAPH.CENTER
                ),
            )
    for row in closure_table.rows:
        row.height = Inches(0.3)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
    add_gap_chart(report_data.get("gap_rows", []))

    pos = report_data.get("pos", [])
    psos = report_data.get("psos", [])
    outcome_headers = [outcome.po_number for outcome in pos] + [outcome.pso_number for outcome in psos]
    mapping_section = document.add_section(WD_SECTION.NEW_PAGE)
    mapping_section.orientation = WD_ORIENT.LANDSCAPE
    mapping_section.page_width = Inches(16.54)
    mapping_section.page_height = Inches(11.69)
    mapping_section.top_margin = Inches(0.65)
    mapping_section.bottom_margin = Inches(0.55)
    mapping_section.left_margin = Inches(0.3)
    mapping_section.right_margin = Inches(0.3)
    mapping_section.header_distance = Inches(0.08)
    mapping_section.header.is_linked_to_previous = True
    add_section_heading("Mapping Grade")

    guide = document.add_paragraph()
    guide.alignment = WD_ALIGN_PARAGRAPH.CENTER
    guide.paragraph_format.space_before = Pt(0)
    guide.paragraph_format.space_after = Pt(5)
    guide_run = guide.add_run(
        "Grade scale:  1 - Below 40%    |    2 - 40% to 69.99%    |    3 - 70% and above"
    )
    guide_run.font.name = "Times New Roman"
    guide_run.font.size = Pt(8)
    guide_run.font.color.rgb = RGBColor(76, 96, 120)

    if outcome_headers and report_data.get("mapping_grade_rows"):
        outcome_count = len(outcome_headers)
        total_width = 14.7
        outcome_width = (total_width - 1.15) / outcome_count
        outcome_sub_widths = (0.17, 0.17, 0.22, 0.13)
        column_widths = [1.15] + [
            outcome_width * width / sum(outcome_sub_widths)
            for _ in range(outcome_count)
            for width in outcome_sub_widths
        ]
        mapping_table = document.add_table(rows=2, cols=1 + outcome_count * 4)
        mapping_table.style = "Table Grid"
        mapping_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        mapping_table.autofit = False
        table_properties = mapping_table._tbl.tblPr
        table_width = table_properties.find(qn("w:tblW"))
        if table_width is None:
            table_width = OxmlElement("w:tblW")
            table_properties.append(table_width)
        table_width.set(qn("w:w"), str(int(total_width * 1440)))
        table_width.set(qn("w:type"), "dxa")

        for column, width in enumerate(column_widths):
            mapping_table.columns[column].width = Inches(width)

        co_header = mapping_table.cell(0, 0).merge(mapping_table.cell(1, 0))
        set_cell(
            co_header,
            "Course outcome",
            bold=True,
            fill="D9E7F5",
            size=6.5,
            no_wrap=True,
        )
        for outcome_index, outcome in enumerate(outcome_headers):
            start = 1 + outcome_index * 4
            header_cell = mapping_table.cell(0, start).merge(
                mapping_table.cell(0, start + 3)
            )
            set_cell(
                header_cell,
                outcome,
                bold=True,
                fill="C7DAED",
                size=6.5,
                no_wrap=True,
            )
            for sub_index, label in enumerate(("TPI", "MPI", "Map%", "Gr.")):
                set_cell(
                    mapping_table.cell(1, start + sub_index),
                    label,
                    bold=True,
                    fill="EAF2F9",
                    size=6,
                    no_wrap=True,
                )

        for mapping_row in report_data.get("mapping_grade_rows", []):
            row = mapping_table.add_row()
            row.height = Inches(0.34)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            fill = "F7FAFD" if len(mapping_table.rows) % 2 else "FFFFFF"
            set_cell(
                row.cells[0],
                f"CO{mapping_row['co'].co_number}",
                bold=True,
                fill=fill,
                size=6.5,
                no_wrap=True,
            )
            for outcome_index, entry in enumerate(mapping_row["entries"]):
                values = (
                    entry["tpi"],
                    entry["mpi"],
                    f"{entry['percentage']:g}%",
                    entry["grade"] if entry["grade"] is not None else "—",
                )
                start = 1 + outcome_index * 4
                for sub_index, value in enumerate(values):
                    grade_fill = {
                        1: "FCE8E6",
                        2: "FFF3D6",
                        3: "E6F4EA",
                    }.get(entry["grade"], fill) if sub_index == 3 else fill
                    set_cell(
                        row.cells[start + sub_index],
                        value,
                        bold=sub_index == 3 and entry["grade"] is not None,
                        fill=grade_fill,
                        size=6.5,
                        no_wrap=True,
                    )

        average_row = mapping_table.add_row()
        average_row.height = Inches(0.34)
        average_row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        set_cell(
            average_row.cells[0],
            "Average grade",
            bold=True,
            fill="D9E7F5",
            size=6.5,
            no_wrap=True,
        )
        for outcome_index in range(outcome_count):
            grades = [
                row["entries"][outcome_index]["grade"]
                for row in report_data.get("mapping_grade_rows", [])
                if row["entries"][outcome_index]["grade"] is not None
            ]
            average = round(sum(grades) / len(grades), 2) if grades else "—"
            start = 1 + outcome_index * 4
            merged_average = average_row.cells[start].merge(
                average_row.cells[start + 2]
            )
            set_cell(merged_average, "—", fill="D9E7F5", size=6, no_wrap=True)
            set_cell(
                average_row.cells[start + 3],
                average,
                bold=True,
                fill="D9E7F5",
                size=6.5,
                no_wrap=True,
            )
    else:
        document.add_paragraph("No PO/PSO mappings are configured for this course.")

    matrix_section = document.add_section(WD_SECTION.NEW_PAGE)
    matrix_section.orientation = WD_ORIENT.LANDSCAPE
    matrix_section.page_width = Inches(11.69)
    matrix_section.page_height = Inches(8.27)
    matrix_section.top_margin = Inches(0.55)
    matrix_section.bottom_margin = Inches(0.45)
    matrix_section.left_margin = Inches(0.4)
    matrix_section.right_margin = Inches(0.4)
    matrix_section.header_distance = Inches(0.08)
    matrix_section.header.is_linked_to_previous = True
    add_section_heading("Course Articulation Matrix (CO-PO-PSO Mapping)", new_page=False)

    matrix_rows = [
        (
            f"CO-{mapping_row['co'].co_number}",
            *[
                entry["grade"] if entry["grade"] is not None else ""
                for entry in mapping_row["entries"]
            ],
        )
        for mapping_row in report_data.get("mapping_grade_rows", [])
    ]
    average_values = []
    for column_index in range(len(outcome_headers)):
        grades = [
            row["entries"][column_index]["grade"]
            for row in report_data.get("mapping_grade_rows", [])
            if row["entries"][column_index]["grade"] is not None
        ]
        average_values.append(round(sum(grades) / len(grades), 2) if grades else "")
    if outcome_headers:
        matrix_rows.append(("AVERAGE", *average_values))
        matrix_table = document.add_table(rows=1, cols=1 + len(outcome_headers))
        matrix_table.style = "Table Grid"
        matrix_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        matrix_table.autofit = False
        matrix_width = 10.85
        matrix_column_width = matrix_width / (len(outcome_headers) + 1)
        for column in range(len(outcome_headers) + 1):
            matrix_table.columns[column].width = Inches(matrix_column_width)
        title_cell = matrix_table.cell(0, 0).merge(
            matrix_table.cell(0, len(outcome_headers))
        )
        set_cell(
            title_cell,
            f"{course.course_code} CO-PO-PSO Mapping",
            bold=True,
            fill="F4C7A1",
            size=10,
        )
        for row_index, values in enumerate(
            [("Course Outcomes", *outcome_headers), *matrix_rows],
            start=1,
        ):
            row = matrix_table.add_row()
            row.height = Inches(0.38)
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            fill = "F4C7A1" if row_index == len(matrix_rows) + 1 else (
                "F8FBFD" if row_index % 2 else "FFFFFF"
            )
            for column, value in enumerate(values):
                set_cell(
                    row.cells[column],
                    value,
                    bold=column == 0 or row_index in (1, len(matrix_rows) + 1),
                    fill=fill,
                    size=7,
                    no_wrap=True,
                )

    attainment_section = document.add_section(WD_SECTION.NEW_PAGE)
    attainment_section.orientation = WD_ORIENT.LANDSCAPE
    attainment_section.page_width = Inches(16.54)
    attainment_section.page_height = Inches(11.69)
    attainment_section.top_margin = Inches(0.55)
    attainment_section.bottom_margin = Inches(0.45)
    attainment_section.left_margin = Inches(0.4)
    attainment_section.right_margin = Inches(0.4)
    attainment_section.header_distance = Inches(0.08)
    attainment_section.header.is_linked_to_previous = True
    add_section_heading("CO-PO-PSO Attainment", new_page=False)

    attainment_headers = (
        "PO / PSO",
        "Mapped CO",
        "Mapping Level",
        "Max Level",
        "PO-PSO Attainment Formula",
        "PO-PSO Attainment",
        "Attainment",
        "Attainment Level",
    )
    attainment_table = document.add_table(rows=1, cols=len(attainment_headers))
    attainment_table.style = "Table Grid"
    attainment_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    attainment_table.autofit = False
    header_properties = attainment_table.rows[0]._tr.get_or_add_trPr()
    repeat_header = OxmlElement("w:tblHeader")
    repeat_header.set(qn("w:val"), "true")
    header_properties.append(repeat_header)
    attainment_widths = (1.0, 1.35, 1.15, 0.9, 5.2, 1.55, 1.0, 1.0)
    attainment_table_width = sum(attainment_widths)
    table_properties = attainment_table._tbl.tblPr
    table_width = OxmlElement("w:tblW")
    table_width.set(qn("w:w"), str(int(attainment_table_width * 1440)))
    table_width.set(qn("w:type"), "dxa")
    table_properties.append(table_width)
    for column, (header, width) in enumerate(zip(attainment_headers, attainment_widths)):
        attainment_table.columns[column].width = Inches(width)
        set_cell(
            attainment_table.cell(0, column),
            header,
            bold=True,
            fill="F4C7A1",
            size=7,
        )
    for row_index, source_row in enumerate(
        report_data.get("po_pso_attainment_rows", [])
    ):
        row = attainment_table.add_row()
        row.height = Inches(0.38)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        row_properties = row._tr.get_or_add_trPr()
        no_split = OxmlElement("w:cantSplit")
        no_split.set(qn("w:val"), "true")
        row_properties.append(no_split)
        values = (
            source_row["outcome"],
            source_row["mapped_cos"],
            source_row["mapping_level"],
            source_row["max_level"],
            source_row["formula"],
            (
                f'{source_row["attainment"]:.2f}'
                if source_row["attainment"] != ""
                else ""
            ),
            source_row["rounded_attainment"],
            source_row["attainment_level"],
        )
        for column, value in enumerate(values):
            set_cell(
                row.cells[column],
                value,
                bold=column == 0,
                fill="FFFFFF" if row_index % 2 else "FFF8F2",
                size=7 if column == 4 else 7.5,
                alignment=(
                    WD_ALIGN_PARAGRAPH.LEFT
                    if column in (1, 4)
                    else WD_ALIGN_PARAGRAPH.CENTER
                ),
            )

    thresholds = report_data.get("attainment_thresholds")
    level_2 = thresholds.level_2_min if thresholds else 34
    level_3 = thresholds.level_3_min if thresholds else 67
    legend_title = document.add_table(rows=1, cols=1)
    legend_title.style = "Table Grid"
    legend_title.alignment = WD_TABLE_ALIGNMENT.CENTER
    legend_title.autofit = False
    legend_title.columns[0].width = Inches(7.6)
    set_cell(
        legend_title.cell(0, 0),
        "CO-PO Mapping Level",
        bold=True,
        fill="D9EAD3",
        size=9,
    )
    legend_table = document.add_table(rows=2, cols=3)
    legend_table.style = "Table Grid"
    legend_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    legend_table.autofit = False
    legend_values = (
        ("1", "2", "3"),
        (f"<{level_2}", f">={level_2} and <{level_3}", f">={level_3}"),
    )
    for row_index, values in enumerate(legend_values):
        for column, value in enumerate(values):
            legend_table.columns[column].width = Inches(7.6 / 3)
            set_cell(
                legend_table.cell(row_index, column),
                value,
                bold=row_index == 0,
                fill="FFFFFF",
                size=8,
            )

    buffer = io.BytesIO()
    document.save(buffer)
    safe_course_code = re.sub(r"[^A-Za-z0-9._-]+", "-", course.course_code).strip("-")
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="CO-PO-PSO-Attainment-{safe_course_code}.docx"'
    )
    return response

    add_section_heading("Course Articulation Matrix (CO-PO-PSO Mapping)")
    matrix_rows = [
        (
            f"CO{mapping_row['co'].co_number}",
            *[entry["grade"] if entry["grade"] is not None else "—" for entry in mapping_row["entries"]],
        )
        for mapping_row in report_data.get("mapping_grade_rows", [])
    ]
    average_values = []
    for column_index in range(len(outcome_headers)):
        grades = [
            row["entries"][column_index]["grade"]
            for row in report_data.get("mapping_grade_rows", [])
            if row["entries"][column_index]["grade"] is not None
        ]
        average_values.append(round(sum(grades) / len(grades), 2) if grades else "—")
    if outcome_headers:
        matrix_rows.append(("Average", *average_values))
        add_report_table(
            ("Course Outcome", *outcome_headers),
            matrix_rows,
            font_size=max(5, 8 - len(outcome_headers) // 5),
        )
    else:
        document.add_paragraph("No PO/PSO mappings are configured for this course.")

    add_section_heading("Direct Attainment of PO-PSOs")
    direct_by_co = {
        row["co"]: row["direct_attainment_rounded"]
        for row in report_data.get("direct_attainment_rows", [])
    }
    direct_po_pso_rows = []
    for column_index, outcome in enumerate(outcome_headers):
        mapped = [
            (mapping_row["entries"][column_index]["grade"], direct_by_co.get(f"CO{mapping_row['co'].co_number}"))
            for mapping_row in report_data.get("mapping_grade_rows", [])
            if mapping_row["entries"][column_index]["grade"] is not None
            and f"CO{mapping_row['co'].co_number}" in direct_by_co
        ]
        if not mapped:
            direct_po_pso_rows.append((outcome, "", 3, "", "", ""))
            continue
        mapping_average = sum(item[0] for item in mapped) / len(mapped)
        co_attainment_average = sum(item[1] for item in mapped) / len(mapped)
        direct_value = co_attainment_average * mapping_average / 3
        direct_po_pso_rows.append((
            outcome,
            ", ".join(
                f"CO{mapping_row['co'].co_number}"
                for mapping_row in report_data.get("mapping_grade_rows", [])
                if mapping_row["entries"][column_index]["grade"] is not None
            ),
            3,
            f"({mapping_average:.2f}/3) × ({co_attainment_average:.2f})",
            round(direct_value, 8),
            round(direct_value),
        ))
    add_report_table(
        ("PO / PSO", "Mapped COs", "Max Level", "Direct Attainment Formula", "Direct PO-PSO Attainment", "Rounded Attainment"),
        direct_po_pso_rows,
        widths=(1.15, 2.3, 1.0, 2.5, 2.0, 1.9),
        font_size=7,
    )

    headers = (
        "PO / PSO",
        "Mapped CO",
        "Mapping Level",
        "Max Level",
        "PO-PSO Attainment\n(Avg. Attainment × Actual Mapping / Max Level)\n(Formula for reference)",
        "PO-PSO Attainment\n(Avg. Attainment × Actual Mapping / Max Level)",
        "Attainment",
        "Attainment Level",
    )
    column_widths = (0.62, 0.88, 0.82, 0.62, 2.65, 2.55, 0.82, 0.82)
    po_table_width = 5.8
    column_width_scale = po_table_width / sum(column_widths)
    column_widths = tuple(width * column_width_scale for width in column_widths)
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.rows[0].height = Inches(0.62)
    table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    for index, (header, width) in enumerate(zip(headers, column_widths)):
        table.columns[index].width = Inches(width)
        table.rows[0].cells[index].width = Inches(width)
        set_cell(
            table.rows[0].cells[index],
            header,
            bold=True,
            fill="FFFFFF",
            size=8,
        )

    header_properties = table.rows[0]._tr.get_or_add_trPr()
    repeat_header = OxmlElement("w:tblHeader")
    repeat_header.set(qn("w:val"), "true")
    header_properties.append(repeat_header)

    def display_number(value):
        if value == "":
            return ""
        return f"{float(value):.8f}".rstrip("0").rstrip(".")

    for report_row in rows:
        row = table.add_row()
        row.height = Inches(0.42)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        cells = row.cells
        values = (
            report_row["outcome"],
            report_row["mapped_cos"] or "",
            f"{report_row['mapping_level']:.2f}" if report_row["mapping_level"] != "" else "",
            report_row["max_level"],
            report_row["formula"],
            display_number(report_row["attainment"]),
            report_row["rounded_attainment"],
            report_row["attainment_level"],
        )
        for index, (cell, value, width) in enumerate(zip(cells, values, column_widths)):
            cell.width = Inches(width)
            set_cell(
                cell,
                value,
                bold=index in (0, 6, 7),
                fill="FFFFFF",
                size=8 if index == 4 else 9,
            )

    document.add_paragraph().paragraph_format.space_after = Pt(3)
    legend_title = document.add_paragraph()
    legend_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    legend_title.paragraph_format.space_before = Pt(4)
    legend_title.paragraph_format.space_after = Pt(0)
    legend_run = legend_title.add_run("CO-PO Mapping Level")
    legend_run.font.name = "Times New Roman"
    legend_run.font.size = Pt(12)
    legend_run.font.bold = True
    legend_run.font.color.rgb = RGBColor(49, 90, 47)

    level_2 = thresholds.level_2_min
    level_3 = thresholds.level_3_min
    legend_rows = (
        ("Level 1", "Level 2", "Level 3"),
        (f"<{level_2}", f">={level_2} and <{level_3}", f">={level_3}"),
        (f"<{level_2}%", f"{level_2}-{level_3}%", f"Above {level_3}%"),
    )
    legend = document.add_table(rows=len(legend_rows), cols=3)
    legend.style = "Table Grid"
    legend.alignment = WD_TABLE_ALIGNMENT.CENTER
    legend.autofit = False
    legend_width = po_table_width / 3
    for row_index, values in enumerate(legend_rows):
        for column_index, value in enumerate(values):
            legend.columns[column_index].width = Inches(legend_width)
            legend.cell(row_index, column_index).width = Inches(legend_width)
            set_cell(
                legend.cell(row_index, column_index),
                value,
                bold=row_index == 0,
                fill="FFFFFF",
                size=9,
            )
        legend.rows[row_index].height = Inches(0.42)
        legend.rows[row_index].height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST

    buffer = io.BytesIO()
    document.save(buffer)
    safe_course_code = re.sub(r"[^A-Za-z0-9._-]+", "-", course.course_code).strip("-")
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="CO-PO-PSO-Attainment-{safe_course_code}.docx"'
    )
    return response


@login_required
def co_attainment_sheet(
    request,
    course_id,
    report_type="sheet",
    *,
    return_attainment_rows=False,
    return_report_context=False,
):

    course = get_object_or_404(Course, id=course_id)

    if not (request.user.role == "HOD" or course.faculty == request.user):
        return HttpResponseForbidden("Not authorized")

    tools = AssessmentTool.objects.filter(course=course)
    students = Student.objects.filter(
        academic_class=course.academic_class
    ).order_by("list_order", "pk")

    # ----------------------------
    # GROUP COLUMNS
    # ----------------------------
    grouped_columns = {}
    cie_columns = []
    ese_tools = []

    for tool in tools:

        main = tool.main_tool
        sub = tool.sub_tool

        if main.strip().upper() == "ESE":
            ese_tools.append(tool)
            continue

        column = {
            "key": f"tool_{tool.id}",
            "sub": sub if sub else main,
            "tool": tool
        }
        cie_columns.append(column)
        if main not in grouped_columns:
            grouped_columns[main] = []
        grouped_columns[main].append(column)

    # ----------------------------
    # CO LIST
    # ----------------------------
    cos = CourseOutcome.objects.filter(course=course).order_by("co_number")
    edit_mode = report_type == "gap" and request.GET.get("edit") == "1"
    quality_loop_records = {
        record.course_outcome_id: record
        for record in COQualityLoop.objects.filter(course=course)
    }

    if report_type == "gap" and request.method == "POST":
        for co in cos:
            COQualityLoop.objects.update_or_create(
                course=course,
                course_outcome=co,
                defaults={
                    "action_proposed": request.POST.get(f"action_{co.id}", "").strip(),
                    "target_modification": request.POST.get(f"modification_{co.id}", "").strip(),
                },
            )
        messages.success(request, "Quality loop statements saved successfully.")
        return redirect("co_attainment_gap", course_id=course.id)

    tool_items_by_co = {}
    tool_marks_by_student = {}

    def get_tool_items_by_co(tool):
        if tool.id not in tool_items_by_co:
            main = tool.main_tool.strip().lower()

            if main == "ica":
                items = IcaAssignmentExp.objects.filter(tool=tool).select_related("co")
            elif main == "ise assignment":
                items = AssignmentTool.objects.filter(tool=tool).select_related("co")
            elif main == "ise exam":
                items = ExamDetail.objects.filter(tool=tool).select_related("co")
            elif main == "mock oral":
                items = UniversityExam.objects.filter(tool=tool).select_related("co")
            else:
                items = ()

            items_by_co = defaultdict(list)
            for item in items:
                items_by_co[item.co_id].append(item)
            tool_items_by_co[tool.id] = items_by_co

        return tool_items_by_co[tool.id]

    def get_tool_co_items(tool, co):
        return get_tool_items_by_co(tool).get(co.id, [])

    def get_tool_marks_by_student(tool):
        if tool.id not in tool_marks_by_student:
            main = tool.main_tool.strip().lower()

            if main == "ica":
                mark_model, item_field = IcaStudentMarks, "subtool"
            elif main == "ise assignment":
                mark_model, item_field = AssignmentTutorialMarks, "question"
            elif main == "ise exam":
                mark_model, item_field = ExamMarks, "question"
            elif main == "mock oral":
                tool_marks_by_student[tool.id] = dict(
                    UniversityExamMarks.objects.filter(
                        tool=tool,
                        marks__isnull=False,
                    ).values_list("student_id", "marks")
                )
                return tool_marks_by_student[tool.id]
            else:
                tool_marks_by_student[tool.id] = {}
                return tool_marks_by_student[tool.id]

            marks_by_student = defaultdict(dict)
            for student_id, item_id, marks in mark_model.objects.filter(
                tool=tool,
                marks__isnull=False,
            ).values_list("student_id", f"{item_field}_id", "marks"):
                marks_by_student[student_id][item_id] = marks
            tool_marks_by_student[tool.id] = marks_by_student

        return tool_marks_by_student[tool.id]

    def get_mark_for_item(tool, student, item):
        return get_tool_marks_by_student(tool).get(student.id, {}).get(item.id)

    def calculate_tool_co_average(tool, co, selected_items=None):
        items = (
            [item for item in selected_items if item.co_id == co.id]
            if selected_items is not None
            else get_tool_co_items(tool, co)
        )
        main = tool.main_tool.strip().lower()
        all_exam_items = []
        selected_exam_max_ids = set()

        if main == "ise exam":
            all_exam_items = sorted(
                [
                    item
                    for items in get_tool_items_by_co(tool).values()
                    for item in items
                ],
                key=_exam_question_sort_key
            )
            selected_exam_max_ids = _effective_exam_detail_ids(all_exam_items)
            items = [
                item
                for item in items
                if item.id in selected_exam_max_ids
            ]

        if not items:
            return 0, 0

        max_marks = sum(item.marks or 0 for item in items)

        if main == "mock oral":
            configured_total = sum(
                item.marks or 0
                for co_items in get_tool_items_by_co(tool).values()
                for item in co_items
            )
            if not configured_total:
                return 0, max_marks

            student_totals = []
            marks_by_student = get_tool_marks_by_student(tool)
            for student in students:
                total_marks = marks_by_student.get(student.id)
                if total_marks is not None:
                    student_totals.append(total_marks * max_marks / configured_total)

            average = sum(student_totals) / len(student_totals) if student_totals else 0
            return round(average, 2), max_marks

        student_totals = []

        for student in students:
            total = 0
            attempted = False
            effective_question_ids = set()

            if main == "ise exam":
                student_exam_marks = get_tool_marks_by_student(tool).get(student.id, {})
                effective_question_ids = _effective_exam_detail_ids(all_exam_items, student_exam_marks)

            for item in items:

                if main == "ise exam" and item.id not in effective_question_ids:
                    continue

                mark = get_mark_for_item(tool, student, item)

                if mark is not None:
                    total += mark
                    attempted = True

            if attempted:
                student_totals.append(total)

        average = sum(student_totals) / len(student_totals) if student_totals else 0
        return round(average, 2), max_marks

    cie_display_columns = []
    roman_numerals = {1: "I", 2: "II", 3: "III", 4: "IV"}

    for tool in tools:
        main = tool.main_tool.strip().lower()
        if main == "ese":
            continue

        if main == "ica":
            items = sorted(
                [item for co_items in get_tool_items_by_co(tool).values() for item in co_items],
                key=lambda item: item.sub_tool_no,
            )
            for item in items:
                cie_display_columns.append({
                    "key": f"tool_{tool.id}_item_{item.id}",
                    "sub": f"{tool.sub_tool or 'Experiment'} {item.sub_tool_no}",
                    "tool": tool,
                    "items": [item],
                })
            continue

        if main == "ise assignment":
            items = [item for co_items in get_tool_items_by_co(tool).values() for item in co_items]
            assignment_groups = defaultdict(list)
            ungrouped_items = []
            for item in items:
                match = re.fullmatch(r"A(\d+)\.\d+", item.question_no or "")
                if match:
                    assignment_groups[int(match.group(1))].append(item)
                else:
                    ungrouped_items.append(item)

            if assignment_groups:
                for assignment_number, assignment_items in sorted(assignment_groups.items()):
                    numeral = roman_numerals.get(assignment_number, str(assignment_number))
                    cie_display_columns.append({
                        "key": f"tool_{tool.id}_assignment_{assignment_number}",
                        "sub": f"ISE-{numeral}",
                        "tool": tool,
                        "items": assignment_items,
                    })
                if ungrouped_items:
                    cie_display_columns.append({
                        "key": f"tool_{tool.id}_other_assignments",
                        "sub": tool.sub_tool or "Assignment",
                        "tool": tool,
                        "items": ungrouped_items,
                    })
                continue

        sub_tool = tool.sub_tool.strip()
        exam_match = re.fullmatch(r"UT\s*-?\s*(\d+)", sub_tool, re.IGNORECASE)
        if main == "ise exam" and exam_match:
            numeral = roman_numerals.get(int(exam_match.group(1)), exam_match.group(1))
            sub_tool = f"UT-{numeral}"
        elif main == "ise exam" and sub_tool.lower() == "prelim":
            sub_tool = "PRELIM"

        cie_display_columns.append({
            "key": f"tool_{tool.id}",
            "sub": sub_tool or tool.main_tool,
            "tool": tool,
            "items": None,
        })

    # ----------------------------
    # MARKS CONTRIBUTION + CLASS AVERAGE TABLE
    # ----------------------------
    co_table = {}
    co_avg_table = {}
    display_avg_table = {}
    cie_total_table = {}
    cie_percentage_table = {}
    ese_percentage_table = {}
    direct_attainment_rows = []
    total_attainment_rows = []
    gap_rows = []
    po_pso_attainment_rows = []
    mapping_grade_rows = []
    pos = []
    psos = []
    assessment_tool_rows = []
    attainment_thresholds = None
    can_edit_thresholds = report_type == "po_pso" and request.user.role == "HOD"
    threshold_edit_mode = can_edit_thresholds and request.GET.get("edit") == "1"

    if report_type == "po_pso":
        attainment_thresholds, _ = AttainmentLevelThreshold.objects.get_or_create(
            course=course
        )
        if request.method == "POST":
            if not can_edit_thresholds:
                return HttpResponseForbidden("Not authorized")
            try:
                level_2_min = int(request.POST.get("level_2_min", ""))
                level_3_min = int(request.POST.get("level_3_min", ""))
            except (TypeError, ValueError):
                messages.error(request, "Enter whole-number attainment cutoffs.")
                threshold_edit_mode = True
            else:
                if 1 <= level_2_min < level_3_min <= 100:
                    attainment_thresholds.level_2_min = level_2_min
                    attainment_thresholds.level_3_min = level_3_min
                    attainment_thresholds.save(update_fields=["level_2_min", "level_3_min"])
                    messages.success(request, "Attainment level cutoffs saved.")
                    return redirect("co_po_pso_attainment", course_id=course.id)
                messages.error(request, "Level 2 must be below Level 3, and both cutoffs must be between 1 and 100.")
                threshold_edit_mode = True

    surveys_by_co = {
        survey.course_outcome_id: survey
        for survey in CourseExitSurvey.objects.filter(course=course)
    }
    target_map = {
        target.course_outcome_id: target.target_percentage
        for target in COTarget.objects.filter(course=course)
    }
    weightage = AttainmentWeightage.objects.filter(course=course).first()
    if weightage is None:
        weightage = AttainmentWeightage(course=course)
    direct_weight = weightage.direct_attainment / 100
    indirect_weight = weightage.indirect_attainment / 100
    cie_weight = weightage.cie_weightage / 100
    ese_weight = weightage.ese_weightage / 100

    def calculate_survey_percentage(co):
        survey = surveys_by_co.get(co.id)

        if not survey:
            return 0

        total = (
            survey.strongly_agree
            + survey.agree
            + survey.neutral
            + survey.disagree
            + survey.strongly_disagree
        )

        if not total:
            return 0

        weighted_total = (
            survey.strongly_agree * 5
            + survey.agree * 4
            + survey.neutral * 3
            + survey.disagree * 2
            + survey.strongly_disagree
        )

        return (weighted_total / total) * 20

    def calculate_ese_class_average_percentage():
        tool_percentages = []

        for tool in ese_tools:
            configured_total = UniversityExam.objects.filter(
                tool=tool
            ).aggregate(total=Sum("marks"))["total"] or 0

            if not configured_total:
                continue

            average_marks = UniversityExamMarks.objects.filter(
                tool=tool,
                marks__isnull=False,
            ).aggregate(average=Avg("marks"))["average"] or 0

            tool_percentages.append(average_marks / configured_total * 100)

        return (
            round(sum(tool_percentages) / len(tool_percentages), 4)
            if tool_percentages
            else 0
        )

    ese_class_average_percentage = calculate_ese_class_average_percentage()

    def calculate_weighted_level(co, total_percentage):
        target = target_map.get(co.id, 0)

        if not target:
            return ""
        if total_percentage >= target:
            return 3
        if total_percentage >= target * 0.8:
            return 2
        if total_percentage >= target * 0.6:
            return 1
        return 0

    for co in cos:

        contribution_row = {}
        average_row = {}
        cie_average_total = 0
        cie_marks_total = 0

        for main, cols in grouped_columns.items():

            for col in cols:

                tool = col["tool"]
                key = col["key"]

                average, marks = calculate_tool_co_average(tool, co)

                average_row[key] = round(average / marks * 100, 2) if marks else ""
                contribution_row[key] = marks if marks else ""
                cie_average_total += average
                cie_marks_total += marks

        co_key = f"CO{co.co_number}"
        contribution_row["TOTAL"] = cie_marks_total
        average_row["TOTAL"] = round(cie_average_total, 4)

        display_average_row = {}
        for column in cie_display_columns:
            average, marks = calculate_tool_co_average(
                column["tool"],
                co,
                column["items"],
            )
            display_average_row[column["key"]] = (
                round(average / marks * 100, 4) if marks else ""
            )

        co_table[co_key] = contribution_row
        co_avg_table[co_key] = average_row
        display_avg_table[co_key] = display_average_row
        cie_total_table[co_key] = round(cie_average_total, 4)
        row_assessment_averages = [
            value for value in display_average_row.values() if value != ""
        ]
        cie_percentage_table[co_key] = (
            round(sum(row_assessment_averages) / len(row_assessment_averages), 4)
            if row_assessment_averages
            else 0
        )
        ese_percentage_table[co_key] = ese_class_average_percentage
        direct_component_total = weightage.cie_weightage + weightage.ese_weightage
        direct_attainment = (
            (
                cie_percentage_table[co_key] * weightage.cie_weightage
                + ese_percentage_table[co_key] * weightage.ese_weightage
            )
            / direct_component_total
            if direct_component_total
            else 0
        )
        direct_attainment_rounded = math.floor(direct_attainment + 0.5)
        indirect_attainment = round(calculate_survey_percentage(co), 8)
        total_attainment = (
            direct_attainment_rounded * direct_weight
        ) + (
            indirect_attainment * indirect_weight
        )
        direct_attainment_rows.append({
            "co": co_key,
            "cie_percentage": round(cie_percentage_table[co_key], 2),
            "ese_percentage": round(ese_percentage_table[co_key], 2),
            "direct_attainment": round(direct_attainment, 2),
            "direct_attainment_rounded": direct_attainment_rounded,
        })
        total_attainment_rows.append({
            "co": co_key,
            "direct_attainment_rounded": direct_attainment_rounded,
            "indirect_attainment": round(indirect_attainment, 8),
            "total_attainment": round(total_attainment, 8),
            "total_attainment_rounded": math.floor(total_attainment + 0.5),
            "weighted_level": calculate_weighted_level(co, total_attainment),
        })

        target = target_map.get(co.id)
        attainment = total_attainment_rows[-1]["total_attainment_rounded"]
        gap = target - attainment if target is not None else None
        if target is None:
            focus = "Set a target for this CO"
            focus_class = "focus-unset"
        elif gap < 0:
            focus = "Increase the target for this CO"
            focus_class = "focus-exceeded"
        elif gap > 0:
            focus = "More focus on this CO"
            focus_class = "focus-below"
        else:
            focus = "More focus on this CO"
            focus_class = "focus-met"

        gap_rows.append({
            "co": co_key,
            "co_id": co.id,
            "target": target,
            "attainment": attainment,
            "gap": gap,
            "focus": focus,
            "focus_class": focus_class,
            "action_proposed": getattr(quality_loop_records.get(co.id), "action_proposed", ""),
            "target_modification": getattr(quality_loop_records.get(co.id), "target_modification", ""),
        })

    if report_type == "po_pso":
        mapping_grade_rows, pos, psos = _course_mapping_grades(
            course,
            cos=cos,
            persist=True,
        )
        attainment_by_co_id = {
            co.id: row["total_attainment_rounded"]
            for co, row in zip(cos, total_attainment_rows)
        }

        def format_mapped_cos(mapped_cos):
            numbers = sorted(co.co_number for co in mapped_cos)
            if not numbers:
                return ""
            if numbers == list(range(numbers[0], numbers[-1] + 1)):
                if len(numbers) == 1:
                    return f"CO{numbers[0]}"
                return f"CO{numbers[0]}-CO{numbers[-1]}"
            return ", ".join(f"CO{number}" for number in numbers)

        def build_po_pso_row(outcome, mapping_model, field_name, label):
            mappings = list(
                mapping_model.objects.filter(
                    co__course=course,
                    **{field_name: outcome},
                ).select_related("co")
            )
            mapped_attainment = [
                attainment_by_co_id[mapping.co_id]
                for mapping in mappings
                if mapping.co_id in attainment_by_co_id
            ]
            mapping_level = (
                sum(mapping.level for mapping in mappings) / len(mappings)
                if mappings
                else None
            )
            average_attainment = (
                sum(mapped_attainment) / len(mapped_attainment)
                if mapped_attainment
                else None
            )
            attainment = (
                average_attainment * mapping_level / 3
                if average_attainment is not None and mapping_level is not None
                else None
            )

            if attainment is None:
                formula = ""
                rounded_attainment = ""
                attainment_level = ""
            else:
                formula_values = "+".join(str(value) for value in mapped_attainment)
                formula = f"({mapping_level:.2f}/3) × (({formula_values})/{len(mapped_attainment)})"
                rounded_attainment = round(attainment)
                attainment_level = (
                    3 if attainment >= attainment_thresholds.level_3_min
                    else 2 if attainment >= attainment_thresholds.level_2_min
                    else 1
                )

            po_pso_attainment_rows.append({
                "outcome": label,
                "mapped_cos": format_mapped_cos([mapping.co for mapping in mappings]),
                "mapping_level": round(mapping_level, 2) if mapping_level is not None else "",
                "max_level": 3,
                "formula": formula,
                "attainment": round(attainment, 8) if attainment is not None else "",
                "rounded_attainment": rounded_attainment,
                "attainment_level": attainment_level,
            })

        for po in pos:
            build_po_pso_row(po, COPOMapping, "po", po.po_number)
        for pso in psos:
            build_po_pso_row(pso, COPSOMapping, "pso", pso.pso_number)

        for tool in tools:
            main_tool = tool.main_tool.strip().lower()
            if main_tool == "ese":
                tool_items = list(UniversityExam.objects.filter(tool=tool).select_related("co"))
            else:
                tool_items = [
                    item
                    for co_items in get_tool_items_by_co(tool).values()
                    for item in co_items
                ]
            mapped_cos = {item.co_id: item.co for item in tool_items if item.co_id}
            mapped_co_ids = list(mapped_cos)
            po_numbers = sorted(set(
                COPOMapping.objects.filter(co_id__in=mapped_co_ids)
                .values_list("po__po_number", flat=True)
            ))
            pso_numbers = sorted(set(
                COPSOMapping.objects.filter(co_id__in=mapped_co_ids)
                .values_list("pso__pso_number", flat=True)
            ))
            assessment_tool_rows.append({
                "mode": "Direct",
                "component": tool.main_tool,
                "tool": tool.sub_tool,
                "cos": format_mapped_cos(list(mapped_cos.values())),
                "outcomes": ", ".join(po_numbers + pso_numbers) or "Not mapped",
                "frequency": "Once in Semester",
                "marks": sum(item.marks or 0 for item in tool_items),
            })

        assessment_tool_rows.append({
            "mode": "Indirect",
            "component": "Survey",
            "tool": "Course Exit Survey",
            "cos": format_mapped_cos(cos),
            "outcomes": ", ".join(
                sorted({po.po_number for po in pos})
                + sorted({pso.pso_number for pso in psos})
            ) or "Not mapped",
            "frequency": "Once in Semester",
            "marks": "",
        })

        prelim_keys = [
            column["key"]
            for column in cie_columns
            if column["sub"].strip().lower() == "prelim"
        ]
        prelim_chart_rows = [
            (
                f"CO{co.co_number}",
                sum(co_table.get(f"CO{co.co_number}", {}).get(key, 0) or 0 for key in prelim_keys),
            )
            for co in cos
        ]

        bloom_levels = (
            ("Remember", "BL1"),
            ("Understanding", "BL2"),
            ("Apply", "BL3"),
            ("Analyse", "BL4"),
            ("Evaluate", "BL5"),
            ("Create", "BL6"),
        )
        bloom_chart_rows = []
        for label, level in bloom_levels:
            marks = 0
            for tool in tools:
                main_tool = tool.main_tool.strip().lower()
                if main_tool == "ise exam":
                    items = ExamDetail.objects.filter(tool=tool, bl=level)
                elif main_tool == "ise assignment":
                    items = AssignmentTool.objects.filter(tool=tool, bl=level)
                elif main_tool == "ica":
                    items = IcaAssignmentExp.objects.filter(tool=tool, bl=level)
                else:
                    continue
                marks += items.aggregate(total=Sum("marks"))["total"] or 0
            bloom_chart_rows.append((label, marks))

    # ----------------------------
    # CONTEXT
    # ----------------------------
    context = {
        "course": course,
        "grouped_columns": grouped_columns,
        "cie_columns": cie_columns,
        "cie_display_columns": cie_display_columns,
        "co_avg_table": co_avg_table,
        "display_avg_table": display_avg_table,
        "co_table": co_table,
        "cie_total_table": cie_total_table,
        "cie_percentage_table": cie_percentage_table,
        "ese_percentage_table": ese_percentage_table,
        "direct_attainment_rows": direct_attainment_rows,
        "total_attainment_rows": total_attainment_rows,
        "gap_rows": gap_rows,
        "target_map": target_map,
        "cos": cos,
        "co_cognitive_levels": {
            target.course_outcome_id: target.bl_level
            for target in COTarget.objects.filter(course=course)
        },
        "po_pso_attainment_rows": po_pso_attainment_rows,
        "mapping_grade_rows": mapping_grade_rows,
        "pos": pos,
        "psos": psos,
        "assessment_tool_rows": assessment_tool_rows,
        "prelim_chart_rows": prelim_chart_rows if report_type == "po_pso" else [],
        "bloom_chart_rows": bloom_chart_rows if report_type == "po_pso" else [],
        "attainment_thresholds": attainment_thresholds,
        "can_edit_thresholds": can_edit_thresholds,
        "threshold_edit_mode": threshold_edit_mode,
        "edit_mode": edit_mode,
        "weightage": weightage,
    }

    if return_attainment_rows:
        return total_attainment_rows

    if return_report_context:
        return context

    if report_type == "po_pso" and request.GET.get("download") == "docx":
        assessment_data = assessment_pattern(
            request,
            course.id,
            return_report_context=True,
        )
        if isinstance(assessment_data, HttpResponse):
            return assessment_data
        context["assessment_pattern_data"] = assessment_data
        return _build_co_po_pso_docx_response(
            course,
            context,
        )

    return render(
        request,
        "reports/co_po_pso_attainment.html" if report_type == "po_pso" else "reports/co_attainment_gap.html" if report_type == "gap" else "reports/co_attainment_sheet.html",
        context
    )


@login_required
def course_report_preview(request, course_id):
    if request.GET.get("download") == "docx":
        return co_attainment_sheet(request, course_id, report_type="po_pso")

    report_context = co_attainment_sheet(
        request,
        course_id,
        report_type="po_pso",
        return_report_context=True,
    )
    if isinstance(report_context, HttpResponse):
        return report_context

    assessment_data = assessment_pattern(
        request,
        report_context["course"].id,
        return_report_context=True,
    )
    if isinstance(assessment_data, HttpResponse):
        return assessment_data
    report_context["assessment_pattern_data"] = assessment_data

    docx_response = _build_co_po_pso_docx_response(
        report_context["course"],
        report_context,
    )
    report_context["report_pages"] = _render_docx_report_preview(
        docx_response.content
    )
    return render(
        request,
        "reports/course_report_preview.html",
        report_context,
    )


def _render_docx_report_preview(document_bytes):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from html import escape

    document = Document(io.BytesIO(document_bytes))
    sections = list(document.sections)

    def render_paragraph(paragraph, *, in_header=False):
        text_parts = []
        for run in paragraph.runs:
            text = escape(run.text).replace("\n", "<br>").replace("\t", "&emsp;")
            if not text:
                continue
            run_styles = []
            if run.font.size:
                run_styles.append(f"font-size:{run.font.size.pt:g}pt")
            if run.font.name:
                run_styles.append(f"font-family:'{escape(run.font.name)}'")
            if run.font.color and run.font.color.rgb:
                run_styles.append(f"color:#{run.font.color.rgb}")
            if run.bold:
                text = f"<strong>{text}</strong>"
            if run.italic:
                text = f"<em>{text}</em>"
            if run.underline:
                text = f"<u>{text}</u>"
            if run_styles:
                text = f'<span style="{";".join(run_styles)}">{text}</span>'
            text_parts.append(text)

        for image in paragraph._p.xpath(".//a:blip"):
            relationship_id = image.get(qn("r:embed"))
            if not relationship_id:
                continue
            image_part = paragraph.part.related_parts[relationship_id]
            image_data = base64.b64encode(image_part.blob).decode("ascii")
            image_width = None
            image_height = None
            inline = image.getparent()
            while inline is not None and not inline.tag.endswith("}inline"):
                inline = inline.getparent()
            if inline is not None:
                extent = inline.find(qn("wp:extent"))
                if extent is not None:
                    image_width = int(extent.get("cx", 0)) / 914400
                    image_height = int(extent.get("cy", 0)) / 914400
            image_style = "max-width:100%;height:auto"
            if image_width:
                image_style = (
                    f"width:{image_width:g}in;max-width:100%;height:auto"
                )
            elif image_height:
                image_style = f"height:{image_height:g}in;max-width:100%;width:auto"
            text_parts.append(
                f'<img loading="lazy" decoding="async" '
                f'src="data:{escape(image_part.content_type)};base64,'
                f'{image_data}" alt="Report image" style="{image_style}">'
            )

        content = "".join(text_parts)
        if not content:
            return ""
        style_name = paragraph.style.name if paragraph.style else ""
        if style_name.startswith("Heading"):
            try:
                level = min(max(int(style_name.rsplit(" ", 1)[-1]), 1), 3)
            except ValueError:
                level = 2
            heading_alignment = {
                0: "left",
                1: "center",
                2: "right",
                3: "justify",
            }.get(paragraph.alignment, "left")
            return (
                f'<h{level} class="document-heading" '
                f'style="text-align:{heading_alignment}">{content}</h{level}>'
            )

        alignment = {
            0: "left",
            1: "center",
            2: "right",
            3: "justify",
        }.get(paragraph.alignment, "left")
        paragraph_class = "header-paragraph" if in_header else "document-paragraph"
        return (
            f'<p class="{paragraph_class}" style="text-align:{alignment}">'
            f"{content}</p>"
        )

    def render_table(table, *, in_header=False, max_width=6.97):
        if not table.rows:
            return ""
        single_cell = len(table.columns) == 1
        table_class = "header-table" if in_header else "document-table"
        if single_cell:
            table_class += " cover-table"
        column_widths = [
            column.width.inches if column.width else None
            for column in table.columns
        ]
        if in_header:
            table_style = "width:100%;border-collapse:collapse;table-layout:fixed"
        elif single_cell:
            table_style = (
                "width:80%;margin:45mm auto 12mm;border-collapse:collapse;"
                "table-layout:fixed"
            )
        else:
            table_width = sum(width for width in column_widths if width)
            table_width = min(table_width or 5.8, max_width)
            table_style = (
                f"width:{table_width:g}in;max-width:100%;margin:6px auto 10px;"
                "border-collapse:collapse;table-layout:fixed"
            )
        rows = []
        for row_index, row in enumerate(table.rows):
            cells = []
            column_index = 0
            seen_cells = set()
            for cell in row.cells:
                cell_key = id(cell._tc)
                if cell_key in seen_cells:
                    column_index += 1
                    continue
                seen_cells.add(cell_key)
                grid_span = cell._tc.tcPr.find(qn("w:gridSpan"))
                span = int(grid_span.val) if grid_span is not None else 1
                cell_content = "".join(
                    render_paragraph(paragraph, in_header=in_header)
                    for paragraph in cell.paragraphs
                )
                tag = "th" if row_index == 0 and not single_cell else "td"
                vertical_merge = cell._tc.tcPr.find(qn("w:vMerge"))
                vertical_merge_value = (
                    vertical_merge.get(qn("w:val"))
                    if vertical_merge is not None
                    else None
                )
                if vertical_merge is not None and vertical_merge_value in (None, "continue"):
                    column_index += span
                    continue
                if (
                    vertical_merge_value == "restart"
                    and row_index > 0
                    and table.rows[row_index - 1].cells[column_index]._tc is cell._tc
                ):
                    column_index += span
                    continue
                rowspan = 1
                if (
                    vertical_merge is not None
                    and vertical_merge_value == "restart"
                ):
                    for following_row in table.rows[row_index + 1:]:
                        if column_index >= len(following_row.cells):
                            break
                        if following_row.cells[column_index]._tc is not cell._tc:
                            break
                        rowspan += 1
                cell_width = sum(
                    width
                    for width in column_widths[column_index:column_index + span]
                    if width
                )
                cell_styles = []
                if cell_width:
                    cell_styles.append(f"width:{cell_width:g}in")
                if cell._tc.tcPr.find(qn("w:noWrap")) is not None:
                    cell_styles.append("white-space:nowrap;overflow-wrap:normal")
                shading = cell._tc.tcPr.find(qn("w:shd"))
                shading_fill = (
                    shading.get(qn("w:fill"))
                    if shading is not None
                    else None
                )
                if shading_fill and shading_fill != "auto":
                    cell_styles.append(f"background-color:#{shading_fill}")
                style_attr = (
                    f' style="{";".join(cell_styles)}"'
                    if cell_styles
                    else ""
                )
                colspan_attr = f' colspan="{span}"' if span > 1 else ""
                rowspan_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ""
                cells.append(
                    f"<{tag}{colspan_attr}{rowspan_attr}{style_attr}>"
                    f"{cell_content}</{tag}>"
                )
                column_index += span
            rows.append(f"<tr>{''.join(cells)}</tr>")
        colgroup = ""
        if not single_cell and any(column_widths):
            colgroup = "<colgroup>" + "".join(
                f'<col style="width:{width:g}in">'
                if width
                else "<col>"
                for width in column_widths
            ) + "</colgroup>"
        return (
            f'<table class="{table_class}" style="{table_style}">'
            f'{colgroup}<tbody>{"".join(rows)}</tbody></table>'
        )

    def render_header(header):
        rendered = []
        for element in header._element.iterchildren():
            if element.tag == qn("w:p"):
                content = render_paragraph(Paragraph(element, header), in_header=True)
            elif element.tag == qn("w:tbl"):
                content = render_table(Table(element, header), in_header=True)
            else:
                continue
            if content:
                rendered.append(content)
        return "".join(rendered)

    page_data = []

    def make_page(section_index):
        section_index = min(section_index, len(sections) - 1)
        section = sections[section_index]
        page_data.append({
            "orientation": (
                "landscape"
                if section.page_width > section.page_height
                else "portrait"
            ),
            "page_style": (
                f"width:{section.page_width.inches:g}in;"
                f"min-height:{section.page_height.inches:g}in"
            ),
            "header_html": render_header(section.header),
            "content_html": [],
        })

    current_section = 0
    make_page(current_section)
    body = document._element.body
    for element in body.iterchildren():
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document)
            content = render_paragraph(paragraph)
            if content:
                page_data[-1]["content_html"].append(content)
            has_section_break = bool(element.xpath("./w:pPr/w:sectPr"))
            has_page_break = bool(element.xpath(".//w:br[@w:type='page']"))
            if has_section_break or has_page_break:
                if has_section_break:
                    current_section += 1
                if (
                    page_data[-1]["content_html"]
                    or page_data[-1]["orientation"]
                    != (
                        "landscape"
                        if sections[min(current_section, len(sections) - 1)].page_width
                        > sections[min(current_section, len(sections) - 1)].page_height
                        else "portrait"
                    )
                ):
                    make_page(current_section)
        elif element.tag == qn("w:tbl"):
            page_data[-1]["content_html"].append(
                render_table(
                    Table(element, document),
                    max_width=14.75
                    if page_data[-1]["orientation"] == "landscape"
                    else 6.97,
                )
            )

    page_data = [
        {
            **page,
            "content_html": "".join(page["content_html"]),
        }
        for page in page_data
        if page["content_html"] or len(page_data) == 1
    ]
    return page_data
