from django.urls import include, path
from rest_framework.routers import DefaultRouter

from documents.views import (
    ColonnesDocumentView,
    EnregistrerDocumentView,
    ExtraireDocumentView,
    LigneDocumentViewSet,
    ModeleDocumentView,
    TypeDocumentViewSet,
)

router = DefaultRouter()
router.register("types", TypeDocumentViewSet, basename="type-document")
router.register("lignes", LigneDocumentViewSet, basename="ligne-document")

urlpatterns = [
    # 1. fichier -> lignes à vérifier (rien n'est enregistré)
    path("types/<int:pk>/extraire/", ExtraireDocumentView.as_view(), name="document-extraire"),
    # 2. lignes vérifiées -> enregistrement dans un lot
    path("save/", EnregistrerDocumentView.as_view(), name="document-save"),
    path("modele/", ModeleDocumentView.as_view(), name="document-modele"),
    path("colonnes/", ColonnesDocumentView.as_view(), name="document-colonnes"),
    path("", include(router.urls)),
]
