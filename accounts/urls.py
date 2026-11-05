from django.urls import path
from . import views

urlpatterns = [

    path("login/", views.login_view, name="login"),
    path("", views.home, name="home"),
    path("logout/", views.logout_view, name="logout"),
    path("no-permission/", views.no_permission, name="no_permission"),

    path("hod/dashboard/", views.hod_dashboard, name="hod_dashboard"),
    path(
        "hod/course-completion/",
        views.hod_course_completion,
        name="hod_course_completion",
    ),
    path(
        "hod/report-header/",
        views.department_report_header,
        name="department_report_header",
    ),
    path("hod/create-teacher/", views.create_teacher, name="create_teacher"),
    path("hod/reset-teacher-password/", views.reset_teacher_password, name="reset_teacher_password"),
    path("hod/manage-po/", views.manage_po, name="manage_po"),
    path("hod/manage-pso/", views.manage_pso, name="manage_pso"),
    path('course/<int:course_id>/co/', views.manage_co, name='manage_co'),
    path(
        'course/<int:course_id>/matrix/',
        views.co_po_pso_matrix,
        name='co_po_pso_matrix'
    ),
    path(
        "course/<int:course_id>/performance-indicators/",
        views.course_performance_indicators,
        name="course_performance_indicators",
    ),
    path(
        "course/<int:course_id>/performance-indicators/import/",
        views.import_course_performance_indicators,
        name="import_course_performance_indicators",
    ),
    path(
        "course/<int:course_id>/performance-indicators/template/",
        views.export_course_performance_indicators_template,
        name="export_course_performance_indicators_template",
    ),
    path(
        "course/<int:course_id>/mapping-grade/",
        views.course_mapping_grade,
        name="course_mapping_grade",
    ),
    path("faculty/dashboard/", views.faculty_dashboard, name="faculty_dashboard"),

    path(
        "class/<int:class_id>/students/",
        views.assign_students,
        name="assign_students"
    ),

    path(
        "class/<int:class_id>/students/export/",
        views.export_class_students_excel,
        name="export_class_students_excel"
    ),

    path(
        "class/<int:class_id>/students/import/",
        views.import_class_students_excel,
        name="import_class_students_excel"
    ),
    path(
        "hod/class/<int:class_id>/",
        views.class_dashboard,
        name="class_dashboard"
    ),
    path(
        "hod/class/<int:class_id>/po-pso-attainment/",
        views.class_po_pso_attainment,
        name="class_po_pso_attainment",
    ),
    path(
        "hod/class/<int:class_id>/po-pso-average/",
        views.class_po_pso_average,
        name="class_po_pso_average",
    ),
    path(
        "hod/class/<int:class_id>/weighted-co-levels/",
        views.class_weighted_co_levels,
        name="class_weighted_co_levels",
    ),
    path(
        "hod/class/<int:class_id>/co-gap-quality-loop/",
        views.class_co_gap_quality_report,
        name="class_co_gap_quality_report",
    ),

    path(
        "hod/class/<int:class_id>/courses/",
        views.create_course,
        name="create_course"
    ),
    path(
        "course/<int:course_id>/delete/",
        views.delete_course,
        name="delete_course"
    ),
    path(
        "teacher/<int:teacher_id>/delete/",
        views.delete_teacher,
        name="delete_teacher"
    ),

    # buttons (logic can be empty for now)
    path("course/<int:course_id>/assign/", views.assign_course_teacher, name="assign_course_teacher"),
    path("course/<int:course_id>/view/", views.view_course, name="view_course"),
    path("gs/classes/", views.gs_class_list, name="gs_class_list"),
    path("gs/classes/create/", views.gs_class_create, name="gs_class_create"),
    path("gs/sem/edit/<str:year>/<str:sem>/", views.gs_sem_edit, name="gs_sem_edit"),
    path("gs/sem/update/<str:year>/<str:sem>/", views.gs_sem_update, name="gs_sem_update"),

    path("dept/classes/", views.dept_class_list, name="dept_class_list"),
    path("dept/classes/create/", views.dept_class_create, name="dept_class_create"),

    path(
        "dept/classes/edit/<str:year>/<str:sem>/",
        views.dept_sem_edit,
        name="dept_sem_edit"
    ),

    path(
        "dept/classes/update/<str:year>/<str:sem>/",
        views.dept_sem_update,
        name="dept_sem_update"
    ),
    path("tools/<int:course_id>/", views.assessment_tool_page, name="assessment_tool_page"),
    path(
        "tools/delete/<int:tool_id>/",
        views.delete_assessment_tool,
        name="delete_assessment_tool"
    ),

    path(
        "tools/ica/<int:tool_id>/",
        views.ica_tool_detail,
        name="ica_tool_detail"
    ),

    path(
        "tools/assignment/<int:tool_id>/",
        views.assignment_tutorial_page,
        name="assignment_tutorial_page"
    ),
    path(
        "tools/exam/<int:tool_id>/",
        views.exam_details,
        name="exam_details"
    ),
    path(
        "tools/university_exam/<int:tool_id>/",
        views.university_exam_page,
        name="university_exam_page"
    ),
    path(
        "tools/university_exam/<int:tool_id>/export/",
        views.export_university_exam_excel,
        name="export_university_exam_excel"
    ),

    path(
        "tools/university_exam/<int:tool_id>/import/",
        views.import_university_exam_excel,
        name="import_university_exam_excel"
    ),
    path(
        "ica/student-marks/<int:tool_id>/",
        views.ica_student_marks,
        name="ica_student_marks"
    ),

    path(
        "assignment/tutorial/<int:tool_id>/",
        views.assignment_tutorial_marks,
        name="assignment_tutorial_marks"
    ),

    path(
        "exam/<int:tool_id>/",
        views.exam_marks,
        name="exam_marks"
    ),
    path(
        "university-exam/<int:tool_id>/marks/",
        views.university_exam_marks,
        name="university_exam_marks"
    ),
    path(
        "course/<int:course_id>/assessment_pattern/",
        views.assessment_pattern,
        name="assessment_pattern"
    ),
    path(
        "course/<int:course_id>/co-target/",
        views.co_target_page,
        name="co_target_page"
    ),
    path(
        "course/<int:course_id>/exit-survey/",
        views.course_exit_survey,
        name="course_exit_survey"
    ),
    path('tool/<int:tool_id>/co-summary/', views.tool_marks_co_summary, name='tool_marks_co_summary'),
    path('course/<int:course_id>/co-attainment-sheet/', views.co_attainment_sheet, name='co_attainment_sheet'),
    path(
        'course/<int:course_id>/co-attainment-gap/',
        views.co_attainment_sheet,
        {'report_type': 'gap'},
        name='co_attainment_gap',
    ),
    path(
        'course/<int:course_id>/co-po-pso-attainment/',
        views.co_attainment_sheet,
        {'report_type': 'po_pso'},
        name='co_po_pso_attainment',
    ),
    path(
        'course/<int:course_id>/report-preview/',
        views.course_report_preview,
        name='course_report_preview',
    ),


]
