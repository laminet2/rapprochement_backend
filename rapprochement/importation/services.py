from django.db import transaction
from django.utils import timezone

from core.models import StatutValidation
from core.services.transactions import supprimer_transactions
from documents.models import LigneDocument
from releverBancaire.models import TransactionBancaire
from valorix.models import TransactionValorix


class AnnulationLotError(Exception):
    pass


@transaction.atomic
def annuler_lot(lot):
    """
    Supprime toutes les transactions d'un lot, si aucune n'est déjà
    rapprochée (rapprochement VALIDE). Sinon rien n'est supprimé.
    """
    if lot.annule_le:
        raise AnnulationLotError("Ce lot est déjà annulé.")

    ids_banque = list(TransactionBancaire.objects.filter(lot=lot).values_list("pk", flat=True))
    ids_valorix = list(TransactionValorix.objects.filter(lot=lot).values_list("pk", flat=True))

    ids_document = list(LigneDocument.objects.filter(lot=lot).values_list("pk", flat=True))

    refusees = []
    for source, ids in (("banque", ids_banque), ("valorix", ids_valorix), ("document", ids_document)):
        refusees += supprimer_transactions(source, ids, simuler=True)["refusees"]

    if refusees:
        raise AnnulationLotError(
            f"{len(refusees)} transaction(s) de ce lot sont déjà rapprochées. "
            "Annulez d'abord ces rapprochements avant d'annuler l'import."
        )

    supprimer_transactions("banque", ids_banque)
    supprimer_transactions("valorix", ids_valorix)
    supprimer_transactions("document", ids_document)

    lot.annule_le = timezone.now()
    lot.save(update_fields=["annule_le"])
    return {"supprimees": len(ids_banque) + len(ids_valorix) + len(ids_document)}
