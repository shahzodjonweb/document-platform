"""Question/answer rendering and feature-specific quote/settlement arithmetic."""
import pytest
from pypdf import PdfReader
from apps.core.policy import SEED
from apps.core.services import submit_job,execute_job,storage_path
from apps.studio import provider
from apps.studio.domain import create_draft,update_draft,generation_quote
from apps.studio.metering import generation_credits
from apps.studio.rendering import render_pdf
from operations.integrations import save_config
from tests.test_platform import account
from tests.test_studio import paid
from tests.test_studio_adversarial import source_document
pytestmark=pytest.mark.django_db

@pytest.fixture(autouse=True)
def local(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.COMMERCE_SANDBOX_ENABLED=True


def questions(count):
    return [{'id':f'q{i}','stem':f'Question {i}?','options':[],'answer':f'Answer value {i}','explanation':f'Explanation value {i}','topic':'review','marks':3} for i in range(count)]


@pytest.mark.parametrize('feature',['study.flashcards','study.answer_key'])
def test_study_pdf_contains_answers_explanations_and_key_marks(settings,feature):
    a=paid(settings,account());d=create_draft(a,{'feature_id':feature,'options':{'length':1,'questions':questions(2)}})
    q=generation_quote(a,d.id,1);job,_=submit_job(a,q.id,'study-output-'+feature);job=execute_job(job.id)
    assert job.status=='succeeded',job.error_code
    artifact=job.artifacts.get();assert artifact.role=='user_document'
    text=''.join(page.extract_text() for page in PdfReader(storage_path(artifact.file.object_key)).pages)
    assert 'Question 0?' in text and 'Answer value 0' in text and 'Explanation value 1' in text
    assert ('Card 1' in text) if feature=='study.flashcards' else ('3 points' in text)


def test_flashcard_tariff_shared_by_quote_and_actual(settings,monkeypatch):
    a=paid(settings,account());save_config('ai',{'mode':'openai','model':'offline-test-model','api_key':'sk-offline'})
    d=create_draft(a,{'feature_id':'study.flashcards','source_text':'Review','options':{'length':1,'question_count':6}})
    raw={'title':'Cards','answer_supported':True,'citations':[],'sections':[{'id':'s1','heading':'','body':'','notes':''}],'questions':questions(6)}
    monkeypatch.setattr(provider,'generate',lambda *args,**kwargs:(raw,{'input_tokens':100,'output_tokens':100}))
    q=generation_quote(a,d.id,1);tariff=q.policy['generation_bounds']['tariff']
    assert q.meters['ai_credits']==q.policy['generation_bounds']['output_pages']*tariff['pdf_output_credits_per_started_page']+2
    job,_=submit_job(a,q.id,'flashcard-tariff');job=execute_job(job.id);assert job.status=='succeeded',job.error_code
    pages=job.artifacts.get().file.page_count
    assert job.settled_meters['ai_credits']==pages*tariff['pdf_output_credits_per_started_page']+2


def test_pdf_qa_base_tariff_in_quote_and_actual(settings,monkeypatch):
    a=paid(settings,account());asset=source_document(a)
    save_config('ai',{'mode':'openai','model':'offline-test-model','api_key':'sk-offline'})
    d=create_draft(a,{'feature_id':'study.pdf_qa','source_ids':[str(asset.id)],'options':{'length':1,'question_count':0}})
    raw={'title':'Answer','answer_supported':True,'citations':[{'asset_id':str(asset.id),'page':1,'quote':'The river flows north.'}],'sections':[{'id':'s1','heading':'Answer','body':'The river flows north.','notes':''}],'questions':[]}
    monkeypatch.setattr(provider,'generate',lambda *args,**kwargs:(raw,{'input_tokens':100,'output_tokens':100}))
    q=generation_quote(a,d.id,1);tariff=q.policy['generation_bounds']['tariff']
    assert q.meters['ai_credits']==q.policy['generation_bounds']['output_pages']*tariff['pdf_output_credits_per_started_page']+tariff['source_ingestion_credits_per_started_5_pages']+tariff['qa_base_credits']
    job,_=submit_job(a,q.id,'qa-base-tariff');job=execute_job(job.id);assert job.status=='succeeded',job.error_code
    assert job.settled_meters['ai_credits']==tariff['pdf_output_credits_per_started_page']+tariff['source_ingestion_credits_per_started_5_pages']+tariff['qa_base_credits']


@pytest.mark.parametrize('locale,source_label,page_label',[('en','Source','p.'),('uz','Manba','b.'),('ru','Источник','стр.')])
def test_rendered_source_labels_are_localized(tmp_path,locale,source_label,page_label):
    content={'title':'Citation','sections':[{'heading':'Test','body':'Text'}],'questions':[],'citations':[{'asset_id':'source-example','page':3}]}
    path=tmp_path/'source.pdf';render_pdf(content,path,locale)
    text=PdfReader(path).pages[0].extract_text()
    assert source_label in text and page_label+' 3' in text
