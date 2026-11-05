from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from .models import (
    AcademicClass,
    AssignmentTool,
    COPOMapping,
    COPSOMapping,
    CollegeReportSettings,
    Course,
    CourseOutcome,
    CoursePerformanceIndicator,
    COTarget,
    Department,
    ExamDetail,
    ExamMarks,
    ProgramOutcome,
    ProgramSpecificOutcome,
    AssessmentTool,
    AssignmentTutorialMarks,
    AttainmentWeightage,
    CourseExitSurvey,
    IcaAssignmentExp,
    IcaStudentMarks,
    Student,
    UniversityExam,
    UniversityExamMarks,
    User,
)


class OutcomeMappingPreservationTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Engineering")
        self.user = User.objects.create_user(
            username="department-head",
            password="test-password",
            role="HOD",
            department=self.department,
        )
        self.academic_class = AcademicClass.objects.create(
            department=self.department,
            name="SE",
            academic_year="2026-27",
            semester="3",
        )
        self.course = Course.objects.create(
            academic_class=self.academic_class,
            course_code="CS101",
            course_name="Programming",
        )
        self.course_outcome = CourseOutcome.objects.create(
            course=self.course,
            co_number=1,
            description="Apply programming concepts",
        )
        self.student = Student.objects.create(
            roll_no="1",
            name="Test Student",
            academic_class=self.academic_class,
            department=self.department,
        )
        self.tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="Assignment",
            sub_tool="Tutorial 1",
        )
        self.question = AssignmentTool.objects.create(
            tool=self.tool,
            question_no="Q1",
            co=self.course_outcome,
            marks=10,
        )
        self.po = ProgramOutcome.objects.create(
            department=self.department,
            po_number="PO1",
            description="Original program outcome",
        )
        self.pso = ProgramSpecificOutcome.objects.create(
            department=self.department,
            pso_number="PSO1",
            description="Original specific outcome",
        )
        self.po_mapping = COPOMapping.objects.create(
            co=self.course_outcome,
            po=self.po,
            level=2,
        )
        self.pso_mapping = COPSOMapping.objects.create(
            co=self.course_outcome,
            pso=self.pso,
            level=3,
        )
        self.client.force_login(self.user)

    def test_editing_co_preserves_omitted_outcomes_and_mappings(self):
        self.course.faculty = self.user
        self.course.save(update_fields=["faculty"])
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Preserve this outcome",
        )
        second_mapping = COPSOMapping.objects.create(
            co=second_co,
            pso=self.pso,
            level=1,
        )

        response = self.client.post(
            reverse("manage_co", args=[self.course.id]),
            {
                "co_count": "1",
                "co_desc_1": "Updated programming outcome",
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("view_course", args=[self.course.id]),
            fetch_redirect_response=False,
        )
        self.course_outcome.refresh_from_db()
        second_co.refresh_from_db()
        self.assertEqual(
            self.course_outcome.description,
            "Updated programming outcome",
        )
        self.assertEqual(second_co.description, "Preserve this outcome")
        self.assertTrue(COPSOMapping.objects.filter(pk=second_mapping.pk).exists())
        self.assertTrue(
            AssignmentTool.objects.filter(
                pk=self.question.pk,
                co=self.course_outcome,
            ).exists()
        )

    def test_blank_co_description_does_not_clear_existing_outcome(self):
        self.course.faculty = self.user
        self.course.save(update_fields=["faculty"])

        response = self.client.post(
            reverse("manage_co", args=[self.course.id]),
            {
                "co_count": "1",
                "co_desc_1": "   ",
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("view_course", args=[self.course.id]),
            fetch_redirect_response=False,
        )
        self.course_outcome.refresh_from_db()
        self.assertEqual(
            self.course_outcome.description,
            "Apply programming concepts",
        )

    def test_nonempty_new_co_description_creates_outcome(self):
        self.course.faculty = self.user
        self.course.save(update_fields=["faculty"])

        response = self.client.post(
            reverse("manage_co", args=[self.course.id]),
            {
                "co_count": "2",
                "co_desc_1": "Apply programming concepts",
                "co_desc_2": "Analyze program behavior",
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("view_course", args=[self.course.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            CourseOutcome.objects.get(course=self.course, co_number=2).description,
            "Analyze program behavior",
        )

    def test_assignment_page_renders_co_distribution_form(self):
        response = self.client.get(
            reverse("assignment_tutorial_page", args=[self.tool.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No. of COs")
        self.assertContains(response, "No. of Questions")
        self.assertContains(response, "Total Marks")

    def test_attainment_uses_normalized_direct_weights_and_indirect_survey_weight(self):
        cie_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ICA",
            sub_tool="Experiment",
        )
        cie_item = IcaAssignmentExp.objects.create(
            tool=cie_tool,
            sub_tool_no=1,
            co=self.course_outcome,
            bl="BL1",
            marks=100,
        )
        IcaStudentMarks.objects.create(
            tool=cie_tool,
            student=self.student,
            subtool=cie_item,
            marks=80,
        )
        ese_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ESE",
            sub_tool="Final",
        )
        UniversityExam.objects.create(
            tool=ese_tool,
            co=self.course_outcome,
            marks=100,
        )
        UniversityExamMarks.objects.create(
            tool=ese_tool,
            student=self.student,
            marks=51,
        )
        CourseExitSurvey.objects.create(
            course=self.course,
            course_outcome=self.course_outcome,
            strongly_agree=1,
        )
        AttainmentWeightage.objects.create(
            course=self.course,
            direct_attainment=90,
            indirect_attainment=10,
            cie_weightage=40,
            ese_weightage=60,
            survey_weightage=10,
        )

        response = self.client.get(
            reverse("co_attainment_sheet", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        direct_row = response.context["direct_attainment_rows"][0]
        total_row = response.context["total_attainment_rows"][0]
        self.assertEqual(direct_row["direct_attainment"], 62.6)
        self.assertEqual(direct_row["direct_attainment_rounded"], 63)
        self.assertEqual(total_row["indirect_attainment"], 100.0)
        self.assertEqual(total_row["direct_attainment_rounded"], 63)
        self.assertEqual(total_row["total_attainment"], 66.7)

    def test_co_attainment_gap_uses_total_attainment_and_saved_target(self):
        COTarget.objects.create(
            course=self.course,
            course_outcome=self.course_outcome,
            target_percentage=50,
        )
        ese_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ESE",
            sub_tool="University Exam",
        )
        UniversityExam.objects.create(
            tool=ese_tool,
            co=self.course_outcome,
            marks=100,
        )
        UniversityExamMarks.objects.create(
            tool=ese_tool,
            student=self.student,
            marks=74,
        )

        response = self.client.get(
            reverse("co_attainment_gap", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        row = response.context["gap_rows"][0]
        self.assertEqual(row["target"], 50)
        self.assertEqual(row["attainment"], 41)
        self.assertEqual(row["gap"], 9)
        self.assertEqual(row["focus"], "More focus on this CO")
        self.assertContains(response, "CO Attainment Gap")
        self.assertContains(response, "Target - Attainment")
        self.assertContains(response, 'id="co-attainment-gap-chart"')
        self.assertContains(response, 'id="gap-chart-data"')
        self.assertContains(response, "No action recorded")
        self.assertNotContains(response, "<textarea")

        edit_response = self.client.get(
            reverse("co_attainment_gap", args=[self.course.id]),
            {"edit": "1"},
            secure=True,
        )
        self.assertContains(edit_response, "Save changes")
        self.assertContains(edit_response, f'name="action_{self.course_outcome.id}"')
        self.assertContains(edit_response, f'name="modification_{self.course_outcome.id}"')

        save_response = self.client.post(
            reverse("co_attainment_gap", args=[self.course.id]),
            {
                f"action_{self.course_outcome.id}": "Add a practical revision session.",
                f"modification_{self.course_outcome.id}": "Raise the target to 75%.",
            },
            secure=True,
        )
        self.assertEqual(save_response.status_code, 302)

        saved_response = self.client.get(
            reverse("co_attainment_gap", args=[self.course.id]),
            secure=True,
        )
        self.assertContains(saved_response, "Add a practical revision session.")
        self.assertContains(saved_response, "Raise the target to 75%.")
        self.assertNotContains(saved_response, "<textarea")

    def test_class_co_gap_quality_report_renders_course_sections_and_dashboard_link(self):
        self.department.report_department_name = "Department of Mechanical Engineering"
        self.department.report_accreditation = "NBA Accredited"
        self.department.report_email = "mech@example.edu"
        self.department.report_hod_name = "Dr. Department HOD"
        self.department.report_hod_qualification = "M.E., Ph.D. (Mechanical Engineering)"
        self.department.save()
        CollegeReportSettings.objects.update_or_create(
            pk=1,
            defaults={"website": "https://www.sknscoe.ac.in"},
        )
        second_course = Course.objects.create(
            academic_class=self.academic_class,
            course_code="CS102",
            course_name="Data Structures",
        )
        CourseOutcome.objects.create(
            course=second_course,
            co_number=1,
            description="Use data structures",
        )

        response = self.client.get(
            reverse(
                "class_co_gap_quality_report",
                args=[self.academic_class.id],
            ),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["course_reports"]), 2)
        self.assertEqual(
            [report["course"].course_code for report in response.context["course_reports"]],
            ["CS101", "CS102"],
        )
        self.assertContains(response, "Programming")
        self.assertContains(response, "Data Structures")
        self.assertContains(response, "Closure of Quality Loop")
        self.assertContains(response, "A/p- Korti, Tal- Pandharpur")
        self.assertContains(response, "Dr. Department HOD")
        self.assertContains(response, "mech@example.edu")
        self.assertContains(response, "https://www.sknscoe.ac.in")
        self.assertEqual(response.content.count(b'class="course-page"'), 2)

        dashboard_response = self.client.get(
            reverse("class_dashboard", args=[self.academic_class.id]),
            secure=True,
        )
        self.assertContains(
            dashboard_response,
            reverse(
                "class_co_gap_quality_report",
                args=[self.academic_class.id],
            ),
        )

    def test_class_co_gap_quality_report_downloads_one_word_page_per_course(self):
        self.user.first_name = "Onkar"
        self.user.last_name = "Thigale"
        self.user.save(update_fields=["first_name", "last_name"])
        self.course.faculty = self.user
        self.course.save(update_fields=["faculty"])
        self.department.report_department_name = "Department of Mechanical Engineering"
        self.department.report_accreditation = "NBA Accredited"
        self.department.report_email = "mech@example.edu"
        self.department.report_hod_name = "Dr. Department HOD"
        self.department.report_hod_qualification = "M.E., Ph.D. (Mechanical Engineering)"
        self.department.save()
        CollegeReportSettings.objects.update_or_create(
            pk=1,
            defaults={"website": "https://www.sknscoe.ac.in"},
        )
        second_course = Course.objects.create(
            academic_class=self.academic_class,
            course_code="CS102",
            course_name="Data Structures",
        )
        CourseOutcome.objects.create(
            course=second_course,
            co_number=1,
            description="Use data structures",
        )

        response = self.client.get(
            reverse(
                "class_co_gap_quality_report",
                args=[self.academic_class.id],
            ),
            {"download": "docx"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertIn("attachment; filename=", response["Content-Disposition"])

        from docx import Document

        document = Document(BytesIO(response.content))
        document_text = "\n".join(
            [paragraph.text for paragraph in document.paragraphs]
            + [
                cell.text
                for table in document.tables
                for row in table.rows
                for cell in row.cells
            ]
        )
        self.assertIn("Programming", document_text)
        self.assertIn("Data Structures", document_text)
        self.assertIn("Closure of Quality Loop", document_text)
        header_text = "\n".join(
            cell.text
            for table in document.sections[0].header.tables
            for row in table.rows
            for cell in row.cells
        )
        self.assertIn("SKN SINHGAD COLLEGE OF ENGINEERING", header_text)
        self.assertIn("Department of Mechanical Engineering", header_text)
        self.assertIn("A/p- Korti, Tal- Pandharpur", header_text)
        self.assertIn("e-mail: mech@example.edu", header_text)
        self.assertIn("Website: https://www.sknscoe.ac.in", header_text)
        self.assertIn("Dr. Department HOD", header_text)
        self.assertIn("mech@example.edu", header_text)
        self.assertIn("https://www.sknscoe.ac.in", header_text)
        self.assertEqual(len(document.sections[0].header.tables), 2)
        officials_table = document.sections[0].header.tables[1]
        self.assertEqual(
            [cell.width for cell in officials_table.rows[0].cells],
            [officials_table.columns[0].width, officials_table.columns[1].width],
        )
        for cell in officials_table.rows[0].cells:
            self.assertEqual(cell.vertical_alignment, 1)
            self.assertTrue(
                all(paragraph.alignment == 1 for paragraph in cell.paragraphs)
            )
        logo = document.sections[0].header.tables[0]._element.xpath(".//wp:inline")
        self.assertEqual(len(logo), 1)
        self.assertAlmostEqual(logo[0].extent.cx / 914400, 1.05, places=2)
        self.assertEqual(len(document.tables), 8)
        signature_table = document.tables[3]
        self.assertEqual(
            signature_table.alignment,
            0,
        )
        self.assertEqual(
            [cell.text for cell in signature_table.rows[0].cells],
            ["Sr.No.", "Name of Subject Teacher", "Sign"],
        )
        self.assertEqual(
            [cell.text for cell in signature_table.rows[1].cells],
            ["1.", "Onkar Thigale", ""],
        )
        signature_table_element = signature_table._tbl
        signature_table_position = list(document._element.body).index(
            signature_table_element
        )
        spacer_element = list(document._element.body)[signature_table_position - 1]
        self.assertEqual(spacer_element.tag.rsplit("}", 1)[-1], "p")
        spacer = next(
            paragraph
            for paragraph in document.paragraphs
            if paragraph._p is spacer_element
        )
        self.assertGreaterEqual(spacer.paragraph_format.space_before.pt, 8)
        self.assertEqual(
            len(document._element.xpath(".//w:br[@w:type='page']")),
            1,
        )

    def test_class_co_gap_quality_report_is_hod_only(self):
        faculty = User.objects.create_user(
            username="report-faculty",
            password="test-password",
            role="FACULTY",
            department=self.department,
        )
        self.client.force_login(faculty)

        response = self.client.get(
            reverse(
                "class_co_gap_quality_report",
                args=[self.academic_class.id],
            ),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)

    def test_hod_can_save_department_report_header_details(self):
        dashboard_response = self.client.get(reverse("hod_dashboard"), secure=True)
        self.assertContains(dashboard_response, "Word Report Header")
        self.assertContains(
            dashboard_response,
            reverse("department_report_header"),
        )

        edit_response = self.client.get(
            reverse("department_report_header"),
            secure=True,
        )
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, "Department accreditation")
        self.assertContains(edit_response, "College website")
        self.assertContains(edit_response, "Edit details")
        self.assertNotContains(edit_response, 'name="report_department_name"')
        self.assertNotContains(edit_response, 'name="website"')

        editable_response = self.client.get(
            reverse("department_report_header"),
            {"edit": "1"},
            secure=True,
        )
        self.assertContains(editable_response, 'name="report_department_name"')
        self.assertContains(editable_response, 'name="website"')
        self.assertContains(editable_response, "Save header details")

        save_response = self.client.post(
            reverse("department_report_header"),
            {
                "report_department_name": "Department of Civil Engineering",
                "report_accreditation": "NBA Accredited",
                "report_email": "civil@example.edu",
                "website": "https://www.sknscoe.ac.in",
                "report_hod_name": "Dr. Civil HOD",
                "report_hod_qualification": "M.E., Ph.D. (Civil Engineering)",
            },
            secure=True,
        )
        self.assertRedirects(
            save_response,
            reverse("department_report_header"),
            fetch_redirect_response=False,
        )
        self.department.refresh_from_db()
        self.assertEqual(self.department.report_department_name, "Department of Civil Engineering")
        self.assertEqual(self.department.report_accreditation, "NBA Accredited")
        self.assertEqual(self.department.report_email, "civil@example.edu")
        self.assertEqual(
            CollegeReportSettings.objects.get(pk=1).website,
            "https://www.sknscoe.ac.in",
        )
        self.assertEqual(self.department.report_hod_name, "Dr. Civil HOD")
        self.assertEqual(
            self.department.report_hod_qualification,
            "M.E., Ph.D. (Civil Engineering)",
        )
        readonly_response = self.client.get(
            reverse("department_report_header"),
            secure=True,
        )
        self.assertContains(readonly_response, "Department of Civil Engineering")
        self.assertContains(readonly_response, "https://www.sknscoe.ac.in")
        self.assertNotContains(readonly_response, 'name="report_department_name"')

    def test_non_hod_cannot_edit_department_report_header(self):
        faculty = User.objects.create_user(
            username="department-faculty",
            password="test-password",
            role="FACULTY",
            department=self.department,
        )
        self.client.force_login(faculty)

        response = self.client.get(
            reverse("department_report_header"),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)

    def test_academic_year_must_use_full_academic_year_format(self):
        self.academic_class.academic_year = "2"
        with self.assertRaises(ValidationError):
            self.academic_class.full_clean()

        self.academic_class.academic_year = "2025-26"
        self.academic_class.full_clean()

    def test_hod_dashboard_links_to_separate_course_completion_page(self):
        unassigned_course = Course.objects.create(
            academic_class=self.academic_class,
            course_code="CS102",
            course_name="Unassigned course",
        )

        response = self.client.get(reverse("hod_dashboard"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Course Completion")
        self.assertContains(response, reverse("hod_course_completion"))
        self.assertNotContains(response, "Department course completion")
        self.assertNotContains(response, "Unassigned course")

        completion_response = self.client.get(
            reverse("hod_course_completion"),
            secure=True,
        )
        self.assertEqual(completion_response.status_code, 200)
        completion_rows = {
            row["course"].id: row
            for class_group in completion_response.context["class_groups"]
            for row in class_group["rows"]
        }
        self.assertEqual(set(completion_rows), {self.course.id, unassigned_course.id})
        configured_course = completion_rows[self.course.id]
        self.assertEqual(configured_course["status"], "In progress")
        self.assertEqual(configured_course["total_count"], 7)
        self.assertIn("Student marks", configured_course["pending_sections"])
        self.assertIn("Attainment weightage and CO targets", configured_course["pending_sections"])
        self.assertIn("CO-PO-PSO Attainment", configured_course["pending_sections"])
        self.assertEqual(
            completion_rows[unassigned_course.id]["status"],
            "Not started",
        )
        self.assertContains(
            completion_response,
            reverse("co_po_pso_attainment", args=[self.course.id]),
        )

    def test_hod_course_completion_page_filters_subjects_by_class_and_search(self):
        other_class = AcademicClass.objects.create(
            department=self.department,
            name="TE",
            academic_year="2025-26",
            semester="5",
        )
        other_course = Course.objects.create(
            academic_class=other_class,
            course_code="CS202",
            course_name="Distributed Systems",
            faculty=self.user,
        )

        response = self.client.get(
            reverse("hod_course_completion"),
            {
                "year": "2025-26",
                "class": str(other_class.id),
                "faculty": str(self.user.id),
                "status": "Not started",
                "q": "distributed",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        grouped_rows = [
            row
            for class_group in response.context["class_groups"]
            for row in class_group["rows"]
        ]
        self.assertEqual(
            [row["course"].id for row in grouped_rows],
            [other_course.id],
        )
        self.assertEqual(response.context["course_count"], 1)
        self.assertContains(response, "Class-wise subject completion")
        self.assertContains(response, "Distributed Systems")
        self.assertNotContains(response, "Programming")
        self.assertContains(response, 'name="faculty"')
        self.assertContains(response, 'name="status"')

    def test_non_hod_cannot_access_hod_course_completion_page(self):
        faculty = User.objects.create_user(
            username="completion-faculty",
            password="test-pass",
            role="FACULTY",
            department=self.department,
        )
        self.client.force_login(faculty)

        response = self.client.get(
            reverse("hod_course_completion"),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)

    def test_class_dashboard_links_to_class_po_pso_attainment_summary(self):
        response = self.client.get(
            reverse("class_dashboard", args=[self.academic_class.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PO-PSO Attainment Summary")
        self.assertContains(
            response,
            reverse("class_po_pso_attainment", args=[self.academic_class.id]),
        )
        self.assertContains(response, "course articulation matrix (PO & PSO Mapping)")
        self.assertContains(
            response,
            reverse("class_po_pso_average", args=[self.academic_class.id]),
        )
        self.assertContains(response, "Course-wise Weighted CO Level")
        self.assertContains(
            response,
            reverse("class_weighted_co_levels", args=[self.academic_class.id]),
        )

    def test_class_po_pso_attainment_summary_shows_all_subjects_and_mapping_levels(self):
        second_course = Course.objects.create(
            academic_class=self.academic_class,
            course_code="CS102",
            course_name="Data Structures",
        )
        po_indicator = CoursePerformanceIndicator.objects.create(
            course=self.course,
            po=self.po,
            competency_level="1",
            competency_description="Programming competency",
            indicator_code="PO1.1",
            indicator_description="Apply programming skills",
        )
        po_indicator.course_outcomes.add(self.course_outcome)
        CoursePerformanceIndicator.objects.create(
            course=self.course,
            po=self.po,
            competency_level="2",
            competency_description="Programming competency",
            indicator_code="PO1.2",
            indicator_description="Analyze programming skills",
        )
        pso_indicator = CoursePerformanceIndicator.objects.create(
            course=self.course,
            pso=self.pso,
            competency_level="1",
            competency_description="Department competency",
            indicator_code="PSO1.1",
            indicator_description="Apply department skills",
        )
        pso_indicator.course_outcomes.add(self.course_outcome)

        dashboard_response = self.client.get(
            reverse("class_dashboard", args=[self.academic_class.id]),
            secure=True,
        )
        response = self.client.get(
            reverse("class_po_pso_attainment", args=[self.academic_class.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(dashboard_response, "PO-PSO Attainment Summary")
        self.assertContains(response, "DIRECT ATTAINMENT OF PO-PSOS")
        self.assertContains(response, "CS101")
        self.assertContains(response, "CS102")
        self.assertContains(response, "PO1")
        self.assertContains(response, "PSO1")
        subject_rows = response.context["subject_rows"]
        self.assertEqual(len(subject_rows), 2)
        self.assertEqual(subject_rows[0]["course"], self.course)
        self.assertEqual(subject_rows[0]["cells"], [2, 3])
        self.assertEqual(subject_rows[1]["course"], second_course)
        self.assertEqual(subject_rows[1]["cells"], ["", ""])
        self.po_mapping.refresh_from_db()
        self.assertEqual(self.po_mapping.level, 2)
        self.assertNotContains(response, ">Print<")
        self.assertContains(response, "Export Excel")

        export_response = self.client.get(
            reverse("class_po_pso_attainment", args=[self.academic_class.id]),
            {"export": "excel"},
            secure=True,
        )
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(
            export_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        workbook = load_workbook(BytesIO(export_response.content), data_only=True)
        worksheet = workbook["PO-PSO Attainment"]
        self.assertEqual(worksheet["A1"].value, "DIRECT ATTAINMENT OF PO-PSOS")
        self.assertEqual(
            [worksheet.cell(row=4, column=column).value for column in range(1, 6)],
            ["SR.NO", "Course Code", "Course Name", "PO1", "PSO1"],
        )
        self.assertEqual(
            [worksheet.cell(row=5, column=column).value for column in range(1, 6)],
            [1, "CS101", "Programming", 2, 3],
        )

    def test_class_po_pso_average_shows_only_course_average_levels(self):
        second_course = Course.objects.create(
            academic_class=self.academic_class,
            course_code="CS102",
            course_name="Data Structures",
        )
        po_indicator = CoursePerformanceIndicator.objects.create(
            course=self.course,
            po=self.po,
            competency_level="1",
            competency_description="Programming competency",
            indicator_code="PO1.1",
            indicator_description="Apply programming skills",
        )
        po_indicator.course_outcomes.add(self.course_outcome)
        CoursePerformanceIndicator.objects.create(
            course=self.course,
            po=self.po,
            competency_level="2",
            competency_description="Programming competency",
            indicator_code="PO1.2",
            indicator_description="Analyze programming skills",
        )
        pso_indicator = CoursePerformanceIndicator.objects.create(
            course=self.course,
            pso=self.pso,
            competency_level="1",
            competency_description="Department competency",
            indicator_code="PSO1.1",
            indicator_description="Apply department skills",
        )
        pso_indicator.course_outcomes.add(self.course_outcome)

        response = self.client.get(
            reverse("class_po_pso_average", args=[self.academic_class.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "COURSE ARTICULATION MATRIX (PO &amp; PSO MAPPING)",
        )
        self.assertContains(response, "CS101")
        self.assertContains(response, "CS102")
        self.assertContains(response, "PO1")
        self.assertContains(response, "PSO1")
        rows = response.context["subject_rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["course"], self.course)
        self.assertEqual(rows[0]["averages"], [2, 3])
        self.assertEqual(rows[1]["course"], second_course)
        self.assertEqual(rows[1]["averages"], [0, 0])
        self.assertNotContains(response, "CO1")
        self.assertNotContains(response, ">Print<")
        self.assertContains(response, "Export Excel")

        export_response = self.client.get(
            reverse("class_po_pso_average", args=[self.academic_class.id]),
            {"export": "excel"},
            secure=True,
        )
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(
            export_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        workbook = load_workbook(BytesIO(export_response.content), data_only=True)
        worksheet = workbook["PO-PSO Average"]
        self.assertEqual(
            worksheet["A1"].value,
            "COURSE ARTICULATION MATRIX (PO & PSO MAPPING)",
        )
        self.assertEqual(
            [worksheet.cell(row=4, column=column).value for column in range(1, 6)],
            ["SR.NO", "Course Code", "Course Name", "PO1", "PSO1"],
        )
        self.assertEqual(
            [worksheet.cell(row=5, column=column).value for column in range(1, 6)],
            [1, "CS101", "Programming", 2, 3],
        )

    def test_non_hod_cannot_access_class_po_pso_average(self):
        faculty = User.objects.create_user(
            username="class-average-faculty",
            password="test-pass",
            role="FACULTY",
            department=self.department,
        )
        self.client.force_login(faculty)

        response = self.client.get(
            reverse("class_po_pso_average", args=[self.academic_class.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)

    def test_class_weighted_co_levels_match_course_attainment_report(self):
        COTarget.objects.create(
            course=self.course,
            course_outcome=self.course_outcome,
            target_percentage=50,
        )
        ese_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ESE",
            sub_tool="University Exam",
        )
        UniversityExam.objects.create(
            tool=ese_tool,
            co=self.course_outcome,
            marks=100,
        )
        UniversityExamMarks.objects.create(
            tool=ese_tool,
            student=self.student,
            marks=74,
        )

        response = self.client.get(
            reverse("class_weighted_co_levels", args=[self.academic_class.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LEVEL OF WEIGHTED CO")
        self.assertContains(response, "CO1")
        self.assertEqual(response.context["co_columns"], ["CO1"])
        self.assertEqual(
            response.context["subject_rows"][0]["levels"],
            [2],
        )
        self.assertNotContains(response, ">Print<")
        self.assertContains(response, "Export Excel")
        self.assertFalse(
            AttainmentWeightage.objects.filter(course=self.course).exists()
        )

        export_response = self.client.get(
            reverse("class_weighted_co_levels", args=[self.academic_class.id]),
            {"export": "excel"},
            secure=True,
        )
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(
            export_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        workbook = load_workbook(BytesIO(export_response.content), data_only=True)
        worksheet = workbook["Weighted CO Levels"]
        self.assertEqual(worksheet["A1"].value, "LEVEL OF WEIGHTED CO")
        self.assertEqual(
            [worksheet.cell(row=4, column=column).value for column in range(1, 5)],
            ["SR.NO", "Course Code", "Course Name", "CO1"],
        )
        self.assertEqual(
            [worksheet.cell(row=5, column=column).value for column in range(1, 5)],
            [1, "CS101", "Programming", 2],
        )

    def test_non_hod_cannot_access_class_weighted_co_levels(self):
        faculty = User.objects.create_user(
            username="class-weighted-co-faculty",
            password="test-pass",
            role="FACULTY",
            department=self.department,
        )
        self.client.force_login(faculty)

        response = self.client.get(
            reverse("class_weighted_co_levels", args=[self.academic_class.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)

    def test_non_hod_cannot_access_class_po_pso_attainment_summary(self):
        faculty = User.objects.create_user(
            username="class-summary-faculty",
            password="test-pass",
            role="FACULTY",
            department=self.department,
        )
        self.client.force_login(faculty)

        response = self.client.get(
            reverse("class_po_pso_attainment", args=[self.academic_class.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 403)

    def test_dashboard_marks_are_complete_when_saved_for_assessed_students(self):
        Student.objects.create(
            roll_no="2",
            name="Second Student",
            academic_class=self.academic_class,
            department=self.department,
        )
        AssignmentTutorialMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=self.question,
            marks=5,
        )

        response = self.client.get(
            reverse("hod_course_completion"),
            secure=True,
        )

        course_row = next(
            row
            for class_group in response.context["class_groups"]
            for row in class_group["rows"]
            if row["course"].id == self.course.id
        )
        marks_step = next(
            step for step in course_row["steps"] if step["label"] == "Student marks"
        )
        self.assertTrue(marks_step["complete"])

    def test_co_po_pso_attainment_uses_mapped_co_attainment(self):
        unmapped_po = ProgramOutcome.objects.create(
            department=self.department,
            po_number="PO2",
            description="Unmapped program outcome",
        )
        COTarget.objects.create(
            course=self.course,
            course_outcome=self.course_outcome,
            bl_level="BL2",
            target_percentage=50,
        )
        for outcome, po, pso in ((self.course_outcome, self.po, self.pso),):
            po_indicator = CoursePerformanceIndicator.objects.create(
                course=self.course,
                po=po,
                competency_level="1.1",
                competency_description="Apply concepts",
                indicator_code="1.1.1",
                indicator_description="Apply concepts to a case",
            )
            po_indicator.course_outcomes.add(outcome)
            pso_indicator = CoursePerformanceIndicator.objects.create(
                course=self.course,
                pso=pso,
                competency_level="1.1",
                competency_description="Apply specific concepts",
                indicator_code="1.1.1",
                indicator_description="Apply specific concepts to a case",
            )
            pso_indicator.course_outcomes.add(outcome)

        ese_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ESE",
            sub_tool="University Exam",
        )
        UniversityExam.objects.create(
            tool=ese_tool,
            co=self.course_outcome,
            marks=100,
        )
        UniversityExamMarks.objects.create(
            tool=ese_tool,
            student=self.student,
            marks=74,
        )

        response = self.client.get(
            reverse("co_po_pso_attainment", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            f'href="{reverse("co_po_pso_attainment", args=[self.course.id])}?download=docx"',
        )
        self.assertNotContains(response, "Download Word")
        course_dashboard_response = self.client.get(
            reverse("view_course", args=[self.course.id]),
            secure=True,
        )
        self.assertEqual(course_dashboard_response.status_code, 200)
        self.assertContains(
            course_dashboard_response,
            reverse("course_report_preview", args=[self.course.id]),
        )
        self.assertContains(
            course_dashboard_response,
            reverse("co_po_pso_attainment", args=[self.course.id]),
        )
        self.assertContains(course_dashboard_response, "View PO-PSO attainment")
        self.assertNotContains(
            course_dashboard_response,
            f'href="{reverse("co_po_pso_attainment", args=[self.course.id])}?download=docx"',
        )
        self.assertNotContains(course_dashboard_response, "Download Word Report")
        preview_response = self.client.get(
            reverse("course_report_preview", args=[self.course.id]),
            secure=True,
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, "Complete Course Report")
        self.assertContains(preview_response, "width:5.8in;max-width:100%")
        self.assertContains(preview_response, "padding: 8px 6px")
        third_page_html = "".join(
            preview_response.context["report_pages"][2]["content_html"]
        )
        self.assertIn(
            '<h1 class="document-heading" style="text-align:center">'
            '<span style="font-size:12pt;font-family:\'Times New Roman\';color:#CC0000">'
            '<strong>COURSE OUTCOMES (COs)</strong></span></h1>',
            third_page_html,
        )
        self.assertIn("Course Information", third_page_html)
        self.assertIn("Cognitive Level", third_page_html)
        self.assertIn("colspan=\"4\"", third_page_html)
        self.assertIn("background-color:#F4C7A8", third_page_html)
        self.assertIn("L2: Understand", third_page_html)
        fourth_page_html = "".join(
            preview_response.context["report_pages"][3]["content_html"]
        )
        self.assertIn("LIST OF ASSESSMENT TOOLS", fourth_page_html)
        self.assertIn(
            "Assessment Method and Instruments (Direct and Indirect)",
            fourth_page_html,
        )
        self.assertIn("Mode of Assessment", fourth_page_html)
        self.assertIn("Mapping With PO &amp; PSO", fourth_page_html)
        self.assertIn("rowspan=", fourth_page_html)
        fifth_page_html = "".join(
            preview_response.context["report_pages"][4]["content_html"]
        )
        self.assertIn("Assessment Pattern", fifth_page_html)
        self.assertIn("CO-wise Marks Distribution", fifth_page_html)
        self.assertIn("Quality of Question Paper &amp; Assignment", fifth_page_html)
        self.assertIn("Course outcome", fifth_page_html)
        self.assertIn("Cognitive level", fifth_page_html)
        self.assertIn("CIE total", fifth_page_html)
        self.assertIn("Total", fifth_page_html)
        self.assertIn("background-color:#D9EAF7", fifth_page_html)
        self.assertIn(
            "min-height:",
            preview_response.context["report_pages"][4]["page_style"],
        )
        self.assertGreater(
            float(
                preview_response.context["report_pages"][4]["page_style"]
                .split("min-height:")[1]
                .removesuffix("in")
            ),
            11.69,
        )
        pattern_data = preview_response.context["assessment_pattern_data"]
        first_co_key, first_co_values = next(iter(pattern_data["co_table"].items()))
        self.assertIn(first_co_key, fifth_page_html)
        self.assertIn(str(first_co_values["TOTAL"]), fifth_page_html)
        first_bloom_key, first_bloom_values = next(iter(pattern_data["bl_table"].items()))
        self.assertIn(first_bloom_key, fifth_page_html)
        self.assertIn(str(first_bloom_values["TOTAL"]), fifth_page_html)
        self.assertGreaterEqual(fifth_page_html.count("data:image/png;base64"), 2)
        sixth_page_html = "".join(
            preview_response.context["report_pages"][5]["content_html"]
        )
        self.assertIn("Attainment Weightage and Target", sixth_page_html)
        self.assertIn("DIRECT ATTAINMENT", sixth_page_html)
        self.assertIn("INDIRECT ATTAINMENT", sixth_page_html)
        self.assertIn("COURSE EXIT SURVEY", sixth_page_html)
        self.assertIn("CO wise Target (50-70%)", sixth_page_html)
        self.assertIn("Course Outcome Statements", sixth_page_html)
        self.assertIn("Cognitive Level", sixth_page_html)
        self.assertIn("Weightage (%)", sixth_page_html)
        self.assertIn("CO-1", sixth_page_html)
        seventh_page_html = "".join(
            preview_response.context["report_pages"][6]["content_html"]
        )
        self.assertIn("CO Attainment Sheet", seventh_page_html)
        self.assertIn("CIE Class Averages", seventh_page_html)
        self.assertIn("CONTINUOUS INTERNAL EVALUATION", seventh_page_html)
        self.assertIn("COURSE OUTCOMES", seventh_page_html)
        self.assertIn("CO1", seventh_page_html)
        eighth_page_html = "".join(
            preview_response.context["report_pages"][7]["content_html"]
        )
        self.assertIn("Direct CO Attainment", eighth_page_html)
        self.assertIn("CIE CLASS AVERAGE", eighth_page_html)
        self.assertIn("ESE CLASS AVERAGE", eighth_page_html)
        self.assertIn("DIRECT CO ATTAINMENT", eighth_page_html)
        self.assertIn("ROUNDED", eighth_page_html)
        self.assertIn("Direct CO Attainment =", eighth_page_html)
        ninth_page_html = "".join(
            preview_response.context["report_pages"][8]["content_html"]
        )
        self.assertIn("Course Exit Survey", ninth_page_html)
        self.assertIn("COURSE OUTCOME QUESTION", ninth_page_html)
        self.assertIn("STRONGLY AGREE", ninth_page_html)
        self.assertIn("ATTAINMENT", ninth_page_html)
        self.assertIn("CO1", ninth_page_html)
        tenth_page_html = "".join(
            preview_response.context["report_pages"][9]["content_html"]
        )
        self.assertIn("Total CO Attainment", tenth_page_html)
        self.assertIn("DIRECT CO ATTAINMENT", tenth_page_html)
        self.assertIn("INDIRECT CO ATTAINMENT", tenth_page_html)
        self.assertIn("TOTAL CO ATTAINMENT %", tenth_page_html)
        self.assertIn("ROUNDED", tenth_page_html)
        self.assertIn("Total Attainment of CO =", tenth_page_html)
        eleventh_page_html = next(
            "".join(page["content_html"])
            for page in preview_response.context["report_pages"]
            if "CO Attainment GAP" in "".join(page["content_html"])
        )
        self.assertIn("CO Attainment GAP", eleventh_page_html)
        self.assertIn("CO Attainment Gap (Target-", eleventh_page_html)
        self.assertIn("Closure of QUALITY Loop", eleventh_page_html)
        self.assertIn("Action Proposed to Bridge Gap", eleventh_page_html)
        self.assertIn("Modifications of Target", eleventh_page_html)
        self.assertContains(preview_response, "COURSE OUTCOMES (COs)")
        self.assertContains(preview_response, "CO Attainment GAP")
        self.assertContains(preview_response, "Closure of QUALITY Loop")
        self.assertContains(preview_response, "CO-PO-PSO ATTAINMENT")
        self.assertContains(preview_response, "Mapping Grade")
        self.assertContains(preview_response, "Map%")
        self.assertContains(preview_response, "Course Articulation Matrix")
        self.assertContains(preview_response, "CO-PO-PSO Mapping")
        self.assertContains(preview_response, "CO-PO-PSO Attainment")
        self.assertContains(preview_response, "CO-PO Mapping Level")
        self.assertEqual(len(preview_response.context["report_pages"]), 14)
        self.assertTrue(
            any(
                "data:image/png;base64" in report_page["content_html"]
                for report_page in preview_response.context["report_pages"]
            )
        )
        report_header_html = "".join(
            report_page["header_html"]
            for report_page in preview_response.context["report_pages"]
        )
        self.assertIn("font-size:19pt", report_header_html)
        self.assertIn("width:0.95in", report_header_html)
        self.assertIn("table-layout:fixed", report_header_html)
        self.assertContains(
            preview_response,
            f'href="{reverse("course_report_preview", args=[self.course.id])}?download=docx"',
        )
        self.assertContains(preview_response, "Download Word")
        rows = response.context["po_pso_attainment_rows"]
        po_row = next(row for row in rows if row["outcome"] == self.po.po_number)
        pso_row = next(row for row in rows if row["outcome"] == self.pso.pso_number)
        unmapped_po_row = next(row for row in rows if row["outcome"] == unmapped_po.po_number)
        self.assertEqual(po_row["mapped_cos"], "CO1")
        self.assertEqual(po_row["mapping_level"], 3)
        self.assertEqual(po_row["attainment"], 40.0)
        self.assertEqual(po_row["rounded_attainment"], 40)
        self.assertEqual(po_row["attainment_level"], 2)
        self.assertEqual(pso_row["rounded_attainment"], 40)
        self.assertEqual(unmapped_po_row["mapping_level"], "")
        self.assertEqual(unmapped_po_row["attainment"], "")
        self.assertEqual(unmapped_po_row["max_level"], 3)
        self.assertContains(response, "CO-PO-PSO Attainment")
        self.assertContains(response, "CO-PO Mapping Level")
        self.assertEqual(response.context["attainment_thresholds"].level_2_min, 34)
        self.assertEqual(response.context["attainment_thresholds"].level_3_min, 67)
        self.assertContains(response, "Edit levels")
        self.assertNotContains(response, 'name="level_2_min"')

        edit_response = self.client.get(
            reverse("co_po_pso_attainment", args=[self.course.id]),
            {"edit": "1"},
            secure=True,
        )
        self.assertContains(edit_response, 'name="level_2_min"')
        self.assertContains(edit_response, 'value="34"')
        self.assertContains(edit_response, 'name="level_3_min"')
        self.assertContains(edit_response, 'value="67"')

        save_response = self.client.post(
            reverse("co_po_pso_attainment", args=[self.course.id]),
            {"level_2_min": "30", "level_3_min": "40"},
            secure=True,
        )
        self.assertEqual(save_response.status_code, 302)

        saved_response = self.client.get(
            reverse("co_po_pso_attainment", args=[self.course.id]),
            secure=True,
        )
        saved_rows = saved_response.context["po_pso_attainment_rows"]
        saved_po_row = next(row for row in saved_rows if row["outcome"] == self.po.po_number)
        self.assertEqual(saved_response.context["attainment_thresholds"].level_2_min, 30)
        self.assertEqual(saved_response.context["attainment_thresholds"].level_3_min, 40)
        self.assertEqual(saved_po_row["attainment_level"], 3)
        self.assertContains(saved_response, "≥30 and &lt;40")

        self.department.report_department_name = "Department of Mechanical Engineering"
        self.department.report_accreditation = "NBA Accredited"
        self.department.report_email = "mech@example.edu"
        self.department.report_hod_name = "Dr. Department HOD"
        self.department.report_hod_qualification = "M.E., Ph.D. (Mechanical Engineering)"
        self.department.save()
        self.academic_class.academic_year = "2025-26"
        self.academic_class.save()
        CollegeReportSettings.objects.update_or_create(
            pk=1,
            defaults={"website": "https://www.sknscoe.ac.in"},
        )

        download_response = self.client.get(
            reverse("course_report_preview", args=[self.course.id]),
            {"download": "docx"},
            secure=True,
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(
            download_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertIn("attachment; filename=", download_response["Content-Disposition"])

        from docx import Document

        report = Document(BytesIO(download_response.content))
        self.assertEqual(len(report.sections), 13)
        self.assertFalse(
            any(paragraph.text == "INDEX" for paragraph in report.paragraphs)
        )
        for section_index, section in enumerate(report.sections):
            if section.page_width > section.page_height:
                self.assertGreater(section.page_width, section.page_height)
                if section_index == 10:
                    self.assertAlmostEqual(section.page_width / 914400, 16.54, places=2)
                    self.assertAlmostEqual(section.page_height / 914400, 11.69, places=2)
                elif section_index == 12:
                    self.assertAlmostEqual(section.page_width / 914400, 16.54, places=2)
                    self.assertAlmostEqual(section.page_height / 914400, 11.69, places=2)
                else:
                    self.assertAlmostEqual(section.page_width / 914400, 11.69, places=2)
                    self.assertAlmostEqual(section.page_height / 914400, 8.27, places=2)
                continue
            self.assertLess(section.page_width, section.page_height)
            self.assertAlmostEqual(section.page_width / 914400, 8.27, places=2)
            if section_index == 3:
                self.assertGreater(section.page_height / 914400, 11.69)
                self.assertLessEqual(section.page_height / 914400, 21.9)
            else:
                self.assertAlmostEqual(section.page_height / 914400, 11.69, places=2)
        self.assertGreaterEqual(len(report.inline_shapes), 3)
        report_header = report.sections[0].header
        header_text = "\n".join(paragraph.text for paragraph in report_header.paragraphs)
        header_text += "\n" + "\n".join(
            paragraph.text
            for table in report_header.tables
            for row in table.rows
            for cell in row.cells
            for paragraph in cell.paragraphs
        )
        self.assertIn("SKN SINHGAD COLLEGE OF ENGINEERING", header_text)
        self.assertIn("Department of Mechanical Engineering", header_text)
        self.assertIn("NBA Accredited", header_text)
        self.assertIn("mech@example.edu", header_text)
        self.assertIn("https://www.sknscoe.ac.in", header_text)
        self.assertIn("Dr. K. J. Karande", header_text)
        self.assertIn("Dr. Department HOD", header_text)
        header_logo = report_header._element.xpath(".//wp:inline")
        self.assertEqual(len(header_logo), 1)
        self.assertAlmostEqual(header_logo[0].extent.cx / 914400, 0.9, places=2)
        college_name = next(
            paragraph
            for paragraph in report_header.tables[0].cell(0, 1).paragraphs
            if paragraph.text == "SKN SINHGAD COLLEGE OF ENGINEERING"
        )
        self.assertEqual(college_name.runs[0].font.size.pt, 19)
        self.assertTrue(
            all(
                paragraph.alignment == 1
                for table in report_header.tables[1:]
                for row in table.rows
                for cell in row.cells
                for paragraph in cell.paragraphs
            )
        )
        self.assertEqual(len(report_header.paragraphs[1]._p.xpath("./w:pPr/w:pBdr/w:bottom")), 1)
        self.assertAlmostEqual(report.sections[0].top_margin / 914400, 1.85, places=2)
        cover_text = "\n".join(paragraph.text for paragraph in report.tables[0].cell(0, 0).paragraphs)
        self.assertIn("CO-PO-PSO ATTAINMENT", cover_text)
        self.assertIn(f"SUBJECT :- {self.course.course_name}", cover_text)
        self.assertIn(f"ACADEMIC YEAR :- {self.course.academic_class.academic_year}", cover_text)
        self.assertIn("ACADEMIC YEAR :- 2025-26", cover_text)
        information_title = next(
            paragraph
            for paragraph in report.paragraphs
            if paragraph.text == "CO-PO-PSO ATTAINMENT"
        )
        self.assertEqual(information_title.alignment, 1)
        information_table = report.tables[1]
        self.assertEqual(len(information_table.rows), 5)
        self.assertEqual(len(information_table.columns), 2)
        self.assertAlmostEqual(
            sum(column.width for column in information_table.columns) / 914400,
            5.8,
            places=2,
        )
        self.assertTrue(
            all(row.height / 914400 >= 0.55 for row in information_table.rows)
        )
        expected_information = (
            ("Name of Department", "Department of Mechanical Engineering"),
            ("Title of Course", self.course.course_name),
            ("Course Code", self.course.course_code),
            ("Academic year", "2025-26"),
            ("Name of Subject Teacher", "Not configured in course data"),
        )
        for row, expected in zip(information_table.rows, expected_information):
            self.assertEqual(tuple(cell.text for cell in row.cells), expected)
        course_information_table = report.tables[2]
        self.assertEqual(
            course_information_table.cell(3, 0).text,
            "Course Information",
        )
        self.assertEqual(course_information_table.cell(4, 0).text, "Course Name")
        self.assertEqual(course_information_table.cell(4, 1).text, self.course.course_name)
        course_outcomes_table = report.tables[3]
        self.assertEqual(
            [cell.text for cell in course_outcomes_table.rows[0].cells],
            ["CO", "Course Outcome Statements", "Cognitive Level"],
        )
        self.assertEqual(
            [cell.text for cell in course_outcomes_table.rows[1].cells],
            ["CS101 CO-1", "Apply programming concepts", "L2: Understand"],
        )
        assessment_tools_table = report.tables[4]
        self.assertEqual(len(assessment_tools_table.columns), 7)
        self.assertEqual(
            assessment_tools_table.cell(0, 0).text,
            "Assessment Method and Instruments (Direct and Indirect)",
        )
        self.assertEqual(
            [cell.text for cell in assessment_tools_table.rows[1].cells],
            [
                "Mode of Assessment",
                "Assessment Component",
                "Assessment Tool",
                "Evaluation of CO",
                "Mapping With PO & PSO",
                "Frequency of Assessment",
                "Marks / Weightage",
            ],
        )
        assessment_pattern_table = report.tables[5]
        self.assertEqual(
            assessment_pattern_table.cell(0, 0).text,
            "Course outcome",
        )
        self.assertEqual(
            assessment_pattern_table.cell(0, len(assessment_pattern_table.columns) - 1).text,
            "CIE total",
        )
        self.assertEqual(
            assessment_pattern_table.cell(2, 0).text,
            first_co_key,
        )
        self.assertEqual(
            assessment_pattern_table.cell(2, len(assessment_pattern_table.columns) - 1).text,
            str(first_co_values["TOTAL"]),
        )
        header_fill = assessment_pattern_table.cell(0, 0)._tc.tcPr.find(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd"
        )
        self.assertEqual(
            header_fill.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fill"
            ),
            "D9EAF7",
        )
        for table in report.tables[5:7]:
            self.assertTrue(
                all(
                    paragraph.alignment == 1
                    for row in table.rows
                    for cell in row.cells
                    for paragraph in cell.paragraphs
                )
            )
        centered_chart_paragraphs = [
            paragraph
            for paragraph in report.paragraphs
            if paragraph._p.xpath(".//wp:inline")
        ]
        self.assertGreaterEqual(len(centered_chart_paragraphs), 2)
        self.assertTrue(
            all(
                paragraph.alignment == 1
                for paragraph in centered_chart_paragraphs[:2]
            )
        )
        assessment_headings = {
            paragraph.text: paragraph
            for paragraph in report.paragraphs
            if paragraph.text
            in {
                "Assessment Pattern",
                "CO-wise Marks Distribution",
                "Quality of Question Paper & Assignment",
            }
        }
        self.assertEqual(len(assessment_headings), 3)
        self.assertTrue(
            all(paragraph.alignment == 1 for paragraph in assessment_headings.values())
        )
        self.assertGreaterEqual(len(report.tables[6].columns), 2)
        self.assertEqual(
            report.tables[6].cell(0, 0).text,
            "Cognitive level",
        )
        self.assertEqual(
            report.tables[6].cell(2, 0).text,
            first_bloom_key,
        )
        self.assertEqual(
            report.tables[6].cell(2, len(report.tables[6].columns) - 1).text,
            str(first_bloom_values["TOTAL"]),
        )
        setup_table = report.tables[8]
        self.assertEqual(setup_table.cell(1, 0).text, "A] DIRECT ATTAINMENT")
        self.assertEqual(setup_table.cell(1, 1).text, "A] DIRECT ATTAINMENT")
        self.assertEqual(setup_table.cell(1, 2).text, "B] INDIRECT ATTAINMENT")
        self.assertEqual(setup_table.cell(2, 0).text, "90%")
        self.assertEqual(setup_table.cell(2, 2).text, "10%")
        target_table = report.tables[10]
        self.assertEqual(
            [cell.text for cell in target_table.rows[0].cells],
            [
                "CO Number",
                "Course Outcome Statements",
                "Cognitive Level",
                "Weightage (%)",
            ],
        )
        report_text = "\n".join(paragraph.text for paragraph in report.paragraphs)
        report_text += "\n" + "\n".join(
            cell.text
            for table in report.tables
            for row in table.rows
            for cell in row.cells
        )
        for section_title in (
            "COURSE OUTCOMES (COs)",
            "Assessment Pattern",
            "Attainment Weightage and Target",
            "CO Attainment Sheet",
            "Direct CO Attainment",
            "Indirect Attainment",
            "Total CO Attainment",
            "CO Attainment GAP",
            "Closure of QUALITY Loop",
            "Mapping Grade",
            "Course Articulation Matrix",
            "CO-PO-PSO Attainment",
            "CO-PO Mapping Level",
        ):
            self.assertIn(section_title, report_text)
        for section_title in (
            "Institute and Department Profile",
            "Program Educational Objectives",
            "Syllabus, Experiments and Textbooks",
            "Direct Attainment of PO-PSOs",
        ):
            self.assertNotIn(section_title, report_text)
        self.assertIn("Not configured in course data", report_text)

    def test_mock_oral_is_available_as_a_main_tool_with_its_own_subtool(self):
        response = self.client.post(
            reverse("assessment_tool_page", args=[self.course.id]),
            {"main_tool": "Mock Oral", "sub_tool": "Mock Oral"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        tool = AssessmentTool.objects.get(
            course=self.course,
            main_tool="Mock Oral",
            sub_tool="Mock Oral",
        )

        response = self.client.get(
            reverse("assessment_tool_page", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mock Oral")
        self.assertContains(response, reverse("university_exam_page", args=[tool.id]))
        self.assertContains(response, reverse("university_exam_marks", args=[tool.id]))

    def test_mock_oral_marks_contribute_to_cie_and_not_ese(self):
        course = Course.objects.create(
            academic_class=self.academic_class,
            course_code="CS102",
            course_name="Data Structures",
        )
        first_co = CourseOutcome.objects.create(
            course=course,
            co_number=1,
            description="Explain data structures",
        )
        second_co = CourseOutcome.objects.create(
            course=course,
            co_number=2,
            description="Apply data structures",
        )
        cie_tool = AssessmentTool.objects.create(
            course=course,
            main_tool="ISE Assignment",
            sub_tool="Assignment",
        )
        mock_oral = AssessmentTool.objects.create(
            course=course,
            main_tool="Mock Oral",
            sub_tool="Mock Oral",
        )
        response = self.client.post(
            reverse("university_exam_page", args=[mock_oral.id]),
            {"total_marks": "100"},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(
                UniversityExam.objects.filter(tool=mock_oral)
                .order_by("co__co_number")
                .values_list("marks", flat=True)
            ),
            [50, 50],
        )

        marks_url = reverse("university_exam_marks", args=[mock_oral.id])
        self.client.post(marks_url, {"edit_mode": "1"}, secure=True)
        response = self.client.post(
            marks_url,
            {"save_marks": "1", f"marks_{self.student.id}": "80"},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)

        ese_tool = AssessmentTool.objects.create(
            course=course,
            main_tool="ESE",
            sub_tool="University Exam",
        )
        UniversityExam.objects.create(tool=ese_tool, co=first_co, marks=100)
        UniversityExamMarks.objects.create(
            tool=ese_tool,
            student=self.student,
            marks=50,
        )

        response = self.client.get(
            reverse("co_attainment_sheet", args=[course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [column["sub"] for column in response.context["cie_columns"]],
            ["Assignment", "Mock Oral"],
        )
        self.assertContains(response, "Continuous Internal Evaluation")
        self.assertContains(response, "CIE Class Average")
        self.assertContains(response, "Final ESE Class Ave %")
        self.assertEqual(response.context["cie_percentage_table"], {
            "CO1": 80.0,
            "CO2": 80.0,
        })
        self.assertEqual(response.context["ese_percentage_table"], {
            "CO1": 50.0,
            "CO2": 50.0,
        })

        response = self.client.get(
            reverse("tool_marks_co_summary", args=[mock_oral.id]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["columns"][0]["max_marks"], 100)
        self.assertEqual(response.context["students"][0]["marks"], [80.0])

    def test_ese_attainment_uses_main_exam_average_not_co_distributions(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        ese_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ESE",
            sub_tool="University Exam",
        )
        UniversityExam.objects.create(
            tool=ese_tool,
            co=self.course_outcome,
            marks=100,
        )
        second_student = Student.objects.create(
            roll_no="2",
            name="Second Student",
            academic_class=self.academic_class,
            department=self.department,
        )
        UniversityExamMarks.objects.create(
            tool=ese_tool,
            student=self.student,
            marks=50,
        )
        UniversityExamMarks.objects.create(
            tool=ese_tool,
            student=second_student,
            marks=70,
        )
        AttainmentWeightage.objects.create(
            course=self.course,
            direct_attainment=90,
            indirect_attainment=10,
            cie_weightage=40,
            ese_weightage=60,
            survey_weightage=10,
        )

        response = self.client.get(
            reverse("co_attainment_sheet", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["ese_percentage_table"],
            {"CO1": 60.0, "CO2": 60.0},
        )

    def test_ese_class_average_is_average_of_ese_and_poe_percentages(self):
        ese_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ESE",
            sub_tool="University Exam",
        )
        poe_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ESE",
            sub_tool="POE",
        )
        UniversityExam.objects.create(
            tool=ese_tool,
            co=self.course_outcome,
            marks=100,
        )
        UniversityExam.objects.create(
            tool=poe_tool,
            co=self.course_outcome,
            marks=50,
        )
        UniversityExamMarks.objects.create(
            tool=ese_tool,
            student=self.student,
            marks=50,
        )
        UniversityExamMarks.objects.create(
            tool=poe_tool,
            student=self.student,
            marks=45,
        )

        response = self.client.get(
            reverse("co_attainment_sheet", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["ese_percentage_table"]["CO1"],
            70.0,
        )

    def test_attainment_class_average_shows_percentage_of_tool_max_marks(self):
        tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ISE Assignment",
            sub_tool="Tutorial 1",
        )
        question = AssignmentTool.objects.create(
            tool=tool,
            question_no="Q1",
            co=self.course_outcome,
            marks=20,
        )
        second_student = Student.objects.create(
            roll_no="2",
            name="Second Student",
            academic_class=self.academic_class,
            department=self.department,
        )
        third_student = Student.objects.create(
            roll_no="3",
            name="Third Student",
            academic_class=self.academic_class,
            department=self.department,
        )
        for student, marks in (
            (self.student, 13),
            (second_student, 13),
            (third_student, 14),
        ):
            AssignmentTutorialMarks.objects.create(
                tool=tool,
                student=student,
                question=question,
                marks=marks,
            )

        response = self.client.get(
            reverse("co_attainment_sheet", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        tool_key = f"tool_{tool.id}"
        self.assertEqual(response.context["co_avg_table"]["CO1"][tool_key], 66.65)
        self.assertEqual(response.context["cie_percentage_table"]["CO1"], 66.65)
        self.assertContains(response, "Class Avg. %")
        self.assertContains(response, ">66.65</td>")
        self.assertNotContains(response, "Marks<br>Contribution")

    def test_attainment_average_table_shows_assignment_groups_and_experiments(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        assignment_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ISE Assignment",
            sub_tool="Assignment",
        )
        first_assignment_question = AssignmentTool.objects.create(
            tool=assignment_tool,
            question_no="A1.1",
            co=self.course_outcome,
            marks=10,
        )
        second_assignment_question = AssignmentTool.objects.create(
            tool=assignment_tool,
            question_no="A1.2",
            co=self.course_outcome,
            marks=10,
        )
        AssignmentTool.objects.create(
            tool=assignment_tool,
            question_no="A2.1",
            co=second_co,
            marks=10,
        )
        AssignmentTutorialMarks.objects.create(
            tool=assignment_tool,
            student=self.student,
            question=first_assignment_question,
            marks=8,
        )
        AssignmentTutorialMarks.objects.create(
            tool=assignment_tool,
            student=self.student,
            question=second_assignment_question,
            marks=6,
        )

        experiment_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ICA",
            sub_tool="Experiment",
        )
        first_experiment = IcaAssignmentExp.objects.create(
            tool=experiment_tool,
            sub_tool_no=1,
            co=self.course_outcome,
            bl="BL1",
            marks=10,
        )
        second_experiment = IcaAssignmentExp.objects.create(
            tool=experiment_tool,
            sub_tool_no=2,
            co=second_co,
            bl="BL2",
            marks=10,
        )
        IcaStudentMarks.objects.create(
            tool=experiment_tool,
            student=self.student,
            subtool=first_experiment,
            marks=8,
        )
        IcaStudentMarks.objects.create(
            tool=experiment_tool,
            student=self.student,
            subtool=second_experiment,
            marks=6,
        )

        response = self.client.get(
            reverse("co_attainment_sheet", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        display_columns = response.context["cie_display_columns"]
        assignment_columns = [
            column for column in display_columns
            if column["tool"] == assignment_tool
        ]
        experiment_columns = [
            column for column in display_columns
            if column["tool"] == experiment_tool
        ]
        self.assertEqual(
            [column["sub"] for column in assignment_columns],
            ["ISE-I", "ISE-II"],
        )
        self.assertEqual(
            [column["sub"] for column in experiment_columns],
            ["Experiment 1", "Experiment 2"],
        )
        display_row = response.context["display_avg_table"]["CO1"]
        self.assertEqual(display_row[assignment_columns[0]["key"]], 70.0)
        self.assertEqual(display_row[experiment_columns[0]["key"]], 80.0)
        self.assertEqual(display_row[experiment_columns[1]["key"]], "")
        self.assertEqual(response.context["cie_percentage_table"]["CO1"], 75.0)

    def test_university_exam_summary_keeps_student_marks_as_one_total(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ESE",
            sub_tool="University Exam",
        )
        UniversityExam.objects.create(
            tool=tool,
            co=self.course_outcome,
            marks=30,
        )
        UniversityExam.objects.create(
            tool=tool,
            co=second_co,
            marks=40,
        )
        UniversityExamMarks.objects.create(
            tool=tool,
            student=self.student,
            marks=41,
        )

        response = self.client.get(
            reverse("tool_marks_co_summary", args=[tool.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["columns"]), 1)
        self.assertEqual(response.context["columns"][0]["label"], "Total")
        self.assertEqual(response.context["columns"][0]["max_marks"], 70)
        self.assertEqual(response.context["students"][0]["marks"], [41])
        self.assertEqual(response.context["students"][0]["total_obtained"], 41)
        self.assertEqual(
            [row["label"] for row in response.context["summary_rows"]],
            ["No. of Students Attempted", "Average", "Attainment %"],
        )
        self.assertContains(response, "41.0 / 70.0")
        self.assertNotContains(response, "CO1")
        self.assertNotContains(response, "CO2")

    def test_ica_summary_labels_include_experiment_numbers(self):
        tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ICA",
            sub_tool="Experiment",
        )
        IcaAssignmentExp.objects.create(
            tool=tool,
            sub_tool_no=1,
            co=self.course_outcome,
            bl="BL1",
            marks=10,
        )
        IcaAssignmentExp.objects.create(
            tool=tool,
            sub_tool_no=2,
            co=self.course_outcome,
            bl="BL2",
            marks=15,
        )

        response = self.client.get(
            reverse("tool_marks_co_summary", args=[tool.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [column["label"] for column in response.context["columns"]],
            ["Experiment 1 - CO1", "Experiment 2 - CO1"],
        )
        self.assertContains(response, "Experiment 1 - CO1")
        self.assertContains(response, "Experiment 2 - CO1")

    def test_assignment_summary_labels_include_assignment_numbers(self):
        tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ISE Assignment",
            sub_tool="Assignment",
        )
        AssignmentTool.objects.create(
            tool=tool,
            question_no="A1.1",
            co=self.course_outcome,
            marks=10,
        )
        AssignmentTool.objects.create(
            tool=tool,
            question_no="A2.1",
            co=self.course_outcome,
            marks=15,
        )

        response = self.client.get(
            reverse("tool_marks_co_summary", args=[tool.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [column["label"] for column in response.context["columns"]],
            ["Assignment 1 - CO1", "Assignment 2 - CO1"],
        )
        self.assertContains(response, "Assignment 1 - CO1")
        self.assertContains(response, "Assignment 2 - CO1")

    def test_attainment_weights_save_without_redundant_survey_field(self):
        response = self.client.post(
            reverse("co_target_page", args=[self.course.id]),
            {
                "direct_attainment": "90",
                "indirect_attainment": "10",
                "cie_weightage": "40",
                "ese_weightage": "60",
                "survey_weightage": "",
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("co_target_page", args=[self.course.id]),
        )
        weightage = AttainmentWeightage.objects.get(course=self.course)
        self.assertEqual(weightage.direct_attainment, 90)
        self.assertEqual(weightage.indirect_attainment, 10)
        self.assertEqual(weightage.cie_weightage, 40)
        self.assertEqual(weightage.ese_weightage, 60)
        self.assertEqual(weightage.survey_weightage, 10)

    def test_attainment_weight_save_rejects_weights_that_do_not_total_100(self):
        response = self.client.post(
            reverse("co_target_page", args=[self.course.id]),
            {
                "direct_attainment": "90",
                "indirect_attainment": "10",
                "cie_weightage": "40",
                "ese_weightage": "50",
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("co_target_page", args=[self.course.id]),
        )
        self.assertEqual(
            AttainmentWeightage.objects.get(course=self.course).cie_weightage,
            40,
        )
        self.assertEqual(len(list(response.wsgi_request._messages)), 1)

    def test_performance_indicators_calculate_po_and_pso_mapping_grades(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        third_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=3,
            description="Evaluate programming concepts",
        )
        po_prefix = f"po_{self.po.id}"
        pso_prefix = f"pso_{self.pso.id}"
        post_data = {
            f"{po_prefix}_competency_count": "2",
            f"{po_prefix}_comp_1_description": "Apply concepts",
            f"{po_prefix}_comp_1_indicator_count": "7",
            f"{po_prefix}_comp_2_description": "Evaluate concepts",
            f"{po_prefix}_comp_2_indicator_count": "3",
            f"{pso_prefix}_competency_count": "1",
            f"{pso_prefix}_comp_1_description": "Apply specific concepts",
            f"{pso_prefix}_comp_1_indicator_count": "2",
        }

        for index in range(1, 11):
            competency_index = 1 if index <= 7 else 2
            indicator_index = index if index <= 7 else index - 7
            pi_prefix = (
                f"{po_prefix}_comp_{competency_index}_pi_{indicator_index}"
            )
            post_data[f"{pi_prefix}_description"] = f"Indicator {index}"
            if index <= 7:
                post_data[f"{pi_prefix}_co_{self.course_outcome.id}"] = "1"
            if index <= 4:
                post_data[f"{pi_prefix}_co_{second_co.id}"] = "1"
            if index == 1:
                post_data[f"{pi_prefix}_co_{third_co.id}"] = "1"

        for index in range(1, 3):
            pi_prefix = f"{pso_prefix}_comp_1_pi_{index}"
            post_data[f"{pi_prefix}_description"] = f"Specific indicator {index}"
            post_data[f"{pi_prefix}_co_{self.course_outcome.id}"] = "1"

        response = self.client.post(
            reverse("course_performance_indicators", args=[self.course.id]),
            post_data,
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse("course_performance_indicators", args=[self.course.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(CoursePerformanceIndicator.objects.count(), 12)
        self.assertEqual(
            list(
                CoursePerformanceIndicator.objects.filter(po=self.po)
                .order_by("competency_level", "indicator_code")
                .values_list("competency_level", "indicator_code")[:2]
            ),
            [("1.1", "1.1.1"), ("1.1", "1.1.2")],
        )
        self.assertTrue(
            CoursePerformanceIndicator.objects.filter(
                pso=self.pso,
                competency_level="1.1",
                indicator_code="1.1.2",
            ).exists()
        )
        self.assertEqual(
            COPOMapping.objects.get(co=self.course_outcome, po=self.po).level,
            3,
        )
        self.assertEqual(
            COPOMapping.objects.get(co=second_co, po=self.po).level,
            2,
        )
        self.assertEqual(
            COPOMapping.objects.get(co=third_co, po=self.po).level,
            1,
        )
        self.assertEqual(
            COPSOMapping.objects.get(co=self.course_outcome, pso=self.pso).level,
            3,
        )

        response = self.client.get(
            reverse("course_mapping_grade", args=[self.course.id]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        po_entry, pso_entry = response.context["grade_rows"][0]["entries"]
        self.assertEqual((po_entry["tpi"], po_entry["mpi"], po_entry["percentage"], po_entry["grade"]),
                         (10, 7, 70.0, 3))
        self.assertEqual((pso_entry["tpi"], pso_entry["mpi"], pso_entry["percentage"], pso_entry["grade"]),
                         (2, 2, 100.0, 3))
        grade_by_co = {
            row["co"].co_number: row["entries"][0]["grade"]
            for row in response.context["grade_rows"]
        }
        self.assertEqual(grade_by_co, {1: 3, 2: 2, 3: 1})

        response = self.client.get(
            reverse("course_performance_indicators", args=[self.course.id]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mapping Performance Indicators"        )
        self.assertContains(response, "No. of Competencies")
        self.assertContains(response, "POs / PSOs")
        self.assertContains(response, 'id="edit-mapping">Edit</button>')
        self.assertContains(response, 'id="save-mapping" hidden>Save</button>')
        self.assertEqual(len(response.context["outcome_sections"]), 2)
        self.assertEqual(
            len(response.context["outcome_sections"][0]["competencies"]),
            2,
        )

        response = self.client.get(
            reverse("co_po_pso_matrix", args=[self.course.id]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse("view_course", args=[self.course.id]),
            secure=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_mapping_grade_without_indicators_clears_old_manual_levels(self):
        response = self.client.get(
            reverse("course_mapping_grade", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["grade_rows"][0]["entries"][0]["tpi"], 0)
        self.assertFalse(COPOMapping.objects.filter(co=self.course_outcome).exists())
        self.assertFalse(COPSOMapping.objects.filter(co=self.course_outcome).exists())

    def test_mapping_page_orders_po_and_pso_numbers_numerically(self):
        po_ten = ProgramOutcome.objects.create(
            department=self.department,
            po_number="PO10",
            description="Outcome ten",
        )
        po_two = ProgramOutcome.objects.create(
            department=self.department,
            po_number="PO2",
            description="Outcome two",
        )
        pso_ten = ProgramSpecificOutcome.objects.create(
            department=self.department,
            pso_number="PSO10",
            description="Specific outcome ten",
        )
        pso_two = ProgramSpecificOutcome.objects.create(
            department=self.department,
            pso_number="PSO2",
            description="Specific outcome two",
        )

        response = self.client.get(
            reverse("course_performance_indicators", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [section["label"] for section in response.context["outcome_sections"]],
            ["PO1", "PO2", "PO10", "PSO1", "PSO2", "PSO10"],
        )

    def test_mapping_page_shows_full_course_outcome_statement_in_header(self):
        description = (
            "Select appropriate materials and processing methods for "
            "advanced engineering applications without truncating the statement"
        )
        self.course_outcome.description = description
        self.course_outcome.save(update_fields=["description"])

        response = self.client.get(
            reverse("course_performance_indicators", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, description)

    def test_assignment_marks_page_groups_headers_by_assignment_co_and_max_marks(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        self.question.question_no = "A1.1"
        self.question.save(update_fields=["question_no"])
        AssignmentTool.objects.create(
            tool=self.tool,
            question_no="A1.2",
            co=self.course_outcome,
            marks=5,
        )
        AssignmentTool.objects.create(
            tool=self.tool,
            question_no="A2.1",
            co=second_co,
            marks=8,
        )

        response = self.client.get(
            reverse("assignment_tutorial_marks", args=[self.tool.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        groups = response.context["assignment_groups"]
        self.assertEqual(
            [(group["label"], len(group["questions"])) for group in groups],
            [("Assignment 1", 2), ("Assignment 2", 1)],
        )
        self.assertContains(response, '<th colspan="2">Assignment 1</th>', html=True)
        self.assertContains(response, '<th colspan="1">Assignment 2</th>', html=True)
        self.assertContains(response, '<th title="Max Marks">10</th>', html=True)

    def test_exam_page_saves_co_distribution_rows_and_preserves_student_marks(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        first_detail = ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q1.a",
            co=self.course_outcome,
            bl="BL1",
            marks=10,
        )
        second_detail = ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q1.b",
            co=self.course_outcome,
            bl="BL2",
            marks=5,
        )
        ExamMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=first_detail,
            marks=5,
        )
        ExamMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=second_detail,
            marks=2,
        )

        page = self.client.get(
            reverse("exam_details", args=[self.tool.id]),
            secure=True,
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "No. of CO Distributions")
        self.assertEqual(list(page.context["range"]), [1, 2])
        self.assertNotContains(page, '<option value="3">3</option>', html=True)

        response = self.client.post(
            reverse("exam_details", args=[self.tool.id]),
            {
                "distribution_count": "2",
                "co_Q1": str(self.course_outcome.id),
                "bl_Q1": "BL3",
                "marks_Q1": "6",
                "co_Q2": str(second_co.id),
                "bl_Q2": "BL4",
                "marks_Q2": "4",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        saved_details = list(
            ExamDetail.objects.filter(tool=self.tool).order_by("question_no")
        )
        self.assertEqual(
            [
                (detail.question_no, detail.co_id, detail.bl, detail.marks)
                for detail in saved_details
            ],
            [
                ("Q1", self.course_outcome.id, "BL3", 6),
                ("Q2", second_co.id, "BL4", 4),
            ],
        )
        self.assertEqual(
            ExamMarks.objects.get(
                tool=self.tool,
                student=self.student,
                question=first_detail,
            ).marks,
            5,
        )
        self.assertEqual(
            ExamMarks.objects.get(
                tool=self.tool,
                student=self.student,
                question=second_detail,
            ).marks,
            2,
        )

    def test_exam_distribution_count_cannot_exceed_course_co_count(self):
        response = self.client.post(
            reverse("exam_details", args=[self.tool.id]),
            {"distribution_count": "2"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ExamDetail.objects.filter(tool=self.tool).count(), 0)

    def test_exam_marks_excel_export_includes_co_max_marks_and_total(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        first_detail = ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q1",
            co=self.course_outcome,
            bl="BL1",
            marks=20,
        )
        second_detail = ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q2",
            co=second_co,
            bl="BL2",
            marks=15,
        )
        ExamMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=first_detail,
            marks=12,
        )
        ExamMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=second_detail,
            marks=10,
        )

        response = self.client.post(
            reverse("exam_marks", args=[self.tool.id]),
            {"export_excel": "Export Excel"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        worksheet = load_workbook(BytesIO(response.content), data_only=True).active
        self.assertEqual(
            [worksheet.cell(row=1, column=column).value for column in range(1, 7)],
            [None, None, "Tutorial 1", None, None, None],
        )
        self.assertEqual(
            [worksheet.cell(row=2, column=column).value for column in range(1, 6)],
            ["Roll No", "Student Name", "CO1", "CO2", "Total"],
        )
        self.assertEqual(
            [worksheet.cell(row=3, column=column).value for column in range(1, 6)],
            ["Max Marks", None, 20, 15, "-"],
        )
        self.assertEqual(worksheet.cell(row=4, column=5).value, 22)

    def test_exam_marks_page_groups_columns_under_exam_then_co_and_max_marks(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        self.tool.main_tool = "ISE Exam"
        self.tool.sub_tool = "UT1"
        self.tool.save(update_fields=["main_tool", "sub_tool"])
        ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q1",
            co=self.course_outcome,
            bl="BL1",
            marks=20,
        )
        ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q2",
            co=second_co,
            bl="BL2",
            marks=15,
        )

        response = self.client.get(
            reverse("exam_marks", args=[self.tool.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<th colspan="2">UT1</th>', html=True)
        self.assertContains(response, "CO1")
        self.assertContains(response, "CO2")
        self.assertContains(response, "Max Marks")
        self.assertNotContains(response, "<th>Q1</th>", html=True)
        self.assertNotContains(response, "<th>Q2</th>", html=True)

    def test_exam_marks_excel_import_accepts_co_and_max_marks_rows(self):
        exam_detail = ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q1",
            co=self.course_outcome,
            bl="BL1",
            marks=20,
        )
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append([None, None, "Tutorial 1", None])
        worksheet.append(["Roll No", "Student Name", "CO1", "Total"])
        worksheet.append(["Max Marks", None, 20, "-"])
        worksheet.append([self.student.roll_no, self.student.name, 16, 16])
        file_content = BytesIO()
        workbook.save(file_content)
        upload = SimpleUploadedFile(
            "exam-marks.xlsx",
            file_content.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response = self.client.post(
            reverse("exam_marks", args=[self.tool.id]),
            {"import_excel": "Import Excel", "excel_file": upload},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            ExamMarks.objects.get(
                tool=self.tool,
                student=self.student,
                question=exam_detail,
            ).marks,
            16,
        )

    def test_saving_co_distribution_rows_merges_existing_student_marks(self):
        second_co = CourseOutcome.objects.create(
            course=self.course,
            co_number=2,
            description="Analyze programming concepts",
        )
        old_question = AssignmentTool.objects.create(
            tool=self.tool,
            question_no="A1.1",
            co=self.course_outcome,
            marks=10,
        )
        AssignmentTutorialMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=old_question,
            marks=3,
        )

        response = self.client.post(
            reverse("assignment_tutorial_page", args=[self.tool.id]),
            {
                "assignment_count": "1",
                "total_A1": "10",
                "co_A1.1": str(self.course_outcome.id),
                "bl_A1.1": "BL1",
                "questions_A1.1": "4",
                "co_A1.2": str(second_co.id),
                "bl_A1.2": "BL2",
                "questions_A1.2": "6",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        saved_rows = list(
            AssignmentTool.objects.filter(tool=self.tool).order_by("question_no")
        )
        self.assertEqual(
            [
                (row.question_no, row.co_id, row.question_count, row.marks)
                for row in saved_rows
            ],
            [
                ("A1.1", self.course_outcome.id, 4, 4),
                ("A1.2", second_co.id, 6, 6),
            ],
        )
        migrated_mark = AssignmentTutorialMarks.objects.get(
            tool=self.tool,
            student=self.student,
            question=saved_rows[0],
        )
        self.assertEqual(migrated_mark.marks, 3)
        page_response = self.client.get(
            reverse("assignment_tutorial_page", args=[self.tool.id]),
            secure=True,
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, "No. of Questions")

    def test_updating_po_preserves_course_mapping(self):
        response = self.client.post(
            reverse("manage_po"),
            {"po_count": "1", "po_desc_1": "Updated program outcome"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("manage_po"))
        self.po.refresh_from_db()
        self.assertEqual(self.po.description, "Updated program outcome")
        self.assertTrue(COPOMapping.objects.filter(pk=self.po_mapping.pk).exists())

    def test_updating_pso_preserves_course_mapping(self):
        response = self.client.post(
            reverse("manage_pso"),
            {"pso_count": "1", "pso_desc_1": "Updated specific outcome"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("manage_pso"))
        self.pso.refresh_from_db()
        self.assertEqual(self.pso.description, "Updated specific outcome")
        self.assertTrue(COPSOMapping.objects.filter(pk=self.pso_mapping.pk).exists())

    def test_reducing_po_count_does_not_delete_outcomes_or_course_data(self):
        response = self.client.post(
            reverse("manage_po"),
            {"po_count": "0"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProgramOutcome.objects.filter(pk=self.po.pk).exists())
        self.assertTrue(COPOMapping.objects.filter(pk=self.po_mapping.pk).exists())

    def test_blank_pso_description_does_not_clear_saved_outcome_or_mapping(self):
        response = self.client.post(
            reverse("manage_pso"),
            {"pso_count": "1", "pso_desc_1": ""},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.pso.refresh_from_db()
        self.assertEqual(self.pso.description, "Original specific outcome")
        self.assertTrue(COPSOMapping.objects.filter(pk=self.pso_mapping.pk).exists())

    def test_removing_class_with_students_preserves_class_and_roster(self):
        academic_class = AcademicClass.objects.create(
            department=self.department,
            name="TE",
            academic_year="2026-27",
            semester="3",
        )
        student = Student.objects.create(
            roll_no="2",
            name="Student to preserve",
            academic_class=academic_class,
            department=self.department,
        )

        response = self.client.post(
            reverse("dept_sem_update", args=["2026-27", "3"]),
            {
                f"name_{academic_class.id}": "",
                f"order_{academic_class.id}": "1",
                f"name_{self.academic_class.id}": "SE",
                f"order_{self.academic_class.id}": "1",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AcademicClass.objects.filter(pk=academic_class.pk).exists())
        self.assertTrue(Student.objects.filter(pk=student.pk).exists())

    def test_student_with_assessment_marks_cannot_be_deleted(self):
        UniversityExamMarks.objects.create(
            tool=self.tool,
            student=self.student,
            marks=8,
        )

        response = self.client.post(
            reverse("assign_students", args=[self.academic_class.id]),
            {"action": "delete", "student_id": str(self.student.id)},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())
        self.assertTrue(
            UniversityExamMarks.objects.filter(student=self.student, marks=8).exists()
        )

    def test_student_excel_import_updates_existing_rolls_and_adds_new_rows(self):
        Student.objects.create(
            roll_no="99",
            name="Old Student",
            academic_class=self.academic_class,
            department=self.academic_class.department,
        )
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Roll No", "Name"])
        worksheet.append(["3", "Third Student"])
        worksheet.append([self.student.roll_no, "Updated  Student"])
        worksheet.append(["2", "Second Student"])
        file_content = BytesIO()
        workbook.save(file_content)
        upload = SimpleUploadedFile(
            "students.xlsx",
            file_content.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response = self.client.post(
            reverse("import_class_students_excel", args=[self.academic_class.id]),
            {"excel": upload},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Student.objects.filter(academic_class=self.academic_class).count(),
            3,
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.name, "Updated  Student")
        self.assertEqual(
            list(
                Student.objects.filter(academic_class=self.academic_class)
                .order_by("list_order", "pk")
                .values_list("roll_no", "name")
            ),
            [
                ("3", "Third Student"),
                (self.student.roll_no, "Updated  Student"),
                ("2", "Second Student"),
            ],
        )
        self.assertFalse(
            Student.objects.filter(
                academic_class=self.academic_class,
                roll_no="99",
            ).exists()
        )

    def test_assessment_tool_with_saved_marks_cannot_be_deleted(self):
        saved_mark = AssignmentTutorialMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=self.question,
            marks=6,
        )

        response = self.client.post(
            reverse("delete_assessment_tool", args=[self.tool.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AssessmentTool.objects.filter(pk=self.tool.pk).exists())
        self.assertTrue(AssignmentTutorialMarks.objects.filter(pk=saved_mark.pk).exists())

    def test_course_with_saved_marks_cannot_be_deleted(self):
        saved_mark = AssignmentTutorialMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=self.question,
            marks=6,
        )

        response = self.client.post(
            reverse("delete_course", args=[self.course.id]),
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())
        self.assertTrue(AssignmentTutorialMarks.objects.filter(pk=saved_mark.pk).exists())

    def test_ica_rows_with_marks_cannot_be_removed_by_reducing_row_count(self):
        ica_tool = AssessmentTool.objects.create(
            course=self.course,
            main_tool="ICA",
            sub_tool="Experiment",
        )
        item = IcaAssignmentExp.objects.create(
            tool=ica_tool,
            sub_tool_no=2,
            co=self.course_outcome,
            bl="BL1",
            marks=10,
        )
        IcaStudentMarks.objects.create(
            tool=ica_tool,
            student=self.student,
            subtool=item,
            marks=7,
        )

        response = self.client.post(
            reverse("ica_tool_detail", args=[ica_tool.id]),
            {"total_rows": "1"},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(IcaAssignmentExp.objects.filter(pk=item.pk).exists())
        self.assertTrue(IcaStudentMarks.objects.filter(subtool=item, marks=7).exists())

    def test_exam_distribution_with_marks_cannot_be_removed(self):
        first_detail = ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q1",
            co=self.course_outcome,
            bl="BL1",
            marks=10,
        )
        removed_detail = ExamDetail.objects.create(
            tool=self.tool,
            question_no="Q2",
            co=self.course_outcome,
            bl="BL2",
            marks=10,
        )
        ExamMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=removed_detail,
            marks=5,
        )

        response = self.client.post(
            reverse("exam_details", args=[self.tool.id]),
            {
                "distribution_count": "1",
                "co_Q1": str(self.course_outcome.id),
                "bl_Q1": "BL1",
                "marks_Q1": "10",
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ExamDetail.objects.filter(pk=first_detail.pk).exists())
        self.assertTrue(ExamDetail.objects.filter(pk=removed_detail.pk).exists())
        self.assertTrue(
            ExamMarks.objects.filter(question=removed_detail, marks=5).exists()
        )

    def test_blank_university_exam_total_does_not_clear_saved_configuration(self):
        exam = UniversityExam.objects.create(
            tool=self.tool,
            co=self.course_outcome,
            marks=100,
        )

        response = self.client.post(
            reverse("university_exam_page", args=[self.tool.id]),
            {"total_marks": ""},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(UniversityExam.objects.filter(pk=exam.pk, marks=100).exists())

    def test_university_exam_import_rejects_bad_rows_without_clearing_existing_data(self):
        exam = UniversityExam.objects.create(
            tool=self.tool,
            co=self.course_outcome,
            marks=100,
        )
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["CO No", "Description", "Marks"])
        worksheet.append(["CO99", "Not in this course", 75])
        content = BytesIO()
        workbook.save(content)
        upload = SimpleUploadedFile(
            "university-exam.xlsx",
            content.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response = self.client.post(
            reverse("import_university_exam_excel", args=[self.tool.id]),
            {"excel_file": upload},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(UniversityExam.objects.filter(pk=exam.pk, marks=100).exists())

    def test_importing_over_limit_assignment_marks_reports_skipped_cell(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Roll No", "Student Name", "Q1"])
        worksheet.append([self.student.roll_no, self.student.name, 11])
        file_content = BytesIO()
        workbook.save(file_content)
        upload = SimpleUploadedFile(
            "assignment-marks.xlsx",
            file_content.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response = self.client.post(
            reverse("assignment_tutorial_marks", args=[self.tool.id]),
            {"import_excel": "Import Excel", "excel_file": upload},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("assignment_tutorial_marks", args=[self.tool.id]),
        )
        self.assertEqual(
            self.client.session[f"skipped_assignment_marks_{self.tool.id}"],
            [f"marks_{self.student.id}_{self.question.id}"],
        )

    def test_assignment_excel_export_includes_co_max_marks_and_student_total(self):
        self.question.question_no = "A1.1"
        self.question.save(update_fields=["question_no"])
        AssignmentTutorialMarks.objects.create(
            tool=self.tool,
            student=self.student,
            question=self.question,
            marks=6,
        )

        response = self.client.post(
            reverse("assignment_tutorial_marks", args=[self.tool.id]),
            {"export_excel": "Export Excel"},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        worksheet = workbook.active
        self.assertEqual(
            [worksheet.cell(row=1, column=column).value for column in range(1, 5)],
            ["Assignment", None, "Assignment 1", None],
        )
        self.assertEqual(
            [worksheet.cell(row=2, column=column).value for column in range(1, 5)],
            ["Roll No", "Student Name", "CO1", "Total"],
        )
        self.assertEqual(worksheet.cell(row=3, column=3).value, 10)
        self.assertEqual(worksheet.cell(row=3, column=1).value, "Total Marks")
        self.assertEqual(worksheet.cell(row=4, column=3).value, 6)
        self.assertEqual(worksheet.cell(row=4, column=4).value, 6)

    def test_assignment_excel_import_accepts_assignment_and_co_header_rows(self):
        self.question.question_no = "A1.1"
        self.question.save(update_fields=["question_no"])
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Assignment", None, "Assignment 1", ""])
        worksheet.append(["Roll No", "Student Name", "CO1", "Total"])
        worksheet.append(["Total Marks", None, 10, "-"])
        worksheet.append([self.student.roll_no, self.student.name, 8, 8])
        file_content = BytesIO()
        workbook.save(file_content)
        upload = SimpleUploadedFile(
            "assignment-marks.xlsx",
            file_content.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        response = self.client.post(
            reverse("assignment_tutorial_marks", args=[self.tool.id]),
            {"import_excel": "Import Excel", "excel_file": upload},
            secure=True,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            AssignmentTutorialMarks.objects.get(
                tool=self.tool,
                student=self.student,
                question=self.question,
            ).marks,
            8,
        )
