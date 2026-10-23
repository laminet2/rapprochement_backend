from django.urls import path,include
from .views import ExtraireRelevePDFView,ImportTransactionsJSONView,TransactionBancaireViewSet,CompteBancaireListeAPIView
from rest_framework.routers import DefaultRouter



router = DefaultRouter()
router.register(
    "transactions",
    TransactionBancaireViewSet,
    basename="transaction-bancaire",
)

urlpatterns=[
    path("save/",ImportTransactionsJSONView.as_view()),
    path("compte/<int:compte_id>/",ExtraireRelevePDFView.as_view()),
    path("", include(router.urls)),
     path(
        "comptes/",
        CompteBancaireListeAPIView.as_view(),
        name="rbc-comptes",
    ),
    
]