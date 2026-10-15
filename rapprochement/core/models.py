
import uuid
from django.db import models
from django.db.models import Q


class StatutRapprochement(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon"
    PROPOSE = "PROPOSE", "Proposé"
    VALIDE = "VALIDE", "Validé"
    ANNULE = "ANNULE", "Annulé"


class Rapprochement(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    statut = models.CharField(
        max_length=20,
        choices=StatutRapprochement.choices,
        default=StatutRapprochement.BROUILLON
    )

    date_creation = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(
        null=True,
        blank=True
    )

    commentaire = models.TextField(blank=True)

    def __str__(self):
        return f"Rapprochement {self.id} - {self.statut}"


class TransactionRapprochee(models.Model):
    rapprochement = models.ForeignKey(
        Rapprochement,
        on_delete=models.PROTECT,
        related_name="transactions_bancaires"
    )

    transaction = models.ForeignKey(
        "TransactionBancaire",
        on_delete=models.PROTECT,
        related_name="liens_rapprochement"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transaction"],
                name="transaction_dans_un_seul_rapprochement"
            )
        ]


class OperationValorixRapprochee(models.Model):
    rapprochement = models.ForeignKey(
        Rapprochement,
        on_delete=models.PROTECT,
        related_name="operations_valorix"
    )

    operation = models.ForeignKey(
        "OperationValorix",
        on_delete=models.PROTECT,
        related_name="liens_rapprochement"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operation"],
                name="operation_valorix_dans_un_seul_rapprochement"
            )
        ]
