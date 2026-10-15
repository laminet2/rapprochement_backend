from rest_framework import serializers
from .models import TransactionBancaire

class TransactionBancaireSerializer(serializers.ModelSerializer):
    
    nom_compte = serializers.CharField(source='compte.numero_compte', read_only=True)

    class Meta:
        model = TransactionBancaire
        fields = "__all__"

        read_only_fields = ['id']