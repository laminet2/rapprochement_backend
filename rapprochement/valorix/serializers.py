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
                "Le fichier doit être au format .xlsx."
            )

        return fichier    