"""Published renderer presets, with server-enforced plan eligibility."""
from apps.core.errors import DomainError
TEMPLATES=[
 {'id':'clean','name':'Clean document','kind':'document','style':{'accent':'#255e49'}},
 {'id':'classroom','name':'Classroom worksheet','kind':'education','style':{'accent':'#3b6588'}},
 {'id':'presentation','name':'Editorial slides','kind':'slides','style':{'accent':'#255e49'}},
 {'id':'executive_report','name':'Executive report','kind':'professional','style':{'accent':'#273e65','layout':'executive','margin':58,'body_size':11,'body_leading':19}},
 {'id':'compact_brief','name':'Compact brief','kind':'professional','style':{'accent':'#664d36','layout':'compact','margin':36,'body_size':9,'body_leading':13}},
 {'id':'study_notes','name':'Study notes','kind':'professional','style':{'accent':'#56417b','layout':'notes','margin':64,'body_size':11,'body_leading':22}},
]

def published(account):
    from .domain import allowed
    return [{**row,'locales':['en','uz','ru'],'eligible':row['kind']!='professional' or allowed(account,'template.professional')} for row in TEMPLATES]

def style_for(account,identifier):
    row=next((row for row in published(account) if row['id']==identifier),None)
    if row is None:return None
    if not row['eligible']:raise DomainError('feature_not_in_plan',403)
    return dict(row['style'])
