import re
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from .auth import require_staff,audit,ROLES
from .models import StaffSession
from .views import context,finish_render
LABELS={
'en':{'title':'Staff access','intro':'Staff accounts with a role. Each person signs in with their username and password.','username':'Username','password':'Initial password · minimum 12 characters','role':'Role','reason':'Reason','create':'Create staff account','active':'Active','change':'Update access','created':'Account created. Give them their username and password; they can sign in now.','failed':'Check the username, password and role. Existing users cannot be overwritten.','add':'Add staff member','last_login':'Last sign-in','you':'you','never':'never','self':'Your current account cannot be changed here.'},
'uz':{'title':'Xodimlar ruxsati','intro':'Rolga ega xodim hisoblari. Har kim o‘z logini va paroli bilan kiradi.','username':'Foydalanuvchi nomi','password':'Boshlang‘ich parol · kamida 12 belgi','role':'Rol','reason':'Sabab','create':'Xodim yaratish','active':'Faol','change':'Ruxsatni yangilash','created':'Hisob yaratildi. Unga login va parolni bering — hozir kira oladi.','failed':'Nom, parol va rolni tekshiring. Mavjud hisobni almashtirib bo‘lmaydi.','add':'Xodim qo‘shish','last_login':'Oxirgi kirish','you':'siz','never':'hali yo‘q','self':'Joriy hisobingizni bu yerda o‘zgartirib bo‘lmaydi.'},
'ru':{'title':'Доступ сотрудников','intro':'Аккаунты сотрудников с ролями. Каждый входит со своим логином и паролем.','username':'Имя пользователя','password':'Начальный пароль · минимум 12 символов','role':'Роль','reason':'Причина','create':'Создать сотрудника','active':'Активен','change':'Изменить доступ','created':'Аккаунт создан. Передайте логин и пароль — сотрудник может войти сразу.','failed':'Проверьте имя, пароль и роль. Существующий аккаунт нельзя перезаписать.','add':'Добавить сотрудника','last_login':'Последний вход','you':'вы','never':'ещё нет','self':'Текущий аккаунт нельзя изменить здесь.'}}
@require_staff()
@sensitive_post_parameters('password')
@require_http_methods(['GET','POST'])
def staff(request):
    data=context(request,'staff');t=LABELS[data['lang']];data.update(s=t,title=t['title'],roles=sorted(ROLES))
    if request.method=='POST':
        role=request.POST.get('role');username=request.POST.get('username','').strip();action=request.POST.get('action','create')
        if role not in ROLES:data['error']=t['failed']
        elif action=='create':
            password=request.POST.get('password','')
            if not re.fullmatch(r'[A-Za-z0-9_.@-]{3,100}',username) or not 12<=len(password)<=256 or get_user_model().objects.filter(username=username).exists():data['error']=t['failed']
            else:
                with transaction.atomic():
                    user=get_user_model().objects.create_user(username=username,password=password,is_staff=True,is_active=True)
                    user.groups.set([Group.objects.get_or_create(name=role)[0]])
                    audit(request.ops_user,'staff.created',user.pk,after={'role':role})
                data['created_user']=username
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
                    audit(request.ops_user,'staff.access_changed',user.pk,None,before,{'role':role,'active':user.is_active,'superuser':False})
        else:data['error']=t['failed']
    data['users']=get_user_model().objects.filter(is_staff=True).prefetch_related('groups').order_by('username')
    return finish_render(request,'ops/staff.html',data)
