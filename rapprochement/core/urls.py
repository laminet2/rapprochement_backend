
from django.urls import path

from core.views import (
    RapprochementListeAPIView,
    RapprochementDetailAPIView,
    ValiderRapprochementAPIView,
    RejeterRapprochementAPIView,
    AnnulerRapprochementAPIView,
)

app_name = "core"

urlpatterns = [
    path(
        "rapprochements/",
        RapprochementListeAPIView.as_view(),
        name="rapprochement-liste",
    ),
    path(
        "rapprochements/<uuid:pk>/",
        RapprochementDetailAPIView.as_view(),
        name="rapprochement-detail",
    ),
    path(
        "rapprochements/<uuid:pk>/valider/",
        ValiderRapprochementAPIView.as_view(),
        name="rapprochement-valider",
    ),
    path(
        "rapprochements/<uuid:pk>/rejeter/",
        RejeterRapprochementAPIView.as_view(),
        name="rapprochement-rejeter",
    ),
    path(
        "rapprochements/<uuid:pk>/annuler/",
        AnnulerRapprochementAPIView.as_view(),
        name="rapprochement-annuler",
    ),
]
