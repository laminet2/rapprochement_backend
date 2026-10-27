
import logging
import os
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
import pdfplumber

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from django.db import transaction

from rest_framework import status, viewsets
from rest_framework.parsers import MultiPartParser, FormParser,JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from rest_framework.permissions import IsAuthenticated

from .models import (
    TransactionBancaire,
    CompteBancaire,
    TypeTransactionBancaire,
)
from .serializers import TransactionBancaireSerializer,ImportTransactionsJSONSerializer
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
logger = logging.getLogger(__name__)


class ExtraireRelevePDFView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB

    # 2 à 3 pages entières par bloc = équilibre parfait entre
    # intégrité des données, vitesse et respect des limites de sortie JSON.
    PAGES_PER_CHUNK = 2

    prompt_path = Path(__file__).resolve().parent / "prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()

    @classmethod
    def split_by_exact_pages(cls, pages, max_pages_per_chunk=2):
        """Regroupe des PAGES ENTIÈRES sans jamais couper une ligne."""
        chunks = []
        current_chunk = []

        for page_number, page_text in pages:
            current_chunk.append(f"--- PAGE {page_number} ---\n{page_text}")

            if len(current_chunk) == max_pages_per_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks

    def process_chunk(self, structured_llm, index, total_chunks, chunk_text):
        """Traite un groupe de pages entières en un seul appel LLM."""
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Bloc {index}/{total_chunks} du relevé bancaire (Pages entières).\n"
                    "Extrais toutes les transactions présentes dans ce bloc.\n\n"
                    f"{chunk_text}"
                )
            ),
        ]
        result = structured_llm.invoke(messages)
        return result.transactions

    def post(self, request, compte_id, format=None):
        # 1. Vérifier le compte
        try:
            compte = CompteBancaire.objects.get(id=compte_id)
        except CompteBancaire.DoesNotExist:
            return Response(
                {"error": "Compte bancaire introuvable."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. Vérifier le fichier
        pdf_file = request.FILES.get("fichier")
        if not pdf_file:
            return Response(
                {"error": "Fichier PDF manquant (clé 'fichier')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not pdf_file.name.lower().endswith(".pdf"):
            return Response(
                {"error": "Le fichier doit avoir l'extension .pdf."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if pdf_file.size == 0 or pdf_file.size > self.MAX_PDF_SIZE:
            return Response(
                {"error": "Fichier PDF invalide ou supérieur à 50 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # 3. Extraction locale page par page
            pdf_file.seek(0)
            with pdfplumber.open(pdf_file) as pdf:
                pages = [
                    (num, page.extract_text() or "")
                    for num, page in enumerate(pdf.pages, start=1)
                ]

            # Conserver uniquement les pages non vides
            pages = [(num, text.strip()) for num, text in pages if text.strip()]

            if not pages:
                return Response(
                    {"error": "Aucun texte détecté dans le PDF (document scanné ?)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 4. Regroupement par PAGES ENTIÈRES
            chunks = self.split_by_exact_pages(pages, max_pages_per_chunk=self.PAGES_PER_CHUNK)

            # 5. Configuration de ChatOpenAI
            llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                temperature=0,
                max_tokens=16384,
                timeout=120,
                max_retries=2,
            )

            structured_llm = llm.with_structured_output(
                ReleveBancaireSchema,
                method="json_schema",
            )

            # 6. Extraction parallélisée des blocs de pages
            lignes_extraites = []
            max_workers = min(6, len(chunks))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(
                        self.process_chunk,
                        structured_llm,
                        idx,
                        len(chunks),
                        chunk,
                    )
                    for idx, chunk in enumerate(chunks, start=1)
                ]
                for future in futures:
                    lignes_extraites.extend(future.result())

            # 7. Conversion en objets Django
            transactions = []
            for ligne in lignes_extraites:
                date_tx = datetime.strptime(
                    ligne.date_transaction, "%Y-%m-%d"
                ).date()

                date_val = (
                    datetime.strptime(ligne.date_valeur, "%Y-%m-%d").date()
                    if ligne.date_valeur
                    else None
                )

                debit = Decimal(str(ligne.debit)) if ligne.debit is not None else None
                credit = Decimal(str(ligne.credit)) if ligne.credit is not None else None
                solde = (
                    Decimal(str(ligne.solde_apres_operation))
                    if ligne.solde_apres_operation is not None
                    else None
                )

                if debit is not None and debit < 0:
                    raise ValueError("Un montant de débit est négatif.")
                if credit is not None and credit < 0:
                    raise ValueError("Un montant de crédit est négatif.")
                if debit is not None and credit is not None:
                    raise ValueError(
                        "Une transaction ne peut pas avoir simultanément un débit et un crédit."
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

            # 8. Sauvegarde
            save_value = request.data.get("save", False)
            should_save = str(save_value).strip().lower() in {"true", "1", "yes", "oui"}

            if should_save:
                with transaction.atomic():
                    TransactionBancaire.objects.bulk_create(
                        transactions, batch_size=500
                    )

            # 9. Réponse JSON
            serializer = TransactionBancaireSerializer(transactions, many=True)
            return Response(
                {
                    "message": f"{len(transactions)} transactions extraites avec succès.",
                    "count": len(transactions),
                    "saved": should_save,
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.exception("Erreur lors de l'extraction du relevé bancaire.")
            return Response(
                {
                    "error": f"Une erreur est survenue pendant le traitement du relevé bancaire: {e}"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class ImportTransactionsJSONView(APIView):
    parser_classes = [JSONParser]

    def post(self, request, *args, **kwargs):

       

        # 2. Accepter un objet JSON contenant "transactions".
        
        donnees = request.data

        if isinstance(donnees, dict):
            donnees = donnees.get("transactions")

        if not isinstance(donnees, list):
            return Response(
                {
                    "detail": (
                        "Le JSON doit être une liste de transactions "
                        "ou un objet contenant la clé 'transactions'."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not donnees:
            return Response(
                {"detail": "Aucune transaction à enregistrer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Valider toutes les transactions avant toute insertion.
        serializer = ImportTransactionsJSONSerializer(
            data=donnees,
            many=True,
        )
        serializer.is_valid(raise_exception=True)

        transactions = []

        # 4. Construire les objets Django.
        for ligne in serializer.validated_data:
            
            

            transactions.append(
                TransactionBancaire(
                    compte=ligne["compte"],
                    date_transaction=ligne["date_transaction"],
                    date_valeur=ligne.get("date_valeur"),
                    reference_rapprochement=(
                        ligne.get("reference_rapprochement")
                    ),
                    libelle_brut=ligne["libelle_brut"],
                    debit=ligne.get("debit"),
                    credit=ligne.get("credit"),
                    solde_apres_operation=ligne.get(
                        "solde_apres_operation"
                    ),
                    type_transaction=ligne.get(
                        "type_transaction",
                        TypeTransactionBancaire.AUTRE,
                    ),
                )
            )

        # 5. Enregistrer toutes les transactions en une opération atomique.
        try:
            with transaction.atomic():
                TransactionBancaire.objects.bulk_create(
                    transactions,
                    batch_size=500,
                )

        except Exception:
            logger.exception(
                "Erreur lors de l'importation JSON du relevé bancaire."
            )
            return Response(
                {
                    "error": (
                        "Impossible d'enregistrer les transactions."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 6. Retourner uniquement un message de confirmation.
        return Response(
            {"message": "Transactions bien enregistrées."},
            status=status.HTTP_201_CREATED,
        )




class CompteBancaireListeAPIView(APIView):
    #permission_classes = [IsAuthenticated]

    def get(self, request):
        comptes = (
            CompteBancaire.objects
            .select_related("banque")
            .order_by("banque__nom", "numero_compte")
        )

        donnees = [
            {
                "id": compte.id,
                "numero_compte": compte.numero_compte,
                "banque": compte.banque.nom,
                "devise": compte.devise,
            }
            for compte in comptes
        ]

        return Response(donnees)