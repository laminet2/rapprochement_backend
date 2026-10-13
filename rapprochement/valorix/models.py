from django.db import models
from core.enums import TypeTransactionCaisse,StatutRapprochement

# Create your models here.
class TransactionValorix(models.Model):
    id=models.UUIDField(primary_key=True)
    numero_transaction=models.CharField()
    date_transaction=models.DateTimeField(auto_now=False, auto_now_add=False)
    numero_compte = models.CharField(max_length = 150)
    nomComplet=models.CharField()

    debit = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    credit = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    references = models.CharField(max_length = 150)
    
    types=models.CharField(
        choices=TypeTransactionCaisse.choices
    )
    status=models.CharField(
        choices=StatutRapprochement.choices,
        null=True
    )

    references_rapprochement=models.CharField(null=True)
