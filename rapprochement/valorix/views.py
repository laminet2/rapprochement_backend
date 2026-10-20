import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, date

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .models import TypeTransactionCaisse

from .models import TransactionValorix
from .serializers import ImportValorixSerializer,TransactionValorixSerializer


class ImportValorixView(generics.GenericAPIView):
    serializer_class = ImportValorixSerializer
    parser_classes = [MultiPartParser, FormParser]

    # Excel category -> stable value stored in the database.
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
    MAX_ERRORS = 100

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fichier = serializer.validated_data["fichier"]
        save = request.data.get("save")

        try:
            fichier.seek(0)
            workbook = load_workbook(fichier, read_only=True, data_only=True)
        except Exception:
            return Response(
                {"detail": "Le fichier Excel est invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            feuille = workbook.active
            lignes = feuille.iter_rows(min_row=8, values_only=True)
            entetes = next(lignes, None)
            if not entetes:
                return Response(
                    {"detail": "Aucun en-tête trouvé."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            index = {
                "numero_transaction": 1,
                "date_transaction": 6,
                "numero_compte": 8,
                "nomComplet": 9,
                "debit": 11,
                "credit": 12,
                "references": 13,
            }
            last_column = max(index.values())
            type_courant = None
            transactions = []
            erreurs = []

            for numero_ligne, ligne in enumerate(lignes, start=9):
                if len(ligne) <= last_column:
                    erreurs.append({
                        "ligne": numero_ligne,
                        "erreur": "La ligne ne contient pas toutes les colonnes attendues.",
                    })
                    if len(erreurs) >= self.MAX_ERRORS:
                        break
                    continue

                numero = ligne[index["numero_transaction"]]
                if isinstance(numero, str) and numero.strip() in self.CATEGORIES:
                    type_courant = self.CATEGORIES[numero.strip()]
                    continue

                if not isinstance(numero, (int, float)):
                    continue

                try:
                    if type_courant is None:
                        raise ValueError("Type de transaction non reconnu.")

                    date_transaction = ligne[index["date_transaction"]]

                    if isinstance(date_transaction, datetime):
                        # Déjà un datetime, rien à faire
                        pass
                    elif isinstance(date_transaction, date):
                        # Si c'est un objet date simple (sans heure)
                        date_transaction = datetime.combine(date_transaction, datetime.min.time())
                    elif isinstance(date_transaction, str):
                        # Si c'est une chaîne au format "04/05/2026 09:33:27" (ou juste "04/05/2026")
                        date_str = date_transaction.strip()
                        parsed_date = None
                        
                        # On essaie d'abord avec l'heure, puis sans l'heure par sécurité
                        formats = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y")
                        for fmt in formats:
                            try:
                                parsed_date = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                                
                        if parsed_date:
                            date_transaction = parsed_date
                        else:
                            raise ValueError(f"Format de date invalide : {date_str}")
                    else:
                        raise ValueError("Date de transaction invalide.")

                    # Application du fuseau horaire si nécessaire
                    if timezone.is_naive(date_transaction):
                        date_transaction = timezone.make_aware(
                            date_transaction,
                            timezone.get_current_timezone(),
                        )

                    def convertir_montant(valeur):
                        if valeur is None or valeur == "":
                            return None
                        if isinstance(valeur, str):
                            valeur = valeur.replace("\xa0", "").replace(" ", "")
                            if "," in valeur and "." not in valeur:
                                valeur = valeur.replace(",", ".")
                        return Decimal(str(valeur))

                    transactions.append(
                        TransactionValorix(
                            id=uuid.uuid4(),
                            numero_transaction=str(int(numero)),
                            date_transaction=date_transaction,
                            numero_compte=str(ligne[index["numero_compte"]] or "").strip(),
                            nomComplet=str(ligne[index["nomComplet"]] or "").strip(),
                            debit=convertir_montant(ligne[index["debit"]]),
                            credit=convertir_montant(ligne[index["credit"]]),
                            references=str(ligne[index["references"]] or "").strip(),
                            types=type_courant,
                        )
                    )
                except (ValueError, TypeError, InvalidOperation, IndexError) as erreur:
                    erreurs.append({"ligne": numero_ligne, "erreur": str(erreur)})
                    if len(erreurs) >= self.MAX_ERRORS:
                        break

            if erreurs:
                return Response(
                    {
                        "detail": "Importation annulée : des erreurs ont été détectées.",
                        "erreurs": erreurs,
                        "erreurs_tronquees": len(erreurs) >= self.MAX_ERRORS,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            if save:
                #TODO: ajouter les transactions au status non matcher a la table valorix late
                with transaction.atomic():
                    TransactionValorix.objects.bulk_create(transactions, batch_size=500)

            serializer = TransactionValorixSerializer(transactions, many=True)
            return Response(
                {
                    "detail": "Importation réussie.",
                    "nombre_transactions": len(transactions),
                    "data":serializer.data },
                status=status.HTTP_201_CREATED
                )
        finally:
            workbook.close()

class TransactionListView(generics.ListAPIView):
    queryset = TransactionValorix.objects.all().order_by('-date_transaction')
    serializer_class = TransactionValorixSerializer