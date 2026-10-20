
import logging
import os
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from django.db import transaction

from rest_framework import status, viewsets
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from .models import (
    TransactionBancaire,
    CompteBancaire,
    TypeTransactionBancaire,
)
from .serializers import TransactionBancaireSerializer
from pathlib import Path

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================
# SCHÉMAS PYDANTIC
# ============================================================

type_choices_dict = {
    choice[0]: choice[0]
    for choice in TypeTransactionBancaire.choices
}

TypeTransactionEnum = Enum(
    "TypeTransactionEnum",
    type_choices_dict,
)


class LigneTransactionSchema(BaseModel):
    date_transaction: str = Field(
        description="Date de transaction au format YYYY-MM-DD."
    )

    date_valeur: Optional[str] = Field(
        default=None,
        description="Date de valeur au format YYYY-MM-DD, si présente."
    )

    numero_compte_ou_cheque: Optional[str] = Field(
        default=None,
        description="Identifiant à extraire du relevé bancaire : "
            "1. Pour une opération par chèque, extraire le numéro du chèque. "
            "2. Pour les autres opérations, extraire le numéro de compte CGF lorsqu'il est explicitement présent dans le libellé. "
            "Ce numéro est constitué exclusivement de chiffres, généralement au nombre de 7 à 10, "
            "avec des terminaisons très fréquentes en 10XX ou 90XX (ex: ...1066, ...1036, ...1022, ...1008, ...9018, ...9064, etc.). "
            "Si l'identifiant attendu est absent, retourner null. "
            "Ne jamais inventer, déduire ou reconstruire un numéro."
    )

    libelle_brut: str = Field(
        description="Libellé complet et exact de l'opération."
    )

    debit: Optional[float] = Field(
        default=None,
        description="Montant du débit, positif, sinon null."
    )

    credit: Optional[float] = Field(
        default=None,
        description="Montant du crédit, positif, sinon null."
    )

    solde_apres_operation: Optional[float] = Field(
        default=None,
        description="Solde après opération, si disponible."
    )

    type_transaction: TypeTransactionEnum = Field(
        default=TypeTransactionEnum.AUTRE,
        description="Type de transaction parmi les choix autorisés."
    )


class ReleveBancaireSchema(BaseModel):
    transactions: List[LigneTransactionSchema] = Field(
        description="Toutes les opérations du relevé bancaire."
    )


# ============================================================
# VIEWSET CRUD
# ============================================================

class TransactionBancaireViewSet(viewsets.ModelViewSet):
    queryset = TransactionBancaire.objects.all().order_by(
        "-date_transaction"
    )
    serializer_class = TransactionBancaireSerializer

    filterset_fields = [
        "status",
        "type_transaction",
        "compte",
    ]

    search_fields = [
        "libelle_brut",
        "reference_bancaire",
    ]


# ============================================================
# EXTRACTION DU PDF
# ============================================================

class ExtraireRelevePDFView(APIView):
    """
    Reçoit un PDF, l'envoie à OpenAI Files API,
    puis demande à LangChain d'extraire les transactions.

    Le PDF n'est pas parsé localement et aucun encodage
    base64 manuel n'est effectué dans cette vue.
    """

    parser_classes = [MultiPartParser, FormParser]

    MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB


    prompt_path = Path(__file__).resolve().parent / "prompt.txt"

    with open(prompt_path, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()
        

    def post(self, request, compte_id, format=None):

        # --------------------------------------------------------
        # 1. Vérifier le compte
        # --------------------------------------------------------

        try:
            compte = CompteBancaire.objects.get(id=compte_id)
        except CompteBancaire.DoesNotExist:
            return Response(
                {"error": "Compte bancaire introuvable."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # --------------------------------------------------------
        # 2. Récupérer le fichier
        # --------------------------------------------------------

        pdf_file = request.FILES.get("file")

        if not pdf_file:
            return Response(
                {"error": "Fichier PDF manquant (clé 'file')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not pdf_file.name.lower().endswith(".pdf"):
            return Response(
                {"error": "Le fichier doit avoir l'extension .pdf."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if pdf_file.size == 0:
            return Response(
                {"error": "Le fichier PDF est vide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if pdf_file.size > self.MAX_PDF_SIZE:
            return Response(
                {"error": "Le PDF dépasse la limite de 50 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file_id = None
        client = None

        try:
            # ----------------------------------------------------
            # 3. Envoyer le fichier binaire à OpenAI
            # ----------------------------------------------------

            client = OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                timeout=120.0,
                max_retries=2,
            )

            pdf_file.seek(0)

            uploaded_file = client.files.create(
                file=(
                    pdf_file.name,
                    pdf_file,
                    "application/pdf",
                ),
                purpose="user_data",
            )

            uploaded_file_id = uploaded_file.id

            # ----------------------------------------------------
            # 4. Configurer LangChain
            # ----------------------------------------------------

            llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                temperature=0,
                use_responses_api=True,
                timeout=120,
                max_retries=2,
            )

            structured_llm = llm.with_structured_output(
                ReleveBancaireSchema,
                method="json_schema",
            )

            # ----------------------------------------------------
            # 5. Construire le message avec l'identifiant du PDF
            # ----------------------------------------------------

            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": (
                                "Analyse ce relevé bancaire PDF. "
                                "Extrais toutes les transactions "
                                "et retourne le résultat structuré."
                            ),
                        },
                        {
                            "type": "file",
                            "file_id": uploaded_file_id,
                        },
                    ]
                ),
            ]

            # ----------------------------------------------------
            # 6. Appeler le modèle
            # ----------------------------------------------------

            resultat: ReleveBancaireSchema = structured_llm.invoke(
                messages
            )

            # ----------------------------------------------------
            # 7. Convertir les résultats en objets Django
            # ----------------------------------------------------

            transactions = []

            for ligne in resultat.transactions:

                date_tx = datetime.strptime(
                    ligne.date_transaction,
                    "%Y-%m-%d",
                ).date()

                date_val = (
                    datetime.strptime(
                        ligne.date_valeur,
                        "%Y-%m-%d",
                    ).date()
                    if ligne.date_valeur
                    else None
                )

                debit = (
                    Decimal(str(ligne.debit))
                    if ligne.debit is not None
                    else None
                )

                credit = (
                    Decimal(str(ligne.credit))
                    if ligne.credit is not None
                    else None
                )

                solde = (
                    Decimal(str(ligne.solde_apres_operation))
                    if ligne.solde_apres_operation is not None
                    else None
                )

                # Contrôle des montants avant création
                if debit is not None and debit < 0:
                    raise ValueError("Un montant de débit est négatif.")

                if credit is not None and credit < 0:
                    raise ValueError("Un montant de crédit est négatif.")

                if debit is not None and credit is not None:
                    raise ValueError(
                        "Une transaction ne peut pas avoir "
                        "simultanément un débit et un crédit."
                    )

                transactions.append(
                    TransactionBancaire(
                        compte=compte,
                        date_transaction=date_tx,
                        date_valeur=date_val,
                        reference_rapprochement=ligne.numero_compte_ou_cheque,
                        libelle_brut=ligne.libelle_brut,
                        debit=debit,
                        credit=credit,
                        solde_apres_operation=solde,
                        type_transaction=ligne.type_transaction.value,
                    )
                )

            # ----------------------------------------------------
            # 8. Sauvegarde optionnelle
            # ----------------------------------------------------

            save_value = request.data.get("save", False)

            should_save = (
                str(save_value).strip().lower()
                in {"true", "1", "yes", "oui"}
            )

            if should_save:
                with transaction.atomic():
                    TransactionBancaire.objects.bulk_create(
                        transactions,
                        batch_size=500,
                    )

            # ----------------------------------------------------
            # 9. Retourner les données
            # ----------------------------------------------------

            serializer = TransactionBancaireSerializer(
                transactions,
                many=True,
            )

            return Response(
                {
                    "message": (
                        f"{len(transactions)} transactions extraites."
                    ),
                    "count": len(transactions),
                    "saved": should_save,
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception:
            logger.exception(
                "Erreur lors de l'extraction du relevé bancaire."
            )

            return Response(
                {
                    "error": (
                        "Une erreur est survenue pendant "
                        "le traitement du relevé bancaire."
                    )
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        finally:
            # ----------------------------------------------------
            # 10. Nettoyage du fichier temporaire côté OpenAI
            # ----------------------------------------------------

            if client is not None and uploaded_file_id is not None:
                try:
                    client.files.delete(uploaded_file_id)
                except Exception:
                    logger.warning(
                        "Impossible de supprimer le fichier OpenAI %s",
                        uploaded_file_id,
                    )
