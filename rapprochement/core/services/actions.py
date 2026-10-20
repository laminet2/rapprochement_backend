
# core/services/actions.py

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Rapprochement, StatutValidation


class ActionRapprochementError(Exception):
    """Erreur lors du rejet ou de l'annulation d'un rapprochement."""


@transaction.atomic
def _terminer_proposition(rapprochement_id, utilisateur, motif, statut_cible):
    motif = (motif or "").strip()

    if not motif:
        raise ActionRapprochementError(
            "Un motif est obligatoire pour cette action."
        )

    if statut_cible not in (
        StatutValidation.REJETE,
        StatutValidation.ANNULE,
    ):
        raise ActionRapprochementError(
            "Le statut demandé n'est pas autorisé."
        )

    if utilisateur is None or not utilisateur.is_authenticated:
        raise ActionRapprochementError(
            "Un utilisateur authentifié est nécessaire."
        )

    try:
        rapprochement = (
            Rapprochement.objects
            .select_for_update()
            .get(pk=rapprochement_id)
        )
    except Rapprochement.DoesNotExist as exc:
        raise ActionRapprochementError(
            "Le rapprochement demandé n'existe pas."
        ) from exc

    if rapprochement.statut_validation != StatutValidation.PROPOSE:
        raise ActionRapprochementError(
            "Seule une proposition en attente peut être rejetée "
            "ou annulée."
        )

    maintenant = timezone.localtime(timezone.now())
    action = (
        "Rejet"
        if statut_cible == StatutValidation.REJETE
        else "Annulation"
    )

    nouvelle_ligne = (
        f"[{action} le {maintenant:%Y-%m-%d %H:%M:%S} "
        f"par {utilisateur.get_username()}] {motif}"
    )

    commentaire_existant = (rapprochement.commentaire or "").strip()

    rapprochement.commentaire = (
        f"{commentaire_existant}\n{nouvelle_ligne}".strip()
    )
    rapprochement.statut_validation = statut_cible

    rapprochement.save(
        update_fields=[
            "commentaire",
            "statut_validation",
        ]
    )

    return rapprochement


def rejeter_rapprochement(rapprochement_id, utilisateur, motif):
    """Rejette une proposition incorrecte en conservant son historique."""
    return _terminer_proposition(
        rapprochement_id=rapprochement_id,
        utilisateur=utilisateur,
        motif=motif,
        statut_cible=StatutValidation.REJETE,
    )


def annuler_rapprochement(rapprochement_id, utilisateur, motif):
    """Annule une proposition devenue inutile ou créée par erreur."""
    return _terminer_proposition(
        rapprochement_id=rapprochement_id,
        utilisateur=utilisateur,
        motif=motif,
        statut_cible=StatutValidation.ANNULE,
    )
