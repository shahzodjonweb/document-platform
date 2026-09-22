import base64
import secrets
import re
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from .auth import require_staff,audit,ROLES,secret_cipher
from .models import StaffSession,StaffTOTP
from .views import context,finish_render
LABELS={
'en':{'title':'Staff access','intro':'Role-based staff accounts with mandatory authenticator codes.','username':'Username','password':'Initial password · minimum 12 characters','role':'Role','reason':'Reason','create':'Create staff account','active':'Active','change':'Update access','enrollment':'One-time authenticator setup','note':'Save this secret in the authenticator now. It is shown only once.','failed':'Check the username, password, role and reason. Existing users cannot be overwritten.','self':'Your current account cannot be changed here.'},
'uz':{'title':'Xodimlar ruxsati','intro':'Rol va majburiy autentifikator kodi bilan xodim hisoblari.','username':'Foydalanuvchi nomi','password':'Boshlang‘ich parol · kamida 12 belgi','role':'Rol','reason':'Sabab','create':'Xodim yaratish','active':'Faol','change':'Ruxsatni yangilash','enrollment':'Autentifikatorni bir martalik sozlash','note':'Kalitni hozir autentifikatorga saqlang. U bir marta ko‘rsatiladi.','failed':'Nom, parol, rol va sababni tekshiring. Mavjud hisobni almashtirib bo‘lmaydi.','self':'Joriy hisobingizni bu yerda o‘zgartirib bo‘lmaydi.'},
'ru':{'title':'Доступ сотрудников','intro':'Аккаунты сотрудников с ролями и обязательным аутентификатором.','username':'Имя пользователя','password':'Начальный пароль · минимум 12 символов','role':'Роль','reason':'Причина','create':'Создать сотрудника','active':'Активен','change':'Изменить доступ','enrollment':'Одноразовая настройка аутентификатора','note':'Сохраните секрет в аутентификаторе сейчас. Он показан один раз.','failed':'Проверьте имя, пароль, роль и причину. Существующий аккаунт нельзя перезаписать.','self':'Текущий аккаунт нельзя изменить здесь.'}}
@require_staff()
@sensitive_post_parameters('password')
@require_http_methods(['GET','POST'])
def staff(request):
    data=context(request,'staff');t=LABELS[data['lang']];data.update(s=t,title=t['title'],roles=sorted(ROLES))
    if request.method=='POST':
        reason=request.POST.get('reason','').strip();role=request.POST.get('role');username=request.POST.get('username','').strip();action=request.POST.get('action','create')
        if not 5<=len(reason)<=1000 or role not in ROLES:data['error']=t['failed']
        elif action=='create':
            password=request.POST.get('password','')
            if not re.fullmatch(r'[A-Za-z0-9_.@-]{3,100}',username) or not 12<=len(password)<=256 or get_user_model().objects.filter(username=username).exists():data['error']=t['failed']
            else:
                with transaction.atomic():
                    user=get_user_model().objects.create_user(username=username,password=password,is_staff=True,is_active=True)
                    user.groups.set([Group.objects.get_or_create(name=role)[0]])
                    secret=base64.b32encode(secrets.token_bytes(20)).decode()
                    StaffTOTP.objects.create(user=user,encrypted_secret=secret_cipher().encrypt(secret.encode()).decode())
                    audit(request.ops_user,'staff.created',user.pk,reason,after={'role':role,'mfa':True})
                data['enrollment_secret']=secret;data['enrollment_user']=username
        elif action=='update':
            identifier=request.POST.get('user_id','')
            user=get_user_model().objects.filter(pk=int(identifier),is_staff=True).first() if identifier.isdigit() and len(identifier)<20 else None
            if not user:data['error']=t['failed']
            elif user.pk==request.ops_user.pk:data['error']=t['self']
            else:
                with transaction.atomic():
                    user=get_user_model().objects.select_for_update().get(pk=user.pk)
                    before={'roles':list(user.groups.values_list('name',flat=True)),'active':user.is_active,'superuser':user.is_superuser}
                    user.groups.set([Group.objects.get_or_create(name=role)[0]])
                    user.is_active=request.POST.get('active')=='on'
                    # The selected role is authoritative; a legacy Django superuser
                    # flag must not silently retain privileges after demotion.
                    user.is_superuser=False
                    user.save(update_fields=['is_active','is_superuser'])
                    StaffSession.objects.filter(user=user).delete()
                    audit(request.ops_user,'staff.access_changed',user.pk,reason,before,{'role':role,'active':user.is_active,'superuser':False})
        else:data['error']=t['failed']
    data['users']=get_user_model().objects.filter(is_staff=True).prefetch_related('groups').order_by('username')
    return finish_render(request,'ops/staff.html',data)
