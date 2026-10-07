from django.urls import path
from . import views, auth_views
urlpatterns=[
    path('auth/providers',auth_views.providers),
    path('auth/email/register',auth_views.email_register),path('auth/email/verify',auth_views.email_verify),
    path('auth/email/login',auth_views.email_login),path('auth/email/link',auth_views.email_link),
    path('auth/email/reset',auth_views.email_reset),path('auth/email/reset/confirm',auth_views.email_reset_confirm),
    path('auth/password',auth_views.password_change),
    path('auth/google/start',auth_views.google_start),path('auth/google/callback',auth_views.google_callback),
    path('health',views.health),path('auth/session',views.session),path('auth/dev-login',views.dev_login),path('auth/telegram/miniapp',views.miniapp_login),
    path('auth/browser/challenges',views.challenges),path('auth/browser/challenges/<uuid:challenge_id>',views.challenge_status),path('auth/browser/challenges/<uuid:challenge_id>/exchange',views.challenge_exchange),
    path('me',views.me),path('catalog',views.catalog_view),path('plans',views.plans),path('usage',views.usage),path('channels',views.channels),path('channels/check',views.channels_check),
    path('files/uploads',views.uploads),path('files/<uuid:asset_id>',views.file_detail),path('files/<uuid:asset_id>/download',views.file_download),path('files/<uuid:asset_id>/preview',views.file_preview),
    path('secrets',views.secret_create),path('quotes',views.quotes),path('jobs',views.jobs),path('jobs/<uuid:job_id>',views.job_detail),path('jobs/<uuid:job_id>/cancel',views.job_cancel),
    path('artifacts/<uuid:artifact_id>/download',views.artifact_download),path('artifacts/<uuid:artifact_id>/preview',views.artifact_preview),path('contacts',views.contacts),
    path('billing/invoices',views.billing),path('billing/subscription',views.billing),path('billing/transactions',views.billing),path('webhooks/telegram',views.telegram_webhook),
]
