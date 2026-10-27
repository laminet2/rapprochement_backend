from django.urls import path
from .views import ImportValorixView,ImportValorixJSONView,TransactionListView

urlpatterns = [
    path('',ImportValorixView.as_view()),
    path('save/',ImportValorixJSONView.as_view()),

    path(
        "transactions/",
        TransactionListView.as_view(),
        name="valorix-transactions",
    )
]
