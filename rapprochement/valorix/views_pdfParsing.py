import asyncio
import logging
import os
import uuid

from decimal import Decimal, InvalidOperation

import pdfplumber

from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from .models import TypeTransactionCaisse, TransactionValorix
from .serializers import (
    ImportValorixSerializer,
    TransactionValorixSerializer,
)
from .schemas import ExtractionValorix


logger = logging.getLogger(__name__)


class ImportValorixView(generics.GenericAPIView):
    serializer_class = ImportValorixSerializer
    parser_classes = [MultiPartParser, FormParser]

    # Configuration des performances
    CHUNK_SIZE = 100_000
    MAX_PAGES_PER_CHUNK = 40
    MAX_CONCURRENT_CALLS = 3
    LLM_TIMEOUT = 180

    # Correspondance entre les libellés extraits et les types Django
    CATEGORIES = {
        "Dépôt chèques": TypeTransactionCaisse.DEPOT_CHEQUE,
        "Retrait chèques": TypeTransactionCaisse.RETRAIT_CHEQUE,
        "Others": TypeTransactionCaisse.AUTRE,
        "Dépôt espèces": TypeTransactionCaisse.DEPOT_ESPECES,
        "Retrait espèces": TypeTransactionCaisse.RETRAIT_ESPECES,
        "Transferts": TypeTransactionCaisse.TRANSFERT,
        "Dépôt/Virements": TypeTransactionCaisse.DEPOT_VIREMENTS,
        "Retrait/Virements": TypeTransactionCaisse.RETRAIT_VIREMENTS,
    }

    SYSTEM_PROMPT = """
Tu es un système d'extraction de transactions bancaires à partir
du texte d'un relevé bancaire Valorix.

OBJECTIF :
Extraire uniquement les transactions réellement présentes dans
le texte fourni.

RÈGLES STRICTES :

1. N'invente jamais de transaction ni de valeur.
2. N'ajoute pas de transaction à partir d'un simple total ou solde.
3. Conserve les numéros de transaction, les comptes, les références
   et les noms tels qu'ils apparaissent dans le document.
4. N'attribue pas arbitrairement une date, un montant ou un nom.
5. Si une donnée est absente, utilise une valeur vide ou null
   selon le type du champ demandé par le schéma.
6. Ne déduis pas un montant manquant à partir d'un solde.
7. Les montants débit et crédit doivent être affectés à la bonne
   colonne. N'inverse jamais les deux.
8. Respecte les signes et les séparateurs décimaux du document.
9. Le type de transaction doit correspondre à un libellé reconnu
   dans le document. Ne devine pas un type ambigu.
10. Ignore les titres, en-têtes de colonnes, pieds de page,
    numéros de page et lignes de totaux qui ne représentent pas
    des transactions.
11. Une transaction qui continue sur plusieurs lignes ne doit
    être extraite qu'une seule fois.
12. N'extrais que les transactions du bloc fourni.
13. Ne complète pas les informations d'un bloc à partir de
    connaissances externes.
14. Si une ligne est trop ambiguë pour être interprétée avec
    certitude, ne fabrique pas de données pour la compléter.

Retourne exclusivement les données conformes au schéma structuré.
"""

    # ---------------------------------------------------------
    # Découpage du texte en blocs
    # ---------------------------------------------------------

    @classmethod
    def split_text(cls, pages):
        """
        Regroupe les pages en blocs d'environ 100 000 caractères,
        avec au maximum 40 pages par bloc.

        Les pages exceptionnellement longues sont découpées en
        sous-parties pour respecter autant que possible la limite.
        """

        chunks = []
        current_parts = []
        current_size = 0
        current_pages = 0

        def flush():
            nonlocal current_parts, current_size, current_pages

            if current_parts:
                chunks.append("".join(current_parts))

            current_parts = []
            current_size = 0
            current_pages = 0

        for page_number, page_text in pages:
            page_block = (
                f"\n--- PAGE {page_number} ---\n"
                f"{page_text}\n"
            )

            # Si une page est plus grande que la limite,
            # on la découpe en fragments sans dépasser la limite.
            if len(page_block) > cls.CHUNK_SIZE:
                flush()

                start = 0
                while start < len(page_block):
                    end = min(start + cls.CHUNK_SIZE, len(page_block))

                    # Essaie de couper à la fin d'une ligne
                    # afin de limiter la séparation des transactions.
                    if end < len(page_block):
                        newline_pos = page_block.rfind(
                            "\n", start, end
                        )
                        if newline_pos > start:
                            end = newline_pos + 1

                    chunks.append(page_block[start:end])
                    start = end

                continue

            must_flush = (
                current_parts
                and (
                    current_size + len(page_block) > cls.CHUNK_SIZE
                    or current_pages >= cls.MAX_PAGES_PER_CHUNK
                )
            )

            if must_flush:
                flush()

            current_parts.append(page_block)
            current_size += len(page_block)
            current_pages += 1

        flush()

        return chunks

    # ---------------------------------------------------------
    # Extraction d'un bloc par le LLM
    # ---------------------------------------------------------

    @classmethod
    async def extract_chunk(
        cls,
        structured_llm,
        semaphore,
        index,
        total,
        chunk,
    ):
        messages = [
            SystemMessage(content=cls.SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Bloc {index}/{total} du relevé Valorix.\n"
                    "Extrais les transactions présentes dans ce bloc "
                    "uniquement. Ne crée aucune donnée absente.\n\n"
                    f"{chunk}"
                )
            ),
        ]

        async with semaphore:
            logger.info(
                "Début extraction du bloc %s/%s",
                index,
                total,
            )

            result = await structured_llm.ainvoke(messages)

            logger.info(
                "Fin extraction du bloc %s/%s : %s transaction(s)",
                index,
                total,
                len(result.transactions),
            )

            return result.transactions

    @classmethod
    async def extract_all_chunks(cls, chunks, structured_llm):
        """
        Lance les appels en parallèle, avec une limite de concurrence.
        gather conserve l'ordre des résultats selon l'ordre des tâches.
        """

        semaphore = asyncio.Semaphore(cls.MAX_CONCURRENT_CALLS)

        tasks = [
            cls.extract_chunk(
                structured_llm=structured_llm,
                semaphore=semaphore,
                index=index,
                total=len(chunks),
                chunk=chunk,
            )
            for index, chunk in enumerate(chunks, start=1)
        ]

        results = await asyncio.gather(*tasks)

        return [
            ligne
            for result in results
            for ligne in result
        ]

    # ---------------------------------------------------------
    # Validation et conversion des montants
    # ---------------------------------------------------------

    @staticmethod
    def to_decimal(value, field_name):
        if value is None or value == "":
            return None

        try:
            amount = Decimal(str(value))

            if not amount.is_finite():
                raise InvalidOperation

            return amount

        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(
                f"Montant invalide pour le champ {field_name}."
            )

    @staticmethod
    def parse_save_option(value):
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() in {
                "true",
                "1",
                "yes",
                "oui",
            }

        return bool(value)

    # ---------------------------------------------------------
    # Endpoint d'import
    # ---------------------------------------------------------

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        fichier = serializer.validated_data.get("fichier")
        save = self.parse_save_option(
            serializer.validated_data.get("save", False)
        )

        if not fichier:
            return Response(
                {"detail": "Aucun fichier PDF fourni."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not fichier.name.lower().endswith(".pdf"):
            return Response(
                {"detail": "Le fichier doit être au format PDF."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if fichier.size == 0:
            return Response(
                {"detail": "Le fichier PDF est vide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 1. Extraction locale du texte PDF
        try:
            fichier.seek(0)

            with pdfplumber.open(fichier) as pdf:
                pages = [
                    (page_number, page.extract_text() or "")
                    for page_number, page in enumerate(
                        pdf.pages,
                        start=1,
                    )
                ]

        except Exception:
            logger.exception("Impossible de lire le PDF Valorix.")

            return Response(
                {
                    "detail": (
                        "Impossible de lire le fichier PDF. "
                        "Vérifie que le document est valide et lisible."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        pages = [
            (number, text.strip())
            for number, text in pages
            if text and text.strip()
        ]

        if not pages:
            return Response(
                {
                    "detail": (
                        "Aucun texte exploitable détecté dans le PDF. "
                        "Le document est peut-être scanné et nécessite "
                        "une étape OCR."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Découpage en blocs
        chunks = self.split_text(pages)

        logger.info(
            "PDF Valorix : %s page(s) textuelles, %s bloc(s).",
            len(pages),
            len(chunks),
        )

        # 3. Configuration du LLM
        try:
            llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                temperature=0,
                timeout=self.LLM_TIMEOUT,
                max_retries=2,
            )

            structured_llm = llm.with_structured_output(
                ExtractionValorix,
                method="json_schema",
            )

            # 4. Extraction parallèle des blocs
            lignes_extraites = async_to_sync(
                self.extract_all_chunks
            )(chunks, structured_llm)

        except Exception:
            logger.exception(
                "Erreur pendant l'extraction LLM du PDF Valorix."
            )

            return Response(
                {
                    "detail": (
                        "Une erreur est survenue pendant l'extraction "
                        "des transactions. Vérifie la configuration "
                        "du modèle et réessaie."
                    )
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # 5. Conversion en instances Django
        transactions = []
        erreurs = []

        for index, ligne in enumerate(lignes_extraites, start=1):
            try:
                type_label = (
                    ligne.type_transaction or ""
                ).strip()

                type_transaction = self.CATEGORIES.get(type_label)

                if type_transaction is None:
                    raise ValueError(
                        f"Type de transaction non reconnu : "
                        f"{type_label!r}"
                    )

                date_transaction = ligne.date_transaction

                if date_transaction is None:
                    raise ValueError(
                        "Date de transaction manquante."
                    )

                if timezone.is_naive(date_transaction):
                    date_transaction = timezone.make_aware(
                        date_transaction,
                        timezone.get_current_timezone(),
                    )

                debit = self.to_decimal(ligne.debit, "debit")
                credit = self.to_decimal(ligne.credit, "credit")

                if debit is not None and debit < 0:
                    raise ValueError(
                        "Le montant du débit ne peut pas être négatif."
                    )

                if credit is not None and credit < 0:
                    raise ValueError(
                        "Le montant du crédit ne peut pas être négatif."
                    )

                if debit is not None and credit is not None:
                    raise ValueError(
                        "Une transaction ne peut pas avoir simultanément "
                        "un débit et un crédit renseignés."
                    )

                transactions.append(
                    TransactionValorix(
                        id=uuid.uuid4(),
                        numero_transaction=ligne.numero_transaction,
                        date_transaction=date_transaction,
                        numero_compte=ligne.numero_compte,
                        nomComplet=ligne.nomComplet,
                        debit=debit,
                        credit=credit,
                        references=ligne.references or "",
                        types=type_transaction,
                    )
                )

            except (ValueError, TypeError, InvalidOperation) as exc:
                erreurs.append({
                    "ligne": index,
                    "erreur": str(exc),
                })

        # Par défaut, on évite de sauvegarder un résultat partiel
        # sans que l'appelant en soit informé.
        if erreurs:
            logger.warning(
                "%s transaction(s) rejetée(s) pendant la validation.",
                len(erreurs),
            )

            return Response(
                {
                    "detail": (
                        "Certaines transactions extraites n'ont pas passé "
                        "les validations. Aucune transaction n'a été "
                        "enregistrée."
                    ),
                    "nombre_transactions_extraites": len(
                        lignes_extraites
                    ),
                    "nombre_transactions_valides": len(transactions),
                    "nombre_erreurs": len(erreurs),
                    "erreurs": erreurs,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if not transactions:
            return Response(
                {
                    "detail": (
                        "Aucune transaction n'a été extraite du PDF."
                    ),
                    "nombre_transactions": 0,
                    "saved": False,
                    "data": [],
                },
                status=status.HTTP_200_OK,
            )

        # 6. Sauvegarde atomique facultative
        if save:
            try:
                with transaction.atomic():
                    TransactionValorix.objects.bulk_create(
                        transactions,
                        batch_size=500,
                    )

            except Exception:
                logger.exception(
                    "Erreur lors de la sauvegarde des transactions Valorix."
                )

                return Response(
                    {
                        "detail": (
                            "L'extraction a réussi, mais la sauvegarde "
                            "en base de données a échoué."
                        )
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # 7. Sérialisation de la réponse
        response_serializer = TransactionValorixSerializer(
            transactions,
            many=True,
        )

        return Response(
            {
                "detail": "Extraction réussie.",
                "nombre_transactions": len(transactions),
                "nombre_blocs": len(chunks),
                "saved": save,
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )