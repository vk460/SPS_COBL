from django import template

register = template.Library()


# --------------------------------
# Dictionary Access Filter
# --------------------------------
@register.filter
def get_item(value, key):
    """
    Safely get a value from a dictionary in templates.
    Usage:
    {{ my_dict|get_item:"key_name" }}
    """
    if isinstance(value, dict):
        return value.get(key, "")
    return ""


# --------------------------------
# Safe List Access
# --------------------------------
@register.filter
def get_list(value, key):
    """
    Safely return a list from a dictionary.

    Usage:
    {% for item in my_dict|get_list:"key" %}
        {{ item }}
    {% endfor %}
    """
    if isinstance(value, dict):
        result = value.get(key)
        if isinstance(result, list):
            return result
    return []


# --------------------------------
# Student Marks Extractor
# --------------------------------
@register.filter
def get_marks(records, student_id):
    """
    Get obtained marks for a specific student.

    Usage:
    {{ marks_records|get_marks:student.id }}
    """

    if not records:
        return ""

    record = records.get(student_id)

    if record:
        if hasattr(record, "marks"):
            return record.marks
        if hasattr(record, "obtained_marks"):
            return record.obtained_marks

    return ""


# --------------------------------
# Get Total from Nested Dict
# --------------------------------
@register.filter
def get_total(value, key):
    """
    Usage:
    {{ totals|get_total:"key" }}
    """
    if isinstance(value, dict):
        data = value.get(key)
        if isinstance(data, dict):
            return data.get("total", 0)
    return 0


# --------------------------------
# Get Column Data
# --------------------------------
@register.filter
def get_cols(value, key):
    """
    Usage:
    {% for col in data|get_cols:"key" %}
    """
    if isinstance(value, dict):
        data = value.get(key)
        if isinstance(data, dict):
            return data.get("cols", [])
    return []