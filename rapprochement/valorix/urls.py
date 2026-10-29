from django.urls import include, path
from rest_framework.routers import DefaultRouter

from valorix.views import (
    ImportValorixJSONView,
    ImportValorixView,
    TransactionValorixViewSet,
)

router = DefaultRouter()
router.register("transactions", TransactionValorixViewSet, basename="valorix-transaction")

urlpatterns = [
    # 1. fichier -> lignes à vérifier (rien n'est enregistré)
    path("", ImportValorixView.as_view(), name="valorix-extraire"),
    # 2. lignes vérifiées -> enregistrement dans un lot
    path("save/", ImportValorixJSONView.as_view(), name="valorix-save"),
    path("", include(router.urls)),
]
