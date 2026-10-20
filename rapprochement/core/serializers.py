
from rest_framework import serializers

from core.models import (
    Rapprochement,
    TransactionBancaireRapprochee,
    TransactionValorixRapprochee,
)


class TransactionBancaireRapprocheeSerializer(
    serializers.ModelSerializer
):
    date_transaction = serializers.DateField(
        source="transaction.date_transaction",
        read_only=True,
    )
    reference = serializers.CharField(
        source="transaction.reference_rapprochement",
        read_only=True,
        allow_null=True,
    )
    libelle = serializers.CharField(
        source="transaction.libelle_brut",
        read_only=True,
    )
    debit = serializers.DecimalField(
        source="transaction.debit",
        max_digits=18,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    credit = serializers.DecimalField(
        source="transaction.credit",
        max_digits=18,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    banque = serializers.CharField(
        source="transaction.compte.banque.nom",
        read_only=True,
    )

    class Meta:
        model = TransactionBancaireRapprochee
        fields = [
            "id",
            "date_transaction",
            "reference",
            "libelle",
            "debit",
            "credit",
            "banque",
        ]


class TransactionValorixRapprocheeSerializer(
    serializers.ModelSerializer
):
    date_transaction = serializers.DateTimeField(
        source="transaction.date_transaction",
        read_only=True,
    )
    numero_transaction = serializers.CharField(
        source="transaction.numero_transaction",
        read_only=True,
    )
    numero_compte = serializers.CharField(
        source="transaction.numero_compte",
        read_only=True,
    )
    nom_complet = serializers.CharField(
        source="transaction.nomComplet",
        read_only=True,
    )
    debit = serializers.DecimalField(
        source="transaction.debit",
        max_digits=18,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    credit = serializers.DecimalField(
        source="transaction.credit",
        max_digits=18,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    type_transaction = serializers.CharField(
        source="transaction.types",
        read_only=True,
    )
    references = serializers.CharField(
        source="transaction.references",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = TransactionValorixRapprochee
        fields = [
            "id",
            "date_transaction",
            "numero_transaction",
            "numero_compte",
            "nom_complet",
            "debit",
            "credit",
            "type_transaction",
            "references",
        ]


class RapprochementSerializer(serializers.ModelSerializer):
    transactions_bancaires = (
        TransactionBancaireRapprocheeSerializer(
            many=True,
            read_only=True,
        )
    )
    transactions_valorix = (
        TransactionValorixRapprocheeSerializer(
            many=True,
            read_only=True,
        )
    )
    regle_nom = serializers.CharField(
        source="regle.nom",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Rapprochement
        fields = [
            "id",
            "statut_validation",
            "resultat",
            "score_correspondance",
            "ecart_montant",
            "score_details",
            "regle",
            "regle_nom",
            "commentaire",
            "cree_le",
            "valide_le",
            "valide_par",
            "transactions_bancaires",
            "transactions_valorix",
        ]
        read_only_fields = fields


class MotifActionSerializer(serializers.Serializer):
    motif = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=2000,
    )
