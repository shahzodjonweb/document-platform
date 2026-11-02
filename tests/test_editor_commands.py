"""The command contract: what normalize accepts of each kind, and that nothing half-applies a kind no worker can do yet."""
import pytest
from processors.editor import COMMAND_FEATURES,FEATURE_COMMANDS,FIELDS,execute,normalize
from processors.engine import ProcessorError
from apps.studio import editor_policy

BOX={'page':1,'x':10,'y':10,'width':50,'height':20}
EXAMPLES={
 'add_text':{'type':'add_text','page':1,'x':10,'y':10,'text':'Salom','font':'serif','bold':True,'italic':False},
 'highlight':{'type':'highlight',**BOX},
 'note':{'type':'note','page':1,'x':10,'y':10,'text':'Запись'},
 'draw':{'type':'draw','page':1,'points':[[1,1],[2,2]]},
 'fill_form':{'type':'fill_form','field':'name','value':'Ali'},
 'signature':{'type':'signature',**BOX,'input_index':1},
 'insert_image':{'type':'insert_image',**BOX,'input_index':1},
 'replace_text':{'type':'replace_text','page':1,'find':'a','replacement':'b'},
 'replace_image':{'type':'replace_image','page':1,'image_index':0,'input_index':1},
 'remove_image':{'type':'remove_image','page':1,'image_index':0},
 'redact':{'type':'redact',**BOX,'text':'Secret'},
 'edit_text':{'type':'edit_text',**BOX,'original':'Bir qator','text':'Ikki\nqator'},
 'whiteout':{'type':'whiteout',**BOX},
 'rotate_page':{'type':'rotate_page','page':1,'angle':90},
 'delete_page':{'type':'delete_page','page':1},
 'reorder':{'type':'reorder','order':[2,1,3]},
}
# Which fields hold text a customer typed, for each kind that has any. A form field's name is the PDF's own.
TEXT_FIELDS={'add_text':['text'],'note':['text'],'fill_form':['value'],'replace_text':['find','replacement'],'redact':['text'],'edit_text':['original','text']}


def run(*commands,metadata=None,feature='editor.visual'):
    return normalize(feature,{'commands':list(commands),'accept_rasterization':True},metadata)['commands']


def refused(*commands,metadata=None,feature='editor.visual'):
    with pytest.raises(ProcessorError) as caught:run(*commands,metadata=metadata,feature=feature)
    assert caught.value.code=='invalid_editor_command'


def pdf(pages):
    return [{'kind':'pdf','page_count':pages}]


def test_every_kind_has_an_example_and_is_accepted():
    assert EXAMPLES.keys()==FIELDS.keys()
    for kind,command in EXAMPLES.items():
        assert run(command)[0]['type']==kind


def test_both_feature_tables_agree_and_every_kind_has_one():
    assert FIELDS.keys()==COMMAND_FEATURES.keys()==editor_policy.COMMAND_FEATURES.keys()==FEATURE_COMMANDS['editor.visual']
    assert COMMAND_FEATURES==editor_policy.COMMAND_FEATURES
    assert {kind:COMMAND_FEATURES[kind] for kind in ('rotate_page','delete_page','reorder','whiteout','edit_text')}=={'rotate_page':'editor.visual','delete_page':'editor.visual','reorder':'editor.visual','whiteout':'editor.add_text','edit_text':'editor.existing_text'}


def test_the_narrower_features_take_their_new_kinds():
    assert run(EXAMPLES['whiteout'],feature='editor.add_text')
    assert run(EXAMPLES['edit_text'],feature='editor.existing_text')
    refused(EXAMPLES['rotate_page'],feature='editor.add_text')


# A form value alone may keep the line ends it was sent with.
@pytest.mark.parametrize('kind,field,bad',[(kind,field,bad) for kind,fields in TEXT_FIELDS.items() for field in fields for bad in ('\x00','\x07','\r','\x1f') if (kind,bad)!=('fill_form','\r')])
def test_control_characters_are_refused_in_every_text_field(kind,field,bad):
    refused({**EXAMPLES[kind],field:f'a{bad}b'})


@pytest.mark.parametrize('name',['Ism\rFamiliya','Ism\x0bFamiliya','a\x07b','\tq'])
def test_a_form_field_keeps_the_name_the_pdf_gave_it(name):
    assert run({**EXAMPLES['fill_form'],'field':name})[0]['field']==name


@pytest.mark.parametrize('name',['',None,5,'x'*201,'a\x00b'],ids=['empty','none','number','long','nul'])
def test_a_form_field_name_is_still_a_string_that_can_be_stored(name):
    refused({**EXAMPLES['fill_form'],'field':name})


def test_a_form_value_may_keep_a_browsers_line_ends():
    assert run({**EXAMPLES['fill_form'],'value':'a\r\nb'})[0]['value']=='a\r\nb'


def at_fault(*commands,metadata=None):
    with pytest.raises(ProcessorError) as caught:run(*commands,metadata=metadata)
    return caught.value.code,caught.value.index


def test_a_refusal_names_the_command_at_fault():
    good=EXAMPLES['note']
    assert at_fault(good,{**good,'page':0},good)==('invalid_editor_command',1)
    assert at_fault(good,{**good,'color':'red'})==('invalid_editor_command',1)
    assert at_fault('nonsense')==('invalid_editor_command',0)
    assert at_fault(good,good,{**EXAMPLES['signature'],'input_index':1},metadata=[{'kind':'pdf','page_count':3},{'kind':'pdf','page_count':1}])==('unsupported_type',2)


def test_a_refusal_across_the_page_operations_names_the_one_that_broke_the_rule():
    good=EXAMPLES['note'];delete=lambda page:{'type':'delete_page','page':page}
    assert at_fault(good,EXAMPLES['rotate_page'],good,{**EXAMPLES['rotate_page'],'angle':180})==('invalid_editor_command',3)
    assert at_fault(delete(2),good,delete(2))==('invalid_editor_command',2)
    assert at_fault(delete(1),good,delete(2),good,metadata=pdf(2))==('invalid_editor_command',2)
    assert at_fault(good,{'type':'reorder','order':[1,1]},metadata=pdf(2))==('invalid_editor_command',1)
    assert at_fault({'type':'reorder','order':[2,1]},good,{'type':'reorder','order':[1,2]},metadata=pdf(2))==('invalid_editor_command',2)


def test_a_refusal_of_the_whole_list_names_no_command():
    assert at_fault(EXAMPLES['redact'],EXAMPLES['note'])==('redaction_requires_separate_export',None)


@pytest.mark.parametrize('kind,field',[(kind,field) for kind,fields in TEXT_FIELDS.items() for field in fields])
def test_a_line_break_and_a_tab_are_text(kind,field):
    assert run({**EXAMPLES[kind],field:'a\n\tb'})[0][field]=='a\n\tb'


def test_edit_text_bounds():
    assert run({**EXAMPLES['edit_text'],'text':''})[0]['text']==''
    assert run({**EXAMPLES['edit_text'],'text':'я'*2000,'original':'я'*2000})
    for change in ({'original':''},{'original':'я'*2001},{'text':'я'*2001},{'text':5},{'original':None}):
        refused({**EXAMPLES['edit_text'],**change})
    for missing in ('original','text','x','width'):
        refused({key:value for key,value in EXAMPLES['edit_text'].items() if key!=missing})


def test_whiteout_is_white_unless_told_otherwise():
    assert run(EXAMPLES['whiteout'])[0]['color']=='#FFFFFF'
    assert run({**EXAMPLES['whiteout'],'color':'#102030'})[0]['color']=='#102030'
    for color in ('white','#FFF',1):refused({**EXAMPLES['whiteout'],'color':color})


@pytest.mark.parametrize('angle',[0,45,360,-90,True,'90',90.0,None])
def test_rotate_page_angle(angle):
    refused({**EXAMPLES['rotate_page'],'angle':angle})


def test_rotate_page_once_per_page():
    assert len(run({'type':'rotate_page','page':1,'angle':90},{'type':'rotate_page','page':2,'angle':180}))==2
    refused({'type':'rotate_page','page':1,'angle':90},{'type':'rotate_page','page':1,'angle':180})


def test_delete_page_once_per_page_and_one_must_survive():
    delete=lambda page:{'type':'delete_page','page':page}
    assert len(run(delete(1),delete(2),metadata=pdf(3)))==2
    refused(delete(1),delete(1),metadata=pdf(3))
    refused(delete(1),delete(2),delete(3),metadata=pdf(3))
    refused(delete(1),metadata=pdf(1))
    refused(delete(4),metadata=pdf(3))
    # With no page count to go by, only the page numbers can be held.
    assert len(run(delete(1),delete(2)))==2


def test_reorder_is_one_permutation_of_every_source_page():
    assert run({'type':'reorder','order':[3,1,2]},metadata=pdf(3))[0]['order']==[3,1,2]
    assert run({'type':'reorder','order':[2,1]})[0]['order']==[2,1]
    for order in ([1,2],[1,2,2],[1,2,3,4],[0,1,2],[1,2,'3'],[1,2,3.0],[True,2,3],[],None,'123',{}):
        refused({'type':'reorder','order':order},metadata=pdf(3))
    for order in ([2,3],[1,1],[],[1.0,2.0]):
        refused({'type':'reorder','order':order})
    refused({'type':'reorder'},metadata=pdf(3))
    refused({'type':'reorder','order':[1,2,3]},{'type':'reorder','order':[3,2,1]},metadata=pdf(3))
    refused({'type':'reorder','order':[1,2,3],'page':1},metadata=pdf(3))


def test_deleted_pages_stay_in_the_order():
    commands=[{'type':'delete_page','page':2},{'type':'reorder','order':[3,2,1]}]
    assert [c['type'] for c in run(*commands,metadata=pdf(3))]==['delete_page','reorder']
    refused({'type':'delete_page','page':2},{'type':'reorder','order':[3,1]},metadata=pdf(3))


def test_add_text_may_name_a_font_and_styles():
    plain=run({'type':'add_text','page':1,'x':1,'y':1,'text':'a'})[0]
    assert {'font','bold','italic'}.isdisjoint(plain),'what was not asked for is not stored: it costs draft bytes'
    for change in ({'font':'mono'},{'font':1},{'bold':1},{'bold':'true'},{'italic':None}):
        refused({**EXAMPLES['add_text'],**change})


def test_redact_text_is_optional():
    assert 'text' not in run({'type':'redact',**BOX})[0]
    refused({'type':'redact',**BOX,'text':'я'*2001})
    refused({'type':'redact',**BOX,'text':7})


@pytest.mark.parametrize('kind',['edit_text'])
def test_a_kind_no_worker_can_apply_yet_stops_the_job_before_anything_is_written(kind,tmp_path):
    with pytest.raises(ProcessorError) as caught:
        execute('editor.visual',[tmp_path/'never-opened.pdf'],{'commands':[EXAMPLES['note'],run(EXAMPLES[kind])[0]]},tmp_path,[])
    assert caught.value.code=='invalid_editor_command' and caught.value.index==1 and not list(tmp_path.iterdir())


def test_validate_commands_access_knows_the_new_kinds(monkeypatch):
    seen=[]
    monkeypatch.setattr(editor_policy,'allowed',lambda account,feature:seen.append(feature) or True)
    editor_policy.validate_commands_access(None,[EXAMPLES[kind] for kind in ('rotate_page','whiteout','edit_text')])
    assert seen==['editor.visual','editor.add_text','editor.existing_text']
