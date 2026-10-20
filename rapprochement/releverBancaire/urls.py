from django.urls import path
from .views import ExtraireRelevePDFView,ImportTransactionsJSONView
urlpatterns=[
    path("<str:compte_id>",ExtraireRelevePDFView.as_view()),
    path("save/",ImportTransactionsJSONView.as_view()),
]