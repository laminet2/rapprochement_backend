from rest_framework import serializers
from .models import TransactionBancaire,TypeTransactionBancaire,CompteBancaire


class TransactionBancaireSerializer(serializers.ModelSerializer):
    
    nom_compte = serializers.CharField(source='compte.numero_compte', read_only=True)

    class Meta:
        model = TransactionBancaire
        fields = "__all__"

        read_only_fields = ['id']


class ImportTransactionsJSONSerializer(serializers.Serializer):
    date_transaction = serializers.DateField(
        input_formats=["%Y-%m-%d"],
    )

    date_valeur = serializers.DateField(
        input_formats=["%Y-%m-%d"],
        required=False,
        allow_null=True,
        default=None,
    )

    reference_rapprochement = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
    )

    libelle_brut = serializers.CharField()

    debit = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        required=False,
        allow_null=True,
        default=None,
    )

    credit = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        required=False,
        allow_null=True,
        default=None,
    )

    solde_apres_operation = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        required=False,
        allow_null=True,
        default=None,
    )
    
    compte= serializers.PrimaryKeyRelatedField(
            queryset=CompteBancaire.objects.all(),
            required=False,
            allow_null=True,
            default=None
    )
    


    type_transaction = serializers.ChoiceField(
        choices=TypeTransactionBancaire.choices,
        required=False,
        default=TypeTransactionBancaire.AUTRE,
    )

    def validate(self, attrs):
        debit = attrs.get("debit")
        credit = attrs.get("credit")

        if debit is not None and debit < 0:
            raise serializers.ValidationError(
                {"debit": "Le débit ne peut pas être négatif."}
            )

        if credit is not None and credit < 0:
            raise serializers.ValidationError(
                {"credit": "Le crédit ne peut pas être négatif."}
            )

        if debit is not None and credit is not None:
            raise serializers.ValidationError(
                "Une transaction ne peut pas avoir "
                "simultanément un débit et un crédit."
            )

        return attrs