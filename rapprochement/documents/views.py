import logging

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from rest_framework import generics, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from documents.importers import (
    COLONNES_REQUISES,
    enregistrer_import,
    generer_modele,
    lire_document,
    marquer_doublons_lignes,
)
from documents.models import LigneDocument, TypeDocument
from documents.serializers import (
    ExtraireDocumentSerializer,
    ImportDocumentSerializer,
    LigneDocumentSerializer,
    TypeDocumentSerializer,
)
from importation.pdf import ExtractionError

logger = logging.getLogger(__name__)


def _creer_regles(type_document, types_valorix):
    """Crée (si absentes) une règle par type Valorix pour ce document."""
    from core.models import RegleMatching

    for type_valorix in types_valorix:
        RegleMatching.objects.get_or_create(
            type_transaction_valorix=type_valorix,
            type_document=type_document,
            defaults={"sens_transaction_document_cible": type_document.sens},
        )


class TypeDocumentViewSet(viewsets.ModelViewSet):
    """
    Types de document (« Orange Money »…).

    Corps de création : {"nom": "...", "sens": "CREDIT", "types_valorix": ["DEPOT_ESPECES"]}
    — une règle par type Valorix est créée avec des valeurs par défaut,
    ajustables ensuite dans les règles.
    """

    serializer_class = TypeDocumentSerializer
    pagination_class = None

    def get_queryset(self):
        from core.models import StatutValidation

        return TypeDocument.objects.annotate(
            nombre_lignes=Count("lignes", distinct=True),
            lignes_non_rapprochees=Count(
                "lignes", distinct=True,
                filter=~Q(
                    lignes__liens_rapprochement__rapprochement__statut_validation=(
                        StatutValidation.VALIDE
                    )
                ),
            ),
        )

    @transaction.atomic
    def perform_create(self, serializer):
        types_valorix = serializer.validated_data.pop("types_valorix", [])
        instance = serializer.save()
        _creer_regles(instance, types_valorix)

    @transaction.atomic
    def perform_update(self, serializer):
        types_valorix = serializer.validated_data.pop("types_valorix", None)
        ancien_sens = serializer.instance.sens
        instance = serializer.save()
        if instance.sens != ancien_sens:
            if instance.lignes.exists():
                raise ValidationError(
                    {"sens": "Le sens ne peut plus changer : des lignes ont déjà été importées."}
                )
            instance.regles.update(sens_transaction_document_cible=instance.sens)
        if types_valorix:
            _creer_regles(instance, types_valorix)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.lignes.exists():
            return Response(
                {"detail": "Ce type contient des lignes : annulez d'abord les imports correspondants."},
                status=status.HTTP_409_CONFLICT,
            )
        instance.regles.all().delete()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExtraireDocumentView(generics.GenericAPIView):
    """Étape 1 : fichier -> lignes à vérifier. N'enregistre RIEN."""

    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ExtraireDocumentSerializer

    def post(self, request, pk):
        try:
            type_document = TypeDocument.objects.get(pk=pk)
        except TypeDocument.DoesNotExist:
            return Response({"detail": "Type de document introuvable."}, status=404)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fichier = serializer.validated_data["fichier"]

        try:
            lignes = lire_document(fichier)
        except ExtractionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception("Erreur lors de la lecture du document.")
            return Response(
                {"detail": "Erreur inattendue pendant la lecture du fichier."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        marquer_doublons_lignes(lignes, type_document)
        return Response(
            {
                "source": "DOCUMENT",
                "type_document": type_document.id,
                "type_document_nom": type_document.nom,
                "sens": type_document.sens,
                "nom_fichier": fichier.name,
                "nombre_lignes": len(lignes),
                "nombre_erreurs": sum(1 for l in lignes if l["erreurs"]),
                "nombre_doublons": sum(1 for l in lignes if l["doublon_probable"]),
                "data": lignes,
            }
        )


class EnregistrerDocumentView(APIView):
    """
    Étape 2 (bouton « Valider ») : enregistre les lignes vérifiées dans un lot.

    Corps : {"type_document": 1, "nom_fichier": "...", "ignorer_doublons": true,
             "transactions": [{"numero_compte": "...", "date_transaction": "2026-11-02", "montant": "750"}]}
    """

    parser_classes = [JSONParser]

    def post(self, request):
        serializer = ImportDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        if not v["type_document"].actif:
            return Response(
                {"detail": "Ce type de document est désactivé."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lot, creees, ignorees = enregistrer_import(
            v["transactions"], v["type_document"], v["nom_fichier"], v["ignorer_doublons"]
        )
        return Response(
            {
                "message": "Lignes bien enregistrées.",
                "lot": str(lot.id),
                "source": "DOCUMENT",
                "nombre_enregistrees": creees,
                "nombre_ignorees_doublons": ignorees,
            },
            status=status.HTTP_201_CREATED,
        )


class ModeleDocumentView(APIView):
    def get(self, request):
        reponse = HttpResponse(
            generer_modele(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        reponse["Content-Disposition"] = 'attachment; filename="modele_document.xlsx"'
        return reponse


class ColonnesDocumentView(APIView):
    def get(self, request):
        colonnes = list(COLONNES_REQUISES.values())
        return Response(
            {
                "colonnes_obligatoires": colonnes,
                "avertissement": (
                    "Assurez-vous que les colonnes suivantes figurent dans le "
                    "document : " + ", ".join(colonnes) + "."
                ),
                "formats": [".xlsx", ".csv", ".pdf"],
            }
        )


class LigneDocumentViewSet(viewsets.ModelViewSet):
    """Filtres : type_document, lot, q, date_min, date_max, rapprochee, sens."""

    serializer_class = LigneDocumentSerializer

    def get_queryset(self):
        from core.models import StatutValidation

        qs = LigneDocument.objects.select_related("type_document").annotate(
            propositions_en_attente=Count(
                "liens_rapprochement",
                filter=Q(
                    liens_rapprochement__rapprochement__statut_validation=(
                        StatutValidation.PROPOSE
                    )
                ),
                distinct=True,
            )
        )
        p = self.request.query_params
        if p.get("type_document"):
            qs = qs.filter(type_document_id=p["type_document"])
        if p.get("lot"):
            qs = qs.filter(lot_id=p["lot"])
        if p.get("q"):
            qs = qs.filter(numero_compte__icontains=p["q"])
        if p.get("date_min"):
            qs = qs.filter(date_transaction__gte=p["date_min"])
        if p.get("date_max"):
            qs = qs.filter(date_transaction__lte=p["date_max"])
        if p.get("sens") == "DEBIT":
            qs = qs.filter(debit__gt=0)
        elif p.get("sens") == "CREDIT":
            qs = qs.filter(credit__gt=0)

        rapprochee = p.get("rapprochee")
        if rapprochee not in (None, ""):
            valides = Q(
                liens_rapprochement__rapprochement__statut_validation=StatutValidation.VALIDE
            )
            if rapprochee.lower() in ("true", "1", "oui"):
                qs = qs.filter(valides).distinct()
            else:
                qs = qs.exclude(valides)
        return qs.order_by("-date_transaction", "-id")

    def perform_update(self, serializer):
        from core.services.transactions import est_rapprochee

        if est_rapprochee("document", serializer.instance.pk):
            raise ValidationError(
                "Cette ligne est déjà rapprochée : annulez d'abord le rapprochement."
            )
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        from core.services.transactions import supprimer_transactions

        instance = self.get_object()
        resultat = supprimer_transactions("document", [instance.pk])
        if resultat["refusees"]:
            return Response(
                {"detail": resultat["refusees"][0]["raison"]},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
