import pdfplumber
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional

from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from .models import TransactionBancaire, CompteBancaire, StatutRapprochement, TypeTransactionBancaire
from .serializers import TransactionBancaireSerializer

from dotenv import load_dotenv

load_dotenv()


# --- SCHÉMAS PYDANTIC  ---

class LigneTransactionSchema(BaseModel):
    date_transaction: str = Field(description="Date de la transaction au format YYYY-MM-DD")
    date_valeur: Optional[str] = Field(default=None, description="Date de valeur au format YYYY-MM-DD si présente")
    reference_bancaire: Optional[str] = Field(default=None, description="Référence du chèque (generalement de 7 chiffres) / numéro de compte (generalement de 10 chiffres) - ces valeurs sont presentes dans le libelle de l'operation")
    libelle_brut: str = Field(description="Le libellé complet et exact de l'opération")
    debit: Optional[float] = Field(default=None, description="Montant du débit s'il y en a un (positif)")
    credit: Optional[float] = Field(default=None, description="Montant du crédit s'il y en a un (positif)")
    solde_apres_operation: Optional[float] = Field(default=None, description="Solde du compte après l'opération")

class ReleveBancaireSchema(BaseModel):
    transactions: List[LigneTransactionSchema]


# ---  VIEWSET DRF POUR LES TRANSACTIONS ---

class TransactionBancaireViewSet(viewsets.ModelViewSet):
    """
    API standard CRUD pour lister, créer, modifier ou supprimer des transactions bancaires.
    """
    queryset = TransactionBancaire.objects.all().order_by('-date_transaction')
    serializer_class = TransactionBancaireSerializer
    filterset_fields = ['status', 'type_transaction', 'compte']
    search_fields = ['libelle_brut', 'reference_bancaire']


# --- 3. VUE DRF POUR L'EXTRACTION IA D'UN PDF DE RELEVÉ ---

class ExtraireRelevePDFView(APIView):
    """
    Endpoint API pour uploader un PDF de relevé bancaire, le faire analyser par LangChain
    et enregistrer automatiquement les transactions rattachées à un compte bancaire.
    """
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, compte_id, format=None):
        #  Vérification du compte bancaire cible
        try:
            compte = CompteBancaire.objects.get(id=compte_id)
        except CompteBancaire.DoesNotExist:
            return Response({"error": "Compte bancaire introuvable."}, status=status.HTTP_404_NOT_FOUND)

        #  Récupération du fichier PDF dans la requête
        pdf_file = request.FILES.get("file")
        if not pdf_file:
            return Response({"error": "Aucun fichier PDF fourni (clé 'file' requise)."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 3. Extraction du texte brut du PDF avec pdfplumber
            texte_pdf = ""
            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    texte_pdf += page.extract_text() or ""

            if not texte_pdf.strip():
                return Response({"error": "Le fichier PDF est vide ou illisible."}, status=status.HTTP_400_BAD_REQUEST)

            # 4. Configuration de LangChain avec Structured Output
            llm = ChatOpenAI(model="gpt-4o", temperature=0)
            structured_llm = llm.with_structured_output(ReleveBancaireSchema)
            print(texte_pdf)
            prompt = ChatPromptTemplate.from_messages([
                ("system", "Tu es un assistant expert en comptabilité bancaire. Ton rôle est d'analyser le texte brut d'un relevé bancaire et d'extraire fidèlement chaque ligne de transaction financière sous forme de structure de données précise."),
                ("human", "Voici le texte brut du relevé bancaire :\n\n{texte_brut}")
            ])
            
            chain = prompt | structured_llm
            resultat_structure: ReleveBancaireSchema = chain.invoke({"texte_brut": texte_pdf})

            # 5. Enregistrement en base de données
            transactions = []
            for t in resultat_structure.transactions:
                date_tx = datetime.strptime(t.date_transaction, "%Y-%m-%d").date()
                date_val = datetime.strptime(t.date_valeur, "%Y-%m-%d").date() if t.date_valeur else None

                debit_dec = Decimal(str(t.debit)) if t.debit is not None else None
                credit_dec = Decimal(str(t.credit)) if t.credit is not None else None
                solde_dec = Decimal(str(t.solde_apres_operation)) if t.solde_apres_operation is not None else None

                transaction = TransactionBancaire(
                    compte=compte,
                    date_transaction=date_tx,
                    date_valeur=date_val,
                    reference_bancaire=t.reference_bancaire,
                    libelle_brut=t.libelle_brut,
                    debit=debit_dec,
                    credit=credit_dec,
                    solde_apres_operation=solde_dec,
                    type_transaction=TypeTransactionBancaire.AUTRE
                )
                transactions.append(transaction)

            save = request.data.get("save")
            if save:
                with transaction.atomic():
                    TransactionBancaire.objects.bulk_create(transactions, batch_size=500)
            # 6. Sérialisation et retour de la réponse
            serializer = TransactionBancaireSerializer(transactions, many=True)
            return Response({
                "message": f"{len(transactions)} transactions extraites et enregistrées avec succès.",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": f"Erreur lors du traitement IA : {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)