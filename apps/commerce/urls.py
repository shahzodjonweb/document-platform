from django.urls import path
from . import views
urlpatterns=[
path('billing/subscription',views.subscription),path('billing/transactions',views.transactions),
path('billing/checkout',views.checkouts),path('billing/renewal',views.renewal),path('billing/cards',views.saved_cards),path('billing/cards/<uuid:card_id>',views.saved_card),path('billing/cards/<uuid:card_id>/charge',views.saved_card_charge),path('billing/checkout/<uuid:checkout_id>',views.checkout_detail),path('webhooks/inpay',views.inpay_webhook),
path('billing/manual',views.manual_payments),path('billing/manual/<uuid:payment_id>',views.manual_payment_detail),path('billing/manual/<uuid:payment_id>/receipt',views.manual_payment_receipt),
path('referrals',views.referrals),path('artifacts/<uuid:artifact_id>/deliver',views.deliver_artifact),
]
urlpatterns += [path('telegram/local/messages',views.local_telegram)]
