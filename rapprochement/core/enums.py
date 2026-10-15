from django.db import models


class StatutRapprochement(models.TextChoices):
    RAPPROCHE = "RAPPROCHE", "Rapproché"
    ECART_MONTANT = "ECART_MONTANT", "Écart de montant"
    ABSENT_RELEVE = "ABSENT_RELEVE", "Absent du relevé"
    ANOMALIE = "ANOMALIE", "Anomalie"
    EXCLUDED = "EXCLUDED", "Exclu"