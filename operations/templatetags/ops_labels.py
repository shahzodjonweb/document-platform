from django import template
from operations.i18n import CATALOGS
register = template.Library()

@register.simple_tag
def status_label(value, lang='en'):
    key={'failed':'failed_status','queued':'queued_status','no_op':'no_op'}.get(value,value)
    return CATALOGS.get(lang,CATALOGS['en']).get(key,value)
