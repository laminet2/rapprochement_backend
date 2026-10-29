from decimal import Decimal

from rest_framework import serializers

from documents.models import LigneDocument, TypeDocument


class TypeDocumentSerializer(serializers.ModelSerializer):
    nombre_lignes = serializers.IntegerField(read_only=True, default=0)
    lignes_non_rapprochees = serializers.IntegerField(read_only=True, default=0)
    # Types Valorix pour lesquels une règle existe avec ce document.
    types_valorix = serializers.ListField(
        child=serializers.CharField(), required=False
    )

    class Meta:
        model = TypeDocument
        fields = [
            "id", "nom", "sens", "description", "actif", "cree_le",
            "nombre_lignes", "lignes_non_rapprochees", "types_valorix",
        ]
        read_only_fields = ["id", "cree_le"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["types_valorix"] = list(
            instance.regles.values_list("type_transaction_valorix", flat=True)
        )
        return data

    def validate_nom(self, nom):
        return nom.strip()

    def validate_types_valorix(self, valeurs):
        from valorix.models import TypeTransactionCaisse

        valides = {v for v, _ in TypeTransactionCaisse.choices}
        invalides = [v for v in valeurs if v not in valides]
        if invalides:
            raise serializers.ValidationError(
                f"Types Valorix inconnus : {', '.join(invalides)}."
            )
        return list(dict.fromkeys(valeurs))


class LigneDocumentSerializer(serializers.ModelSerializer):
    type_document_nom = serializers.CharField(source="type_document.nom", read_only=True)
    montant = serializers.SerializerMethodField()
    sens = serializers.SerializerMethodField()
    propositions_en_attente = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = LigneDocument
        fields = [
            "id", "type_document", "type_document_nom", "lot", "date_transaction",
            "numero_compte", "debit", "credit", "montant", "sens", "created_at",
            "propositions_en_attente",
        ]
        read_only_fields = ["id", "created_at", "lot", "type_document"]

    def get_montant(self, obj):
        valeur = obj.debit if (obj.debit or 0) > 0 else obj.credit
        return None if valeur is None else str(valeur)

    def get_sens(self, obj):
        if (obj.debit or 0) > 0:
            return "DEBIT"
        if (obj.credit or 0) > 0:
            return "CREDIT"
        return None


class ExtraireDocumentSerializer(serializers.Serializer):
    fichier = serializers.FileField()

    def validate_fichier(self, fichier):
        if not fichier.name.lower().endswith((".xlsx", ".csv", ".pdf")):
            raise serializers.ValidationError("Formats acceptés : .xlsx, .csv ou .pdf.")
        return fichier


class LigneImportDocumentSerializer(serializers.Serializer):
    numero_compte = serializers.CharField(max_length=150)
    date_transaction = serializers.DateField(input_formats=["%Y-%m-%d"])
    montant = serializers.DecimalField(max_digits=18, decimal_places=2)

    def validate_montant(self, valeur):
        if valeur <= Decimal(0):
            raise serializers.ValidationError("Le montant doit être strictement positif.")
        return valeur


class ImportDocumentSerializer(serializers.Serializer):
    type_document = serializers.PrimaryKeyRelatedField(queryset=TypeDocument.objects.all())
    nom_fichier = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    ignorer_doublons = serializers.BooleanField(required=False, default=False)
    transactions = LigneImportDocumentSerializer(many=True, allow_empty=False)
