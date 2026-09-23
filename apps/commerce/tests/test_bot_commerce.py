import asyncio
import io
from datetime import timedelta
from unittest.mock import AsyncMock,Mock
import pytest
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from pypdf import PdfWriter,PdfReader
from apps.core.identity import resolve_account
from apps.core.models import Job,UsageLedger,BotDraft,BotConversation
from apps.core.services import storage_path,upload_file,create_quote,submit_job,execute_job
from apps.commerce.models import Payment,LocalBotMessage,BotDelivery
from apps.commerce.services import create_invoice,payload_for
from telegram.delivery import enqueue,attempt

pytestmark=pytest.mark.django_db(transaction=True)

def principal(uid=910001):
    a=resolve_account({'id':uid,'first_name':'Local bot'},is_test=True)
    # Commerce scenarios start after the language-first onboarding flow.
    BotConversation.objects.update_or_create(telegram_user_id=uid,defaults={'locale':'en','language_selected_at':timezone.now()})
    c=Client();s=c.session;s['customer_account_id']=str(a.id);s.save();return a,c

def command(c,text):
    r=c.post('/api/v1/telegram/local/messages',{'text':text},content_type='application/json')
    assert r.status_code==200,r.content
    return r.json()

def click(c,token):
    r=c.post('/api/v1/telegram/local/messages',{'callback_data':token},content_type='application/json')
    assert r.status_code==200,r.content
    return r.json()

def token(result,label):
    for m in reversed(result['messages']):
        for row in m['buttons']:
            for button in row:
                if button['label']==label:return button['callback_data']
    raise AssertionError(label)

def pdf(width):
    out=io.BytesIO();w=PdfWriter();w.add_blank_page(width=width,height=400);w.write(out);return out.getvalue()

def test_local_bot_actual_billing_callbacks_activate_once_without_network(monkeypatch):
    a,c=principal()
    # Any accidental use of the live provider fails the test.
    from apps.commerce.providers import TelegramStarsProvider
    monkeypatch.setattr(TelegramStarsProvider,'call',lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('Live Telegram called')))
    response=command(c,'/buy plus');pay=token(response,'Simulate local payment')
    assert Payment.objects.count()==0
    click(c,pay);click(c,pay)
    a.refresh_from_db();assert a.plan=='plus' and Payment.objects.count()==1
    confirmation=command(c,'/cancelrenewal')
    assert a.subscription.renewal_enabled
    click(c,token(confirmation,'Confirm change'))
    a.subscription.refresh_from_db();assert not a.subscription.renewal_enabled
    confirmation=command(c,'/resumerenewal')
    a.subscription.refresh_from_db();assert not a.subscription.renewal_enabled
    click(c,token(confirmation,'Confirm change'))
    a.subscription.refresh_from_db();assert a.subscription.renewal_enabled

def test_local_bot_file_upload_merge_download_and_durable_delivery():
    a,c=principal()
    for i,width in enumerate((220,320)):
        r=c.post('/api/v1/telegram/local/messages',{'file':SimpleUploadedFile(f'{i}.pdf',pdf(width))})
        assert r.status_code==200,r.content
    command(c,'/order 2,1');review=command(c,'/done')
    run=token(review,'Run task');click(c,run);click(c,run)
    assert Job.objects.count()==1
    job=Job.objects.get();assert job.status=='succeeded'
    assert [float(p.mediabox.width) for p in PdfReader(storage_path(job.artifacts.get().file.object_key)).pages]==[320,220]
    assert UsageLedger.objects.filter(job=job,kind='consume',meter='file_tasks').count()==1
    assert BotDelivery.objects.filter(status='delivered').count()==1
    assert LocalBotMessage.objects.filter(asset__isnull=False,direction='outbound').count()==1

def test_local_bot_sessions_owner_scoped_passwords_omitted_and_fail_closed(settings):
    a,c=principal();b,other=principal(910002)
    response=command(c,'/buy plus');payment_button=token(response,'Simulate local payment')
    click(other,payment_button)
    assert Payment.objects.count()==0
    secret='never-store-password-test'
    command(c,'/password '+secret)
    assert not LocalBotMessage.objects.filter(text__contains=secret).exists()
    assert len(c.get('/api/v1/telegram/local/messages').json()['messages'])>len(other.get('/api/v1/telegram/local/messages').json()['messages'])
    settings.DEBUG=False
    assert c.get('/api/v1/telegram/local/messages').status_code==403

def test_failed_delivery_retry_does_not_reprocess_or_charge_twice():
    a,_=principal();asset=upload_file(a,SimpleUploadedFile('source.pdf',pdf(220)))
    a.is_test=False;a.save(update_fields=['is_test'])
    q=create_quote(a,'pdf.rotate',[str(asset.id)],{});job,_=submit_job(a,q.id,'delivery-test-job');job=execute_job(job.id)
    delivery=enqueue(job.artifacts.get(),'delivery-fixture-key')
    bot=Mock();bot.send_document=AsyncMock(side_effect=RuntimeError('do not log raw failure'))
    asyncio.run(attempt(delivery.id,bot));delivery.refresh_from_db()
    assert delivery.status=='retrying' and delivery.attempts==1 and delivery.error_code=='telegram_delivery_failed'
    BotDelivery.objects.filter(pk=delivery.id).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
    bot.send_document=AsyncMock(return_value=Mock(message_id=33))
    asyncio.run(attempt(delivery.id,bot));asyncio.run(attempt(delivery.id,bot))
    delivery.refresh_from_db();assert delivery.status=='delivered' and delivery.message_id==33
    assert bot.send_document.await_count==1
    assert Job.objects.get(pk=job.id).attempt_count==1
    assert UsageLedger.objects.filter(job=job,kind='consume',meter='file_tasks').count()==1

def test_bot_workspace_commands_use_current_admin_url_and_keep_owned_input():
    from operations.integrations import save_config
    a,c=principal()
    save_config('telegram',{'webapp_url':'http://localhost:3000/en/app','username':''})
    for command_name in ('create','study','school','teach','editor'):
        result=command(c,'/'+command_name)
        button=result['messages'][-1]['buttons'][0][0]
        assert button['url']==f'http://localhost:3000/en/app/{command_name}'

def test_fast_precheckout_answers_invalid_request_without_grant(monkeypatch):
    from telegram.billing import fast_precheckout
    from apps.commerce.providers import TelegramStarsProvider
    calls=[]
    monkeypatch.setattr(TelegramStarsProvider,'call',lambda _,method,**kwargs:calls.append((method,kwargs)) or True)
    assert fast_precheckout({'pre_checkout_query':{'id':'query-1','from':{'id':123},'invoice_payload':'invalid','currency':'XTR','total_amount':100}})
    assert calls[0][0]=='answer_pre_checkout_query' and calls[0][1]['ok'] is False
    assert Payment.objects.count()==0

def test_live_transport_cannot_deliver_test_account_files():
    from aiogram import Bot
    a,_=principal();asset=upload_file(a,SimpleUploadedFile('source.pdf',pdf(220)))
    q=create_quote(a,'pdf.rotate',[str(asset.id)],{});job,_=submit_job(a,q.id,'test-isolation-job');job=execute_job(job.id)
    delivery=enqueue(job.artifacts.get(),'test-account-delivery')
    async def check():
        bot=Bot('123456:TEST_DO_NOT_USE_NETWORK')
        bot.send_document=AsyncMock(side_effect=AssertionError('Network must not be contacted'))
        try:
            await attempt(delivery.id,bot)
            assert bot.send_document.await_count==0
        finally:await bot.session.close()
    asyncio.run(check());delivery.refresh_from_db()
    assert delivery.status=='blocked' and delivery.error_code=='test_account_delivery'

def test_local_browser_deliver_uses_simulator_and_command_menus_are_localized():
    from telegram.commands import install_commands
    a,c=principal();asset=upload_file(a,SimpleUploadedFile('source.pdf',pdf(220)))
    q=create_quote(a,'pdf.rotate',[str(asset.id)],{});job,_=submit_job(a,q.id,'browser-delivery-job');job=execute_job(job.id)
    url=f'/api/v1/artifacts/{job.artifacts.get().id}/deliver'
    for _ in range(2):
        response=c.post(url,{},content_type='application/json',HTTP_IDEMPOTENCY_KEY='browser-delivery-key')
        assert response.status_code in (200,201) and response.json()['status']=='delivered'
    assert LocalBotMessage.objects.filter(asset__isnull=False).count()==1
    bot=Mock();bot.set_my_commands=AsyncMock();bot.set_chat_menu_button=AsyncMock()
    asyncio.run(install_commands(bot))
    assert [c.kwargs['language_code'] for c in bot.set_my_commands.await_args_list]==['','en','uz','ru']
    assert all(any(v.command=='buy' for v in call.args[0]) for call in bot.set_my_commands.await_args_list)
    assert bot.set_chat_menu_button.await_args.kwargs['menu_button'].type=='commands'

def test_polling_process_lock_blocks_duplicates_and_does_not_store_tokens(settings):
    import os
    from telegram.locking import polling_lock
    with polling_lock():
        path=settings.PRIVATE_STORAGE_ROOT/'runbot.lock'
        assert path.stat().st_mode&0o777==0o600 and path.read_text()==str(os.getpid())
        with pytest.raises(RuntimeError,match='already running'):
            with polling_lock():pass
    with polling_lock():pass

def test_usage_alias_and_unknown_commands_always_answer():
    a,c=principal()
    for command_text in ('/usage','/plan','/unknown_command','Some unrecognized text'):
        result=command(c,command_text)
        assert result['messages'][-1]['direction']=='outbound'
        assert result['messages'][-1]['text']
