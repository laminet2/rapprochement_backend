
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import (
    Rapprochement,
    StatutValidation,
    ResultatMatching,
    TransactionBancaireRapprochee,
    TransactionValorixRapprochee,
)
from core.services.candidats import obtenir_montant_et_sens
from core.services.tolerance import evaluer_ecart


class ValidationRapprochementError(Exception):
    """Erreur métier pendant la validation d'un rapprochement."""


@transaction.atomic
def valider_rapprochement(
    rapprochement_id,
    utilisateur,
    sens_banque_par_type=None,
):
    """
    Valide une proposition 1-1 après vérifications.

    - Verrouille la proposition et les transactions concernées.
    - Vérifie que la proposition est encore en attente.
    - Vérifie que les deux transactions existent et ne sont pas
      déjà utilisées dans un autre rapprochement validé.
    - Revérifie la date et la tolérance de montant.
    - Enregistre l'utilisateur et l'heure de validation.

    Aucun rapprochement n'est validé automatiquement par le score.
    """

    # Verrouiller la proposition pour éviter deux validations simultanées.
    try:
        rapprochement = (
            Rapprochement.objects
            .select_for_update()
            .get(pk=rapprochement_id)
        )
    except Rapprochement.DoesNotExist:
        raise ValidationRapprochementError(
            "Cette proposition de rapprochement n'existe pas."
        )

    if rapprochement.statut_validation != StatutValidation.PROPOSE:
        raise ValidationRapprochementError(
            "Seule une proposition en attente peut être validée."
        )

    if rapprochement.resultat != ResultatMatching.CORRESPONDANCE:
        raise ValidationRapprochementError(
            "Le résultat de cette proposition ne permet pas sa validation."
        )

    if rapprochement.regle is None:
        raise ValidationRapprochementError(
            "Aucune règle de rapprochement n'est associée à cette proposition."
        )

    # Cette implémentation traite uniquement le rapprochement 1-1.
    liens_bancaires = list(
        TransactionBancaireRapprochee.objects.filter(
            rapprochement=rapprochement
        ).values_list("transaction_id", flat=True)
    )

    liens_valorix = list(
        TransactionValorixRapprochee.objects.filter(
            rapprochement=rapprochement
        ).values_list("transaction_id", flat=True)
    )

    if len(liens_bancaires) != 1 or len(liens_valorix) != 1:
        raise ValidationRapprochementError(
            "La proposition doit contenir exactement une transaction "
            "bancaire et une transaction Valorix."
        )

    banque_id = liens_bancaires[0]
    valorix_id = liens_valorix[0]

    # Verrouiller les sources dans un ordre stable pour réduire
    # le risque de conflits entre validations concurrentes.
    from releverBancaire.models import TransactionBancaire
    from valorix.models import TransactionValorix

    try:
        transaction_banque = (
            TransactionBancaire.objects
            .select_for_update()
            .get(pk=banque_id)
        )
        transaction_valorix = (
            TransactionValorix.objects
            .select_for_update()
            .get(pk=valorix_id)
        )
    except (
        TransactionBancaire.DoesNotExist,
        TransactionValorix.DoesNotExist,
    ):
        raise ValidationRapprochementError(
            "Une transaction source liée à cette proposition est introuvable."
        )

    # Empêcher le double rapprochement côté bancaire.
    banque_deja_validee = (
        TransactionBancaireRapprochee.objects.filter(
            transaction=transaction_banque,
            rapprochement__statut_validation=StatutValidation.VALIDE,
        )
        .exclude(rapprochement=rapprochement)
        .exists()
    )

    if banque_deja_validee:
        raise ValidationRapprochementError(
            "Cette transaction bancaire est déjà rapprochée."
        )

    # Empêcher le double rapprochement côté Valorix.
    valorix_deja_validee = (
        TransactionValorixRapprochee.objects.filter(
            transaction=transaction_valorix,
            rapprochement__statut_validation=StatutValidation.VALIDE,
        )
        .exclude(rapprochement=rapprochement)
        .exists()
    )

    if valorix_deja_validee:
        raise ValidationRapprochementError(
            "Cette transaction Valorix est déjà rapprochée."
        )

    regle = rapprochement.regle

    if transaction_valorix.types != regle.type_transaction_valorix:
        raise ValidationRapprochementError(
            "Le type de transaction ne correspond plus à la règle associée."
        )

    # Revérifier la fenêtre de dates à partir des données sources.
    date_valorix = transaction_valorix.date_transaction.date()
    date_banque = transaction_banque.date_transaction

    date_debut = date_valorix - timedelta(
        days=regle.fenetre_jours_avant
    )
    date_fin = date_valorix + timedelta(
        days=regle.fenetre_jours_apres
    )

    if not date_debut <= date_banque <= date_fin:
        raise ValidationRapprochementError(
            "Les dates ne respectent plus la fenêtre de rapprochement."
        )

    # Revérifier la tolérance de montant.
    try:
        montant_banque, sens_banque = obtenir_montant_et_sens(
            transaction_banque
        )
        montant_valorix, sens_valorix = obtenir_montant_et_sens(
            transaction_valorix
        )
    except ValidationError as exc:
        raise ValidationRapprochementError(str(exc))

    evaluation = evaluer_ecart(
        montant_banque=montant_banque,
        montant_valorix=montant_valorix,
        tolerance_fixe=regle.tolerance_fixe,
        tolerance_pourcentage=regle.tolerance_pourcentage,
    )

    if not evaluation["acceptable"]:
        raise ValidationRapprochementError(
            "L'écart de montant dépasse la tolérance autorisée."
        )

    # Si une correspondance de sens a été configurée, la revérifier.
    sens_banque_par_type = sens_banque_par_type or {}
    sens_attendu = (
    "CREDIT" if sens_valorix == "DEBIT" else "DEBIT"
)

    if sens_banque != sens_attendu:
        raise ValidationRapprochementError(
            "Le sens bancaire doit être inverse du sens Valorix : "
            "un débit Valorix doit correspondre à un crédit bancaire, "
            "et un crédit Valorix à un débit bancaire."
        )

    # Les deux transactions sont maintenant considérées compatibles.
    # Enregistrer la décision humaine.
    rapprochement.statut_validation = StatutValidation.VALIDE
    rapprochement.ecart_montant = evaluation["ecart"]
    rapprochement.valide_le = timezone.now()
    rapprochement.valide_par = utilisateur

    rapprochement.save(
        update_fields=[
            "statut_validation",
            "ecart_montant",
            "valide_le",
            "valide_par",
        ]
    )

    return rapprochement
