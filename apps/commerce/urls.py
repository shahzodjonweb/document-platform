from django.urls import path
from . import views
urlpatterns=[
path('billing/offers',views.offers),path('billing/invoices',views.invoices),path('billing/invoices/<uuid:invoice_id>',views.invoice_detail),path('billing/invoices/<uuid:invoice_id>/sandbox-pay',views.sandbox_pay),
path('billing/subscription',views.subscription),path('billing/subscription/cancel-renewal',views.cancel_renewal),path('billing/subscription/resume-renewal',views.resume_renewal),path('billing/subscription/schedule-plan-change',views.schedule_change),path('billing/subscription/sandbox-renew',views.sandbox_renew),
path('billing/transactions',views.transactions),path('billing/manual',views.manual_payments),path('billing/manual/<uuid:payment_id>',views.manual_payment_detail),path('billing/manual/<uuid:payment_id>/receipt',views.manual_payment_receipt),path('billing/payments/<uuid:payment_id>/sandbox-refund',views.sandbox_refund),
path('referrals',views.referrals),path('artifacts/<uuid:artifact_id>/deliver',views.deliver_artifact),
]
urlpatterns += [path('telegram/local/messages',views.local_telegram)]
