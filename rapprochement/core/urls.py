
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
        "",
        RapprochementListeAPIView.as_view(),
        name="rapprochement-liste",
    ),
    path(
        "<uuid:pk>/",
        RapprochementDetailAPIView.as_view(),
        name="rapprochement-detail",
    ),
    path(
        "<uuid:pk>/valider/",
        ValiderRapprochementAPIView.as_view(),
        name="rapprochement-valider",
    ),
    path(
        "<uuid:pk>/rejeter/",
        RejeterRapprochementAPIView.as_view(),
        name="rapprochement-rejeter",
    ),
    path(
        "<uuid:pk>/annuler/",
        AnnulerRapprochementAPIView.as_view(),
        name="rapprochement-annuler",
    ),
]
