from django.urls import path
from .views import ExtraireRelevePDFView,ImportTransactionsJSONView
urlpatterns=[
    path("save/",ImportTransactionsJSONView.as_view()),
    path("compte/<int:compte_id>/",ExtraireRelevePDFView.as_view())
    
]