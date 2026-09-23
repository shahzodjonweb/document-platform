from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from apps.core.errors import DomainError
from .auth import require_staff,audit,development_access
from .views import context,finish_render
from .integrations import telegram_config,ai_config,save_config,test_telegram,control_runner,runner_status
from .models import IntegrationConfig

LABELS={
'en':{'integrations':'Integrations','intro':'Connect your Telegram bot and choose the document generation provider. Secrets are encrypted and never shown after saving.','telegram':'Telegram bot','token':'Bot token','username':'Bot username','webapp':'Web application URL','secret_hint':'Leave blank to keep the saved secret.','reason':'Reason for this change','save':'Save configuration','test':'Test connection','start':'Start local bot','stop':'Stop local bot','ai':'Document generation','mode':'Provider mode','local':'Local authoring · no AI calls','live':'OpenAI · real API calls','disabled':'Disabled','key':'API key','model':'Model ID','configured':'Configured','missing':'Not configured','running':'Running','stopped':'Stopped','local_note':'Local polling needs a real Telegram token. Telegram Mini Apps require an HTTPS URL; ordinary browser tools work on localhost.','saved':'Configuration saved.','connected':'Connected to Telegram.','action_done':'Bot control updated.','failure':'Could not complete this action. Check configuration and try again.','need_reason':'Enter a reason of at least 5 characters.','token_status':'Token status','provider_status':'Provider status','simulator':'Open local bot simulator'},
'uz':{'integrations':'Integratsiyalar','intro':'Telegram botingizni ulang va hujjat yaratish provayderini tanlang. Maxfiy kalitlar shifrlanadi va saqlangandan keyin ko‘rsatilmaydi.','telegram':'Telegram bot','token':'Bot tokeni','username':'Bot foydalanuvchi nomi','webapp':'Veb ilova manzili','secret_hint':'Saqlangan kalitni qoldirish uchun bo‘sh qoldiring.','reason':'O‘zgarish sababi','save':'Sozlamalarni saqlash','test':'Ulanishni tekshirish','start':'Mahalliy botni ishga tushirish','stop':'Mahalliy botni to‘xtatish','ai':'Hujjat yaratish','mode':'Provayder rejimi','local':'Mahalliy tahrirlash · AI chaqirilmaydi','live':'OpenAI · haqiqiy API','disabled':'O‘chirilgan','key':'API kaliti','model':'Model identifikatori','configured':'Sozlangan','missing':'Sozlanmagan','running':'Ishlamoqda','stopped':'To‘xtatilgan','local_note':'Mahalliy bot uchun haqiqiy Telegram tokeni kerak. Telegram Mini App uchun HTTPS manzil zarur; brauzer vositalari localhost’da ishlaydi.','saved':'Sozlamalar saqlandi.','connected':'Telegram ulandi.','action_done':'Bot boshqaruvi yangilandi.','failure':'Amal bajarilmadi. Sozlamalarni tekshirib, qayta urinib ko‘ring.','need_reason':'Kamida 5 belgidan iborat sabab kiriting.','token_status':'Token holati','provider_status':'Provayder holati','simulator':'Mahalliy bot simulyatorini ochish'},
'ru':{'integrations':'Интеграции','intro':'Подключите Telegram-бота и выберите провайдера генерации документов. Секреты шифруются и не показываются после сохранения.','telegram':'Telegram-бот','token':'Токен бота','username':'Имя бота','webapp':'Адрес веб-приложения','secret_hint':'Оставьте пустым, чтобы сохранить текущий ключ.','reason':'Причина изменения','save':'Сохранить настройки','test':'Проверить соединение','start':'Запустить локального бота','stop':'Остановить локального бота','ai':'Генерация документов','mode':'Режим провайдера','local':'Локальное редактирование · без ИИ','live':'OpenAI · реальные вызовы API','disabled':'Отключено','key':'Ключ API','model':'ID модели','configured':'Настроено','missing':'Не настроено','running':'Работает','stopped':'Остановлен','local_note':'Для локального бота нужен настоящий токен Telegram. Mini App требует HTTPS; инструменты браузера работают на localhost.','saved':'Настройки сохранены.','connected':'Соединение с Telegram установлено.','action_done':'Управление ботом обновлено.','failure':'Не удалось выполнить действие. Проверьте настройки и повторите.','need_reason':'Укажите причину длиной не менее 5 символов.','token_status':'Состояние токена','provider_status':'Состояние провайдера','simulator':'Открыть локальный симулятор бота'}}

for language,label in {'en':'Image model ID (optional)','uz':'Rasm modeli identifikatori (ixtiyoriy)','ru':'ID модели изображений (необязательно)'}.items():LABELS[language]['image_model']=label

for language, values in {
    'en': ('Managed by server', 'Waiting for credentials', 'Save your Telegram token and username here. The server starts the bot automatically; use Test connection to verify the credentials.'),
    'uz': ('Server boshqaradi', 'Kirish ma’lumotlari kutilmoqda', 'Telegram tokeni va foydalanuvchi nomini shu yerda saqlang. Server botni avtomatik ishga tushiradi; ma’lumotlarni Ulanishni tekshirish orqali tekshiring.'),
    'ru': ('Управляется сервером', 'Ожидание учётных данных', 'Сохраните токен Telegram и имя бота здесь. Сервер запустит бота автоматически; проверьте данные кнопкой «Проверить соединение».'),
}.items():
    LABELS[language].update(zip(('managed', 'waiting', 'production_note'), values))

@require_staff()
@sensitive_post_parameters('token','api_key')
@require_http_methods(['GET','POST'])
def integrations(request):
    data=context(request,'integrations');labels=LABELS[data['lang']];data['i']=labels;data['title']=labels['integrations']
    if request.method=='POST':
        action=request.POST.get('action','save');reason=request.POST.get('reason','').strip()
        if not 5<=len(reason)<=1000:data['error']=labels['need_reason']
        else:
            try:
                key=request.POST.get('integration','telegram')
                if action!='save' and key!='telegram':raise DomainError('invalid_parameters')
                if action=='save':save_config(key,request.POST);message='saved'
                elif action=='test':test_telegram();message='connected'
                elif action in ('start','stop'):
                    if not development_access(request):raise DomainError('local_control_only',403)
                    control_runner(action);message='action_done'
                else:raise DomainError('invalid_parameters')
                audit(request.ops_user,'integration.'+action,key,reason,after={'configured':True})
                return redirect('/ops/integrations?lang='+data['lang']+'&notice='+message)
            except DomainError as e:
                data['error']=labels['failure'];data['error_code']=e.code
    bot=telegram_config();ai=ai_config()
    local_controls=development_access(request)
    # A container-managed bot has a different PID namespace from the API.
    # Do not misreport it as stopped using the local development PID check.
    status=labels[runner_status()] if local_controls else labels['managed' if bot['token'] else 'waiting']
    # Never include credentials in the template context.
    data.update(bot={'username':bot['username'],'webapp_url':bot['webapp_url'],'configured':bool(bot['token']),'status':status},ai={'mode':ai['mode'],'model':ai['model'],'image_model':ai['image_model'],'configured':bool(ai['api_key'])},local_controls=local_controls,notice=labels.get(request.GET.get('notice',''),''))
    return finish_render(request,'ops/integrations.html',data)
