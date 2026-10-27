
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Rapprochement, StatutValidation, ResultatMatching,RegleMatching
from core.serializers import (
    RapprochementSerializer,
    MotifActionSerializer,
    RegleMatchingSerializer
)
from core.services.validation import (
    valider_rapprochement,
    ValidationRapprochementError,
)
from core.services.actions import (
    rejeter_rapprochement,
    annuler_rapprochement,
    ActionRapprochementError,
)

from core.services.proposition import generer_toutes_les_propositions

from valorix.models import TransactionValorix
from releverBancaire.models import TransactionBancaire

class GenererRapprochementsAPIView(APIView):
    #permission_classes = [IsAuthenticated]

    def post(self, request):
        try:

            regle_data = request.data.get("regle")

            if not regle_data:
                return Response(
                    {"message": "La règle est obligatoire."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            regle = RegleMatching(
             
                type_transaction_valorix=regle_data["type_transaction_valorix"],
                sens_transaction_document_cible=
                    regle_data.get(
                        "sens_transaction_document_cible",
                        "CREDIT"
                    ),
                fenetre_jours_avant=
                    regle_data.get("fenetre_jours_avant", 2),
                fenetre_jours_apres=
                    regle_data.get("fenetre_jours_apres", 2),
                tolerance_fixe=
                    regle_data.get("tolerance_fixe", 0),
                tolerance_pourcentage=
                    regle_data.get("tolerance_pourcentage", 0),
                prendre_valorix_anciennes=
                    regle_data.get("prendre_valorix_anciennes", True),
                prendre_banque_anciennes=
                    regle_data.get("prendre_banque_anciennes", True),
                types_valorix_ignorer=
                    regle_data.get("types_valorix_ignorer", []),
            )

            regle.full_clean()

            bilan = generer_toutes_les_propositions(regle)

            # Les objets Rapprochement ne sont pas directement
            # sérialisables en JSON : on retourne un bilan simple.
            return Response(
                {
                    "message": "Génération des propositions terminée.",
                    "transactions_traitees": bilan["transactions_traitees"],
                    "propositions_creees": bilan["creees"],
                    "propositions_actualisees": bilan["actualisees"],
                    "propositions_ignorees": bilan["ignorees"],
                },
                status=status.HTTP_200_OK,
            )

        except Exception:
            return Response(
                {
                    "message": (
                        "Une erreur est survenue pendant "
                        "la génération des propositions."
                    )
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def erreur_metier_vers_reponse(exc):
    if isinstance(exc, DjangoValidationError):
        detail = exc.messages
    else:
        detail = str(exc)

    return Response(
        {"detail": detail},
        status=status.HTTP_400_BAD_REQUEST,
    )


class RapprochementQuerySetMixin:
    def get_queryset(self):
        return (
            Rapprochement.objects
            .prefetch_related(
                "transactions_bancaires__transaction__compte__banque",
                "transactions_valorix__transaction",
            )
            .order_by("-cree_le")
        )


class RapprochementListeAPIView(
    RapprochementQuerySetMixin,
    generics.ListAPIView,
):
    serializer_class = RapprochementSerializer
    #permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()

        statut = self.request.query_params.get("statut")
        resultat = self.request.query_params.get("resultat")
        recherche = self.request.query_params.get("q", "").strip()

        if statut:
            if statut not in StatutValidation.values:
                raise ValidationError({
                    "statut": "Statut non reconnu."
                })
            queryset = queryset.filter(statut_validation=statut)

        if resultat:
            if resultat not in ResultatMatching.values:
                raise ValidationError({
                    "resultat": "Résultat non reconnu."
                })
            queryset = queryset.filter(resultat=resultat)

        if recherche:
            filtres = Q(commentaire__icontains=recherche)

            try:
                identifiant = UUID(recherche)
                filtres |= Q(id=identifiant)
            except (ValueError, TypeError):
                pass

            queryset = queryset.filter(filtres)

        return queryset


class RapprochementDetailAPIView(
    RapprochementQuerySetMixin,
    generics.RetrieveAPIView,
):
    serializer_class = RapprochementSerializer
    #permission_classes = [IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "pk"


class ValiderRapprochementAPIView(APIView):
    #permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            rapprochement = valider_rapprochement(
                rapprochement_id=pk
            )
        except (
            ValidationRapprochementError,
            DjangoValidationError,
        ) as exc:
            return erreur_metier_vers_reponse(exc)
        except Rapprochement.DoesNotExist:
            return Response(
                {"detail": "Rapprochement introuvable."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            RapprochementSerializer(rapprochement).data,
            status=status.HTTP_200_OK,
        )


class ActionMotifRapprochementAPIView(APIView):
    #permission_classes = [IsAuthenticated]
    action_service = None

    def post(self, request, pk):
        serializer = MotifActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            rapprochement = self.action_service(
                rapprochement_id=pk,
                motif=serializer.validated_data["motif"],
            )
        except ActionRapprochementError as exc:
            return erreur_metier_vers_reponse(exc)
        except Rapprochement.DoesNotExist:
            return Response(
                {"detail": "Rapprochement introuvable."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            RapprochementSerializer(rapprochement).data,
            status=status.HTTP_200_OK,
        )


class RejeterRapprochementAPIView(ActionMotifRapprochementAPIView):
    action_service = staticmethod(rejeter_rapprochement)


class AnnulerRapprochementAPIView(ActionMotifRapprochementAPIView):
    action_service = staticmethod(annuler_rapprochement)




class ValiderTousRapprochementsAPIView(APIView):
    #permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = list(
            Rapprochement.objects
            .filter(statut_validation=StatutValidation.PROPOSE)
            .values_list("id", flat=True)
        )

        valides = 0
        erreurs = []

        for rapprochement_id in ids:
            try:
                valider_rapprochement(
                    rapprochement_id=rapprochement_id
                )
                valides += 1

            except (
                ValidationRapprochementError,
                DjangoValidationError,
                Rapprochement.DoesNotExist,
            ) as exc:
                detail = (
                    exc.messages
                    if isinstance(exc, DjangoValidationError)
                    else str(exc)
                )
                erreurs.append({
                    "id": str(rapprochement_id),
                    "detail": detail,
                })

        return Response(
            {
                "total_a_traiter": len(ids),
                "valides": valides,
                "echecs": len(erreurs),
                "erreurs": erreurs,
            },
            status=status.HTTP_200_OK,
        )
    
class RapprochementStatistiquesAPIView(APIView):
    #permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "transactions_valorix": (
                TransactionValorix.objects.count()
            ),
            "transactions_bancaires": (
                TransactionBancaire.objects.count()
            ),
            "propositions_en_attente": (
                Rapprochement.objects.filter(
                    statut_validation=StatutValidation.PROPOSE
                ).count()
            ),
            "rapprochements_valides": (
                Rapprochement.objects.filter(
                    statut_validation=StatutValidation.VALIDE
                ).count()
            ),
            "rapprochements_rejetes": (
                Rapprochement.objects.filter(
                    statut_validation=StatutValidation.REJETE
                ).count()
            ),
            "rapprochements_annules": (
                Rapprochement.objects.filter(
                    statut_validation=StatutValidation.ANNULE
                ).count()
            ),
        })