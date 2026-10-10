from django.urls import path
from . import views
retry_urls=[path('generation/jobs/<uuid:pk>/retry-quote',views.retry_quote)]
urlpatterns=[path('studio/config',views.config),path('generation/drafts',views.drafts),path('generation/drafts/<uuid:pk>',views.draft_detail),path('generation/drafts/<uuid:pk>/outline',views.outline),path('generation/drafts/<uuid:pk>/quote',views.draft_quote),path('generation/drafts/<uuid:pk>/setup',views.draft_setup),path('studio/deck-designs',views.deck_designs),path('studio/deck-designs/<str:design>.png',views.deck_design_preview),path('generation/drafts/<uuid:pk>/generate',views.generate),path('education/projects',views.projects),path('education/projects/<uuid:pk>',views.project_detail),path('education/projects/<uuid:pk>/practice',views.practice),path('shares',views.shares),path('shares/<uuid:pk>',views.share_detail),path('shared/<str:token>',views.shared),path('editor/documents',views.editors),path('editor/documents/<uuid:pk>',views.editor_detail),path('editor/documents/<uuid:pk>/quote',views.editor_quote),path('workflows/<uuid:pk>/quote',views.workflow_quote),path('workflows/<uuid:pk>/run',views.workflow_run)]
for route,kind in [('workflows','workflow'),('templates','template'),('editor/form-templates','form')]:
    urlpatterns.extend([path(route,views.definitions,{'kind':kind}),path(route+'/<uuid:pk>',views.definition_detail,{'kind':kind})])

from .batches import urlpatterns as batch_urls
urlpatterns.extend(batch_urls)
urlpatterns.extend(retry_urls)
