from django.db import models


class TypeTransactionCaisse(models.TextChoices):
    DEPOT_CHEQUE = "DEPOT_CHEQUE", "Dépôt chèques"
    RETRAIT_CHEQUE = "RETRAIT_CHEQUE", "Retrait chèques"
    DEPOT_ESPECES = "DEPOT_ESPECES", "Dépôt espèces"
    RETRAIT_ESPECES = "RETRAIT_ESPECES", "Retrait espèces"
    TRANSFERT = "TRANSFERT", "Transferts"
    DEPOT_VIREMENTS = "DEPOT_VIREMENTS", "Dépôt/Virements"
    RETRAIT_VIREMENTS = "RETRAIT_VIREMENTS", "Retrait/Virements"
    AUTRE = "AUTRE", "Autre"


class StatutRapprochement(models.TextChoices):
    RAPPROCHE = "RAPPROCHE", "Rapproché"
    ECART_MONTANT = "ECART_MONTANT", "Écart de montant"
    ABSENT_RELEVE = "ABSENT_RELEVE", "Absent du relevé"
    ANOMALIE = "ANOMALIE", "Anomalie"
    EXCLUDED = "EXCLUDED", "Exclu"


class TransactionBanque(models.TextChoices):
    VIREMENTS = "VIREMENTS", "Virements"
