from django.urls import path
from . import views
urlpatterns=[
path('billing/subscription',views.subscription),path('billing/transactions',views.transactions),
path('billing/manual',views.manual_payments),path('billing/manual/<uuid:payment_id>',views.manual_payment_detail),path('billing/manual/<uuid:payment_id>/receipt',views.manual_payment_receipt),
path('referrals',views.referrals),path('artifacts/<uuid:artifact_id>/deliver',views.deliver_artifact),
]
urlpatterns += [path('telegram/local/messages',views.local_telegram)]
