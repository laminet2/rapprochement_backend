from django.urls import path
from .views import ImportValorixView,ImportValorixJSONView,ChangerStatutRapprochementValorixView,TransactionListView

urlpatterns = [
    path('',ImportValorixView.as_view()),
    path('save/',ImportValorixJSONView.as_view()),
    path(
        "transactions/<uuid:pk>/statut-rapprochement/",
        ChangerStatutRapprochementValorixView.as_view(),
        name="valorix-changer-statut-rapprochement",
    ),
    path(
        "transactions/",
        TransactionListView.as_view(),
        name="valorix-transactions",
    ),
    path(
    "transactions/<uuid:pk>/statut-rapprochement/",
    ChangerStatutRapprochementValorixView.as_view(),
    name="valorix-changer-statut",
),
]
