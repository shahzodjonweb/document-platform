from django.urls import path
from django.views.generic.base import RedirectView
from . import views, integration_views, commerce_views, staff_views, actions, provider_usage, generation_views, post_views

urlpatterns = [path('users/<uuid:pk>/plan',actions.set_plan),path('files/<uuid:pk>/download',actions.download_file),path('plans/<str:plan_id>',actions.save_plan),path('jobs/<uuid:pk>/cancel',actions.cancel),path('staff',staff_views.staff),path('bot-simulator',RedirectView.as_view(url='http://127.0.0.1:3000/en/app/bot',permanent=False)),path('payments',commerce_views.finance_page),path('analytics/revenue',commerce_views.finance_page,{'section':'analytics/revenue'}),path('payments/<uuid:pk>',commerce_views.payment_detail),path('payments/manual/<uuid:pk>',commerce_views.manual_payment_detail),path('payments/manual/<uuid:pk>/receipt',commerce_views.manual_payment_receipt),path('integrations',integration_views.integrations),
    path('analytics/ai-usage', provider_usage.usage_page),
    path('generations', generation_views.generations),
    path('generations/<uuid:pk>', generation_views.generation_detail),
    path('generations/<uuid:pk>/file', generation_views.generation_file),
    path('generations/<uuid:pk>/pages/<int:page>', generation_views.generation_page),
    path('posts', post_views.post_list),
    path('posts/new', post_views.post_compose),
    path('posts/<uuid:pk>', post_views.post_detail),
    path('posts/<uuid:pk>/send', post_views.post_send),
    path('posts/<uuid:pk>/test', post_views.post_test),
    path('posts/<uuid:pk>/stop', post_views.post_stop),
    path('posts/<uuid:pk>/discard', post_views.post_discard),
    path('posts/<uuid:pk>/image', post_views.post_image),
    path('',views.page), path('login',views.login),path('dev-login',views.development_login),path('logout',views.logout),
    path('users/<uuid:pk>',views.user_detail),path('jobs/<uuid:pk>',views.job_detail),
    path('api/v1/summary',views.api_summary),path('export/<str:kind>',views.export),
    *[path(section,views.page,{'section':section},name='ops-'+section.replace('/','-')) for section in views.PAGE_ROLES],
]
