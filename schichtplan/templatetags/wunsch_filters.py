from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Ermöglicht dict[key] Zugriff in Templates
    Verwendung: {{ dict|get_item:key }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)