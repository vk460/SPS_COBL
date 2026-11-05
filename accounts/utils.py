from .models import PO, PSO


def get_po_pso_for_student(student):
    """
    Rule:
    - If student is in General Science FY
      → use admitted_department PO/PSO
    - Else
      → use class department PO/PSO
    """

    if student.academic_class.department.is_general_science:
        department = student.admitted_department
    else:
        department = student.academic_class.department

    po_list = PO.objects.filter(department=department).order_by('number')
    pso_list = PSO.objects.filter(department=department).order_by('number')

    return po_list, pso_list