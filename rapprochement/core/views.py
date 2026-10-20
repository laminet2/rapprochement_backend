
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Rapprochement, StatutValidation, ResultatMatching
from core.serializers import (
    RapprochementSerializer,
    MotifActionSerializer,
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
            .select_related("regle", "valide_par")
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
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "pk"


class ValiderRapprochementAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            rapprochement = valider_rapprochement(
                rapprochement_id=pk,
                utilisateur=request.user,
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
    permission_classes = [IsAuthenticated]
    action_service = None

    def post(self, request, pk):
        serializer = MotifActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            rapprochement = self.action_service(
                rapprochement_id=pk,
                utilisateur=request.user,
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
