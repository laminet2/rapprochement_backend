from rest_framework import serializers

from .models import TransactionValorix

class TransactionValorixSerializer(serializers.ModelSerializer):
    class Meta:
        model=TransactionValorix
        fields="__all__"


class ImportValorixSerializer(serializers.Serializer):
    fichier = serializers.FileField()

    def validate_fichier(self, fichier):
        if not fichier.name.lower().endswith(".xlsx"):
            raise serializers.ValidationError(
                "Seuls les fichiers excels sont acceptés."
            )
        return fichier    

class TransactionValorixJSONSerializer(serializers.Serializer):
    
    numero_transaction = serializers.CharField(max_length=255)
    date_transaction = serializers.DateTimeField()
    numero_compte = serializers.CharField(
        max_length=255,
        allow_blank=True,
        required=False,
        default="",
    )
    nomComplet = serializers.CharField(
        max_length=255,
        allow_blank=True,
        required=False,
        default="",
    )
    debit = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        required=False,
        allow_null=True,
        default=None,
    )
    credit = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        required=False,
        allow_null=True,
        default=None,
    )
    references = serializers.CharField(
        allow_blank=True,
        required=False,
        default="",
    )
    statut_rapprochement=serializers.BooleanField()
    
    types = serializers.ChoiceField(
    choices=TransactionValorix._meta.get_field("types").choices
    )