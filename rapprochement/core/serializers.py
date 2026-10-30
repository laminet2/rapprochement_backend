from decimal import Decimal

from rest_framework import serializers

from core.models import (
    Rapprochement,
    RegleMatching,
    TransactionBancaireRapprochee,
    TransactionValorixRapprochee,
)


def _montant_sens(obj):
    debit, credit = (obj.debit or 0), (obj.credit or 0)
    if debit > 0 and credit > 0:
        return None, "AMBIGU"
    if debit > 0:
        return debit, "DEBIT"
    if credit > 0:
        return credit, "CREDIT"
    return None, None


class RegleMatchingSerializer(serializers.ModelSerializer):
    type_document_nom = serializers.CharField(source="type_document.nom", read_only=True, default=None)

    class Meta:
        model = RegleMatching
        fields = [
            "id", "type_transaction_valorix", "type_document", "type_document_nom",
            "sens_transaction_document_cible", "fenetre_jours_avant",
            "fenetre_jours_apres", "tolerance_fixe", "tolerance_pourcentage",
            "regroupement_max", "actif", "date_creation",
        ]
        read_only_fields = ["id", "date_creation"]

    def validate(self, attrs):
        instance = self.instance
        type_valorix = attrs.get(
            "type_transaction_valorix", getattr(instance, "type_transaction_valorix", None)
        )
        document = attrs.get("type_document", getattr(instance, "type_document", None))

        doublon = RegleMatching.objects.filter(
            type_transaction_valorix=type_valorix, type_document=document
        )
        if instance:
            doublon = doublon.exclude(pk=instance.pk)
        if doublon.exists():
            raise serializers.ValidationError(
                "Une règle existe déjà pour ce type Valorix et cette contrepartie."
            )

        # Le sens d'un document est celui de sa configuration.
        if document is not None:
            attrs["sens_transaction_document_cible"] = document.sens
        return attrs


def _ligne_contrepartie(lien):
    """Normalise un lien (banque ou document) pour l'affichage."""
    tx = lien.transaction
    montant, sens = _montant_sens(tx)
    base = {
        "id": lien.id,
        "transaction_id": tx.pk,
        "date_transaction": tx.date_transaction,
        "debit": tx.debit,
        "credit": tx.credit,
        "montant": None if montant is None else str(montant),
        "sens": sens,
    }
    if hasattr(tx, "libelle_brut"):  # relevé bancaire
        return {
            **base,
            "libelle": tx.libelle_brut,
            "reference": tx.reference_rapprochement or "",
            "compte": tx.compte.numero_compte,
            "source": tx.compte.banque.nom,
        }
    return {  # document
        **base,
        "libelle": f"Compte {tx.numero_compte}",
        "reference": "",
        "compte": tx.numero_compte,
        "source": tx.type_document.nom,
    }


class LigneValorixSerializer(serializers.ModelSerializer):
    transaction_id = serializers.UUIDField(read_only=True)
    numero_transaction = serializers.CharField(source="transaction.numero_transaction")
    date_transaction = serializers.DateTimeField(source="transaction.date_transaction")
    numero_compte = serializers.CharField(source="transaction.numero_compte")
    nom_complet = serializers.CharField(source="transaction.nomComplet")
    references = serializers.CharField(source="transaction.references")
    types = serializers.CharField(source="transaction.types")
    debit = serializers.DecimalField(source="transaction.debit", max_digits=20, decimal_places=2)
    credit = serializers.DecimalField(source="transaction.credit", max_digits=20, decimal_places=2)
    montant = serializers.SerializerMethodField()
    sens = serializers.SerializerMethodField()

    class Meta:
        model = TransactionValorixRapprochee
        fields = [
            "id", "transaction_id", "numero_transaction", "date_transaction",
            "numero_compte", "nom_complet", "references", "types", "debit",
            "credit", "montant", "sens",
        ]

    def get_montant(self, obj):
        m, _ = _montant_sens(obj.transaction)
        return None if m is None else str(m)

    def get_sens(self, obj):
        return _montant_sens(obj.transaction)[1]


def _type_depuis_comptes(nb_b, nb_v):
    if nb_b == 1 and nb_v == 1:
        return "1-1"
    if nb_b == 1:
        return "1-N"
    if nb_v == 1:
        return "N-1"
    return "N-M"


class RapprochementSerializer(serializers.ModelSerializer):
    contrepartie = serializers.SerializerMethodField()
    transactions_valorix = LigneValorixSerializer(many=True, read_only=True)
    source_contrepartie = serializers.SerializerMethodField()
    nombre_contrepartie = serializers.SerializerMethodField()
    nombre_valorix = serializers.SerializerMethodField()
    type_rapprochement = serializers.SerializerMethodField()
    total_contrepartie = serializers.SerializerMethodField()
    total_valorix = serializers.SerializerMethodField()
    en_conflit = serializers.SerializerMethodField()
    bloquee = serializers.SerializerMethodField()

    class Meta:
        model = Rapprochement
        fields = [
            "id", "statut_validation", "resultat", "origine",
            "type_rapprochement", "score_correspondance", "score_details",
            "ecart_montant", "total_contrepartie", "total_valorix",
            "nombre_contrepartie", "nombre_valorix", "source_contrepartie",
            "regle_snapshot", "en_conflit", "bloquee", "commentaire",
            "cree_le", "valide_le", "contrepartie", "transactions_valorix",
        ]

    def _liens(self, obj):
        return list(obj.transactions_bancaires.all()) + list(obj.lignes_document.all())

    def get_contrepartie(self, obj):
        return [_ligne_contrepartie(l) for l in self._liens(obj)]

    def get_source_contrepartie(self, obj):
        if obj.type_document_id:
            return {"type": "DOCUMENT", "type_document": obj.type_document_id,
                    "nom": obj.type_document.nom}
        return {"type": "BANQUE", "type_document": None, "nom": "Banque"}

    def get_nombre_contrepartie(self, obj):
        return len(self._liens(obj))

    def get_nombre_valorix(self, obj):
        return len(obj.transactions_valorix.all())

    def get_type_rapprochement(self, obj):
        return _type_depuis_comptes(self.get_nombre_contrepartie(obj), self.get_nombre_valorix(obj))

    def _total(self, liens):
        return str(sum((_montant_sens(l.transaction)[0] or Decimal(0) for l in liens), Decimal(0)))

    def get_total_contrepartie(self, obj):
        return self._total(self._liens(obj))

    def get_total_valorix(self, obj):
        return self._total(obj.transactions_valorix.all())

    def get_en_conflit(self, obj):
        """Une autre proposition en attente utilise l'une de ces transactions."""
        return bool(
            getattr(obj, "conflit_banque", False)
            or getattr(obj, "conflit_document", False)
            or getattr(obj, "conflit_valorix", False)
        ) and obj.statut_validation == "PROPOSE"

    def get_bloquee(self, obj):
        """Une transaction est déjà rapprochée ailleurs : validation impossible."""
        return bool(
            getattr(obj, "bloquee_banque", False)
            or getattr(obj, "bloquee_document", False)
            or getattr(obj, "bloquee_valorix", False)
        ) and obj.statut_validation == "PROPOSE"


class MotifSerializer(serializers.Serializer):
    motif = serializers.CharField(allow_blank=False)


class GenerationSerializer(serializers.Serializer):
    lot_valorix = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    lot_banque = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    lot_document = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    types = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    inclure_regroupements = serializers.BooleanField(required=False, default=True)


class DecisionGroupeeSerializer(serializers.Serializer):
    ids_rejetes = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    motif_rejet = serializers.CharField(required=False, allow_blank=True, default="")
    ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_null=True, default=None
    )
    lot_valorix = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    lot_banque = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    lot_document = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    valider_le_reste = serializers.BooleanField(required=False, default=True)


class SelectionManuelleSerializer(serializers.Serializer):
    """Lignes Valorix + des lignes bancaires OU des lignes d'un type de document."""

    transactions_valorix = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )
    transactions_bancaires = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    type_document = serializers.IntegerField(required=False, allow_null=True, default=None)
    lignes_document = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )

    def validate(self, attrs):
        if attrs["type_document"] is None:
            if not attrs["transactions_bancaires"] or attrs["lignes_document"]:
                raise serializers.ValidationError(
                    "Sélectionnez des transactions bancaires, ou un type de document "
                    "avec ses lignes."
                )
            attrs["ids_contrepartie"] = attrs["transactions_bancaires"]
        else:
            if not attrs["lignes_document"] or attrs["transactions_bancaires"]:
                raise serializers.ValidationError(
                    "Avec un type de document, indiquez ses lignes (lignes_document) "
                    "et aucune transaction bancaire."
                )
            attrs["ids_contrepartie"] = attrs["lignes_document"]
        return attrs


class RapprochementManuelSerializer(SelectionManuelleSerializer):
    motif = serializers.CharField(required=False, allow_blank=True, default="")
    forcer = serializers.BooleanField(required=False, default=False)


class SuppressionTransactionsSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=["banque", "valorix", "document"])
    ids = serializers.ListField(child=serializers.CharField(), allow_empty=False)
