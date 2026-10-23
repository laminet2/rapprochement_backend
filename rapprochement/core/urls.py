
from django.urls import path

from core.views import (
    RapprochementListeAPIView,
    RapprochementDetailAPIView,
    ValiderRapprochementAPIView,
    RejeterRapprochementAPIView,
    AnnulerRapprochementAPIView,
    GenererRapprochementsAPIView,
    RegleMatchingListeAPIView,
    RegleMatchingDetailAPIView,
    ValiderTousRapprochementsAPIView,
    RapprochementStatistiquesAPIView,

)

app_name = "core"

urlpatterns = [
    path(
        "generer/",
        GenererRapprochementsAPIView.as_view(),
        name="rapprochement-generer",
    ),
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
    path(
    "regles/",
    RegleMatchingListeAPIView.as_view(),
    name="regles-liste",
),
path(
    "regles/<uuid:pk>/",
    RegleMatchingDetailAPIView.as_view(),
    name="regles-detail",
),
path(
    "valider-tout/",
    ValiderTousRapprochementsAPIView.as_view(),
    name="rapprochement-valider-tout",
),
path(
    "statistiques/",
    RapprochementStatistiquesAPIView.as_view(),
    name="rapprochement-statistiques",
),
]
