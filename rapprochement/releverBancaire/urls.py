from django.urls import path
from .views import ExtraireRelevePDFView
urlpatterns=[
    path("<str:compte_id>",ExtraireRelevePDFView.as_view())
]