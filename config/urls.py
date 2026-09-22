from django.urls import include, path
from apps.core.admin import restricted_admin
urlpatterns = [path('api/v1/', include('apps.core.urls')), path('ops/', include('operations.urls')), path('django-admin/', restricted_admin.urls)]
