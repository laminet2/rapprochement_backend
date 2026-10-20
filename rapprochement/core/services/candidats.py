
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

from releverBancaire.models import TransactionBancaire
from core.services.tolerance import evaluer_ecart


def obtenir_montant_et_sens(transaction):
    """
    Retourne (montant positif, sens).

    Le sens est DEBIT ou CREDIT.
    Si les deux champs sont renseignés avec des montants non nuls,
    la transaction est considérée comme ambiguë.
    """
    debit = transaction.debit or Decimal("0")
    credit = transaction.credit or Decimal("0")

    if debit < 0 or credit < 0:
        raise ValidationError(
            "Les montants débit/crédit ne doivent pas être négatifs."
        )

    debit_actif = debit > 0
    credit_actif = credit > 0

    if debit_actif and credit_actif:
        raise ValidationError(
            "La transaction possède à la fois un débit et un crédit non nuls."
        )

    if debit_actif:
        return debit, "DEBIT"

    if credit_actif:
        return credit, "CREDIT"

    raise ValidationError(
        "Impossible de déterminer le montant : débit et crédit sont nuls."
    )


def normaliser_reference(reference):
    """
    Normalisation simple pour comparer des références.
    Ne supprime pas les zéros initiaux, qui peuvent être significatifs.
    """
    if not reference:
        return ""

    return "".join(str(reference).upper().split()).strip()


def references_correspondent(transaction_valorix, transaction_banque):
    """
    Vérifie si la référence bancaire correspond à l'une des références
    disponibles côté Valorix.

    Une correspondance de référence reste un indice, pas une validation.
    """
    reference_banque = normaliser_reference(
        transaction_banque.reference_rapprochement
    )

    if not reference_banque:
        return False

    references_valorix = {
        normaliser_reference(
            getattr(transaction_valorix, "references", None)
        ),
        normaliser_reference(
            getattr(transaction_valorix, "references_rapprochement", None)
        ),
    }

    references_valorix.discard("")

    return reference_banque in references_valorix


def rechercher_candidats_bancaires(
    transaction_valorix,
    regle,
    sens_banque_par_type=None,
):
    """
    Recherche les transactions bancaires candidates pour une transaction
    Valorix, selon la fenêtre de dates et la tolérance de la règle.

    sens_banque_par_type est un dictionnaire facultatif, par exemple :
        {
            "DEPOT_CHEQUE": "CREDIT",
            "RETRAIT_CHEQUE": "DEBIT",
        }

    Ces correspondances doivent être confirmées selon le fonctionnement
    comptable réel du projet.

    Retourne une liste de dictionnaires. Ne crée aucun rapprochement.
    """
    if not regle.active:
        return []

    if transaction_valorix.types != regle.type_transaction_valorix:
        return []

    date_valorix = transaction_valorix.date_transaction.date()

    date_debut = date_valorix - timedelta(
        days=regle.fenetre_jours_avant
    )
    date_fin = date_valorix + timedelta(
        days=regle.fenetre_jours_apres
    )

    montant_valorix, sens_valorix = obtenir_montant_et_sens(
        transaction_valorix
    )

    correspondances_sens = sens_banque_par_type or {}
    sens_banque_attendu = correspondances_sens.get(
        transaction_valorix.types
    )

    if sens_banque_attendu not in (None, "DEBIT", "CREDIT"):
        raise ValueError(
            "Le sens bancaire attendu doit être DEBIT, CREDIT ou None."
        )

    transactions_bancaires = TransactionBancaire.objects.filter(
        date_transaction__range=(date_debut, date_fin),
    ).select_related("compte", "compte__banque")

    candidats = []

    for transaction_banque in transactions_bancaires:
        try:
            montant_banque, sens_banque = obtenir_montant_et_sens(
                transaction_banque
            )
        except ValidationError:
            # Une ligne ambiguë ou sans montant ne peut pas être proposée.
            continue

        if (
            sens_banque_attendu is not None
            and sens_banque != sens_banque_attendu
        ):
            continue

        evaluation = evaluer_ecart(
            montant_banque=montant_banque,
            montant_valorix=montant_valorix,
            tolerance_fixe=regle.tolerance_fixe,
            tolerance_pourcentage=regle.tolerance_pourcentage,
        )

        if not evaluation["acceptable"]:
            continue

        candidats.append({
            "transaction_bancaire": transaction_banque,
            "montant_banque": montant_banque,
            "montant_valorix": montant_valorix,
            "sens_banque": sens_banque,
            "sens_valorix": sens_valorix,
            "sens_verifie": sens_banque_attendu is not None,
            "ecart_montant": evaluation["ecart"],
            "tolerance": evaluation["tolerance"],
            "reference_correspond": references_correspondent(
                transaction_valorix,
                transaction_banque,
            ),
            "ecart_jours": (
                transaction_banque.date_transaction - date_valorix
            ).days,
        })

    # On affiche d'abord les écarts les plus faibles,
    # puis les dates les plus proches, puis les références correspondantes.
    candidats.sort(
        key=lambda candidat: (
            candidat["ecart_montant"],
            abs(candidat["ecart_jours"]),
            not candidat["reference_correspond"],
        )
    )

    return candidats
