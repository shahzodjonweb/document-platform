from django.urls import path
from django.views.generic.base import RedirectView
from . import views, integration_views, commerce_views, staff_views, actions

urlpatterns = [path('users/<uuid:pk>/grants',actions.grant),path('jobs/<uuid:pk>/cancel',actions.cancel),path('staff',staff_views.staff),path('bot-simulator',RedirectView.as_view(url='http://127.0.0.1:3000/en/app/bot',permanent=False)),path('payments',commerce_views.finance_page),path('analytics/revenue',commerce_views.finance_page,{'section':'analytics/revenue'}),path('payments/<uuid:pk>',commerce_views.payment_detail),path('integrations',integration_views.integrations),
    path('',views.page), path('login',views.login),path('dev-login',views.development_login),path('logout',views.logout),
    path('users/<uuid:pk>',views.user_detail),path('jobs/<uuid:pk>',views.job_detail),path('support/<uuid:pk>',views.support_detail),
    path('api/v1/summary',views.api_summary),path('export/<str:kind>',views.export),
    *[path(section,views.page,{'section':section},name='ops-'+section.replace('/','-')) for section in views.PAGE_ROLES],
]
