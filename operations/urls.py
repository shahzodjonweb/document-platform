from django.urls import path
from . import views

urlpatterns = [
    path('',views.page), path('login',views.login),path('dev-login',views.development_login),path('logout',views.logout),
    path('users/<uuid:pk>',views.user_detail),path('jobs/<uuid:pk>',views.job_detail),path('support/<uuid:pk>',views.support_detail),
    path('api/v1/summary',views.api_summary),path('export/<str:kind>',views.export),
    *[path(section,views.page,{'section':section},name='ops-'+section.replace('/','-')) for section in views.PAGE_ROLES],
]
