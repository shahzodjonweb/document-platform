from django.conf import settings
from django.contrib import admin
from .models import Account,FileAsset,Job,UsageGrant,UsageLedger,Quote,Artifact,SupportTicket,AnalyticsEvent
class RestrictedAdminSite(admin.AdminSite):
    site_header='PDF Master restricted administration'
    def has_permission(self,request):
        # Production staff authentication lives in /ops with a separate MFA realm.
        return settings.DEBUG and super().has_permission(request) and request.user.is_superuser
restricted_admin=RestrictedAdminSite(name='restricted_admin')
class ReadOnly(admin.ModelAdmin):
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
    def has_delete_permission(self,request,obj=None): return False
for model in (Account,FileAsset,Job,UsageGrant,UsageLedger,Quote,Artifact,SupportTicket,AnalyticsEvent): restricted_admin.register(model,ReadOnly)
