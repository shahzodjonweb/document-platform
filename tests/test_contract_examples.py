"""The contract says what normalize takes: one normalised example of each kind against the emitted oneOf, and the same bad ones refused by both."""
import json
from pathlib import Path
import jsonschema
import pytest
from apps.core.management.commands.export_contract import schema
from processors.editor import FIELDS,normalize
from processors.engine import ProcessorError
from tests.test_editor_commands import EXAMPLES

CONTRACT=schema()
COMMAND={**CONTRACT['components']['schemas']['EditorCommand'],'components':CONTRACT['components']}


def valid(command):
    return jsonschema.Draft202012Validator(COMMAND).is_valid(command)


def test_the_contract_lists_exactly_the_kinds_the_processor_does():
    kinds=[alternative['properties']['type']['const'] for alternative in COMMAND['oneOf']]
    assert sorted(kinds)==sorted(FIELDS)
    for alternative in COMMAND['oneOf']:
        assert set(alternative['properties'])==FIELDS[alternative['properties']['type']['const']] and alternative['additionalProperties'] is False


@pytest.mark.parametrize('kind',sorted(FIELDS))
def test_one_normalised_example_of_each_kind_fits_the_contract(kind):
    normalized=normalize('editor.visual',{'commands':[EXAMPLES[kind]],'accept_rasterization':True})['commands'][0]
    jsonschema.validate(normalized,COMMAND,cls=jsonschema.Draft202012Validator)


@pytest.mark.parametrize('kind',sorted(FIELDS))
def test_what_a_client_may_leave_out_it_may_leave_out_in_both(kind):
    alternative=next(a for a in COMMAND['oneOf'] if a['properties']['type']['const']==kind)
    for field in set(EXAMPLES[kind])-set(alternative['required']):
        smaller={key:value for key,value in EXAMPLES[kind].items() if key!=field}
        assert valid(smaller),field
        assert normalize('editor.visual',{'commands':[smaller],'accept_rasterization':True})


@pytest.mark.parametrize('command',[
    {'type':'rotate_page','page':1,'angle':45},
    {'type':'rotate_page','page':1,'angle':'90'},
    {'type':'rotate_page','page':1},
    {'type':'reorder','order':['1']},
    {'type':'reorder','order':[]},
    {'type':'reorder','order':[0]},
    {'type':'add_text','page':1,'x':1,'y':1,'text':'a','font':'mono'},
    {'type':'add_text','page':1,'x':1,'y':1,'text':'a','bold':'yes'},
    {'type':'whiteout','page':1,'x':1,'y':1,'width':1,'height':1,'color':'white'},
    {'type':'edit_text','page':1,'x':1,'y':1,'width':1,'height':1,'original':'','text':'a'},
    {'type':'edit_text','page':1,'x':1,'y':1,'width':1,'height':1,'original':'a','text':'я'*2001},
    {'type':'delete_page','page':1,'angle':90},
],ids=lambda command:command['type'])
def test_what_normalize_refuses_the_contract_refuses_too(command):
    assert not valid(command)
    with pytest.raises(ProcessorError):normalize('editor.visual',{'commands':[command],'accept_rasterization':True})


def test_the_new_document_fields_and_answers_are_in_the_contract():
    document=CONTRACT['components']['schemas']['EditorDocument']
    assert {'updated_at','device'}<=set(document['required'])
    post=CONTRACT['paths']['/editor/documents']['post']['responses']
    assert {'200','201'}<=post.keys()
    assert 'device' in CONTRACT['paths']['/editor/documents/{id}']['patch']['requestBody']['content']['application/json']['schema']['properties']
    flags=CONTRACT['paths']['/studio/config']['get']['responses']['200']['content']['application/json']['schema']['properties']['limits']['properties']['editor']
    assert set(flags['required'])=={'editor_v2','pdfcraft','text_edit','deck_editor','edit_buttons','count_once','photos_task'}


def test_the_file_on_disk_is_what_the_generator_says():
    path=Path(__file__).resolve().parent.parent/'contracts'/'public.openapi.json'
    assert json.loads(path.read_text(encoding='utf-8'))==json.loads(json.dumps(CONTRACT,ensure_ascii=False))
