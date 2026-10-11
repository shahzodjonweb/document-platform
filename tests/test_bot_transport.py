"""Exercise aiogram routing with real domain services and an offline transport."""
import asyncio
import io
import json
from datetime import datetime,timezone
from pathlib import Path
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage,EditMessageText,SendDocument,AnswerCallbackQuery,GetFile
from aiogram.types import Message,Chat,User,Document,Update,CallbackQuery,File
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone as django_timezone
from pypdf import PdfReader,PdfWriter
from PIL import Image
from apps.core.identity import resolve_account
from apps.core.models import Account,BotConversation,BotDraft,BotCallback,BotInputReceipt,Job,Quote,UsageLedger,AnalyticsEvent
from apps.core.services import upload_file,storage_path
from telegram.bot import COPY, build_dispatcher
from telegram.workflows import attach_input,configure

pytestmark=[pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__();self.calls=[];self.files={};self.counter=1000
    async def close(self): pass
    async def stream_content(self,url,**kwargs):
        key=url.rsplit('/',1)[-1]
        yield self.files[key]
    async def make_request(self,bot,method,timeout=None):
        self.calls.append(method)
        if isinstance(method,AnswerCallbackQuery): return True
        if isinstance(method,GetFile): return File(file_id=method.file_id,file_unique_id=method.file_id,file_size=len(self.files[method.file_id]),file_path=method.file_id)
        self.counter+=1
        chat=Chat(id=int(getattr(method,'chat_id',42)),type='private')
        values={'message_id':self.counter,'date':datetime.now(timezone.utc),'chat':chat,'from_user':User(id=123,is_bot=True,first_name='Fixture bot')}
        if isinstance(method,(SendMessage,EditMessageText)): values.update(text=method.text,reply_markup=method.reply_markup)
        if isinstance(method,SendDocument): values['document']=Document(file_id='out',file_unique_id='out',file_name=method.document.filename)
        return Message(**values).as_(bot)

class Harness:
    def __init__(self,onboard=True):
        self.onboard=onboard
        self.session=OfflineSession();self.bot=Bot('123456:OFFLINE_TEST_TOKEN',session=self.session);self.dispatcher=build_dispatcher();self.count=1
    def user(self,uid=42,locale='en'):
        # Legacy transport/domain tests begin after explicit language selection.
        # This must not create an Account: linking tests prove that identity is
        # created or attached only after the original browser finishes.
        if self.onboard:
            BotConversation.objects.get_or_create(telegram_user_id=uid,defaults={
                'locale':locale,'language_selected_at':django_timezone.now(),
            })
        return User(id=uid,is_bot=False,first_name='Fixture',language_code=locale)
    def incoming(self,uid=42,locale='en',message_id=None,**kwargs):
        self.count+=1
        return Message(message_id=message_id or self.count,date=datetime.now(timezone.utc),chat=Chat(id=uid,type='private'),from_user=self.user(uid,locale),**kwargs)
    def command(self,text,uid=42,locale='en'):
        msg=self.incoming(uid,locale,text=text,entities=[{'type':'bot_command','offset':0,'length':len(text.split()[0])}])
        asyncio.run(self.dispatcher.feed_update(self.bot,Update(update_id=self.count,message=msg)))
    def document(self,key,data,uid=42,message_id=None,name='fixture.pdf'):
        self.session.files[key]=data
        msg=self.incoming(uid,message_id=message_id,document=Document(file_id=key,file_unique_id=key,file_name=name,file_size=len(data)))
        asyncio.run(self.dispatcher.feed_update(self.bot,Update(update_id=self.count,message=msg)))
        return msg.message_id
    def click(self,token,uid=42):
        self.count+=1
        msg=Message(message_id=100,date=datetime.now(timezone.utc),chat=Chat(id=uid,type='private'),from_user=User(id=123,is_bot=True,first_name='Fixture bot'),text='Controls')
        query=CallbackQuery(id=str(self.count),from_user=self.user(uid),chat_instance='private',message=msg,data=token)
        asyncio.run(self.dispatcher.feed_update(self.bot,Update(update_id=self.count,callback_query=query)))
    def token(self,label):
        for call in reversed(self.session.calls):
            markup=getattr(call,'reply_markup',None)
            if markup:
                for row in markup.inline_keyboard:
                    for button in row:
                        if button.text==label and button.callback_data: return button.callback_data
        raise AssertionError(f'Missing button {label}')

    def action(self, action, **payload):
        """Find a rendered control by its behavior, independent of translated copy."""
        for call in reversed(self.session.calls):
            markup = getattr(call, 'reply_markup', None)
            if markup:
                for row in markup.inline_keyboard:
                    for button in row:
                        ref = BotCallback.objects.filter(pk=button.callback_data, action=action).first()
                        if ref and all(ref.payload.get(key) == value for key, value in payload.items()):
                            return button.callback_data
        raise AssertionError(f'Missing action {action}: {payload}')

    def language(self, locale):
        from telegram.onboarding import LANGUAGES
        return self.token(dict(LANGUAGES)[locale])

def pdf(widths=(210,310,410)):
    writer=PdfWriter()
    for width in widths: writer.add_blank_page(width=width,height=500)
    stream=io.BytesIO();writer.write(stream);return stream.getvalue()

def account(uid=42): return resolve_account({'id':uid,'first_name':'Fixture'},is_test=True)
def prepare(feature,params=None,image=False):
    a=account()
    if image:
        stream=io.BytesIO();Image.new('RGB',(50,30),'blue').save(stream,format='PNG');data=stream.getvalue();name='image.png'
    else: data=pdf();name='fixture.pdf'
    asset=upload_file(a,SimpleUploadedFile(name,data))
    attach_input(a,asset,42,1)
    configure(a,feature_id=feature,parameters=params or {})
    return a,asset

def test_bot_file_first_upload_order_quote_and_repeat_run_do_not_duplicate():
    harness=Harness()
    first=harness.document('first',pdf((210,)),message_id=10,name='first.pdf')
    harness.document('second',pdf((310,)),message_id=11,name='Второй.pdf')
    harness.document('first',pdf((210,)),message_id=10,name='first.pdf')
    assert BotInputReceipt.objects.count()==2
    assert len(BotDraft.objects.get().input_ids)==2
    harness.command('/order 2,1')
    harness.command('/done')
    token=harness.action('run')
    harness.click(token);harness.click(token)
    assert Job.objects.count()==1
    job=Job.objects.get();assert job.status=='succeeded',job.error_code
    assert job.origin_channel=='bot'
    output=job.artifacts.get().file
    assert [float(p.mediabox.width) for p in PdfReader(storage_path(output.object_key)).pages]==[310,210]
    assert UsageLedger.objects.filter(job=job,kind='consume',meter='file_tasks').count()==1
    assert any(isinstance(call,SendDocument) for call in harness.session.calls)

def test_bot_callbacks_owner_bound_and_versioned():
    prepare('pdf.rotate')
    harness=Harness();harness.command('/settings')
    token=harness.action('settings', parameters={'angle': 180});draft=BotDraft.objects.get();version=draft.version
    harness.click(token,uid=43)
    draft.refresh_from_db();assert draft.version==version
    harness.click(token);draft.refresh_from_db()
    assert draft.parameters['angle']==180 and draft.version==version+1
    harness.click(token);draft.refresh_from_db();assert draft.version==version+1
    assert Job.objects.count()==0

@pytest.mark.parametrize(('feature','command','expected'),[
    ('pdf.extract_pages','/pages 1,3',{'pages':'1,3'}),
    ('pdf.delete_pages','/pages 2',{'pages':'2'}),
    ('pdf.reorder','/pages 3,1,2',{'order':[3,1,2]}),
    ('pdf.split','/split 1-2;3',{'ranges':['1-2','3']}),
    ('pdf.rotate','/rotate 270 2',{'angle':270,'pages':'2'}),
    ('pdf.to_images','/format jpg 72',{'format':'jpg','dpi':72,'pages':'all'}),
])
def test_readable_bot_commands_preserve_exact_parameters_and_real_outputs(feature,command,expected):
    prepare(feature)
    harness=Harness();harness.command(command);harness.command('/done');harness.command('/run')
    job=Job.objects.get();assert job.status=='succeeded',job.error_code
    assert job.parameters==expected
    assert all(storage_path(a.file.object_key).is_file() for a in job.artifacts.select_related('file'))

def test_image_layout_buttons_and_margin_command():
    prepare('pdf.images_to_pdf',image=True)
    harness=Harness();harness.command('/settings');harness.click(harness.action('settings', parameters={'paper_size': 'Letter'}))
    harness.click(harness.action('settings', parameters={'orientation': 'landscape'}));harness.command('/margin 12');harness.command('/done');harness.command('/run')
    job=Job.objects.get();assert job.status=='succeeded'
    assert job.parameters=={'paper_size':'Letter','orientation':'landscape','margin':12.0}
    page=PdfReader(storage_path(job.artifacts.get().file.object_key)).pages[0]
    assert float(page.mediabox.width)>float(page.mediabox.height)

def test_settings_persist_across_done_and_repeated_done_reuses_quote():
    prepare('pdf.rotate')
    harness=Harness();harness.command('/rotate 180');harness.command('/done');harness.command('/done')
    assert Quote.objects.count()==1
    assert Quote.objects.get().parameters['angle']==180

def test_password_parameters_never_enter_bot_draft_callback_quote_or_analytics():
    prepare('pdf.rotate')
    harness=Harness();secret='dont-store-this-password'
    harness.command('/parameters '+json.dumps({'password':secret}))
    harness.command('/password '+secret)
    assert secret not in json.dumps(list(BotDraft.objects.values('parameters')))
    assert secret not in json.dumps(list(BotCallback.objects.values('payload')))
    assert secret not in json.dumps(list(AnalyticsEvent.objects.values('properties')))
    assert Quote.objects.count()==0
    texts=[getattr(c,'text','') for c in harness.session.calls]
    assert any(COPY['en']['secure'] in text for text in texts)
    assert all(secret not in text for text in texts)

def test_quoted_draft_accepts_more_uploads_and_refreshes_preview_without_processing():
    harness=Harness()
    harness.document('first',pdf((210,)),message_id=10)
    harness.document('second',pdf((310,)),message_id=11)
    harness.command('/done')
    old_run=harness.action('run')
    harness.document('new',pdf((600,)),message_id=22)
    assert len(BotDraft.objects.get().input_ids)==3
    assert BotInputReceipt.objects.filter(message_id=22).count()==1
    harness.document('new',pdf((600,)),message_id=22)
    assert len(BotDraft.objects.get().input_ids)==3
    assert BotInputReceipt.objects.filter(message_id=22).count()==1
    harness.click(old_run)
    assert not Job.objects.exists()
    assert not UsageLedger.objects.exists()

@pytest.mark.parametrize('locale',['en','uz','ru'])
def test_bot_commands_locales_and_menu_has_maximum_six_tools(locale):
    harness=Harness();harness.command('/start',uid=44,locale=locale)
    user=Account.objects.get(telegram_user_id=44);assert user.locale==locale
    tool_calls=BotCallback.objects.filter(account=user,action='tool')
    assert tool_calls.count()<=6
    assert len({row['feature_id'] for row in tool_calls.values_list('payload',flat=True)})==tool_calls.count()

def test_bot_preview_real_png_without_usage_charge():
    prepare('pdf.rotate')
    harness=Harness();harness.command('/preview 2')
    sent=[call for call in harness.session.calls if isinstance(call,SendDocument)]
    assert len(sent)==1
    picture=Image.open(io.BytesIO(sent[0].document.data));assert picture.format=='PNG'
    assert Job.objects.count()==UsageLedger.objects.count()==0
