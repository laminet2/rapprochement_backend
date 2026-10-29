from django.db import models


class SensDocument(models.TextChoices):
    DEBIT = "DEBIT", "Débit"
    CREDIT = "CREDIT", "Crédit"


class TypeDocument(models.Model):
    """
    Un type de document de contrepartie (ex. « Orange Money », « Wave »).

    Il est créé une fois ; on importe ensuite autant de fichiers que
    nécessaire sous ce type. Le sens (débit/crédit) de ses montants fait
    partie de sa configuration. Valorix reste la référence : les lignes
    d'un document sont rapprochées avec les lignes Valorix, comme celles
    d'un relevé bancaire.
    """

    nom = models.CharField(max_length=100, unique=True)
    sens = models.CharField(
        max_length=10, choices=SensDocument.choices, default=SensDocument.CREDIT
    )
    description = models.CharField(max_length=255, blank=True)
    actif = models.BooleanField(default=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "Type de document"
        verbose_name_plural = "Types de document"

    def __str__(self):
        return self.nom


class LigneDocument(models.Model):
    """Une ligne d'un document : numéro de compte client, date, montant net."""

    type_document = models.ForeignKey(
        TypeDocument, on_delete=models.PROTECT, related_name="lignes"
    )
    lot = models.ForeignKey(
        "importation.LotImport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lignes_document",
    )
    date_transaction = models.DateField(db_index=True)
    numero_compte = models.CharField(max_length=150)
    # Une seule des deux colonnes est renseignée, selon le sens du type.
    debit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    credit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_transaction", "-id"]

    def __str__(self):
        return f"{self.type_document} {self.date_transaction} {self.numero_compte}"
