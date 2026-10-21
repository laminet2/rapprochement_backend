from django.utils import timezone
from core.models import RegleMatching

from django.db import transaction

from core.models import (
    Rapprochement,
    StatutValidation,
    ResultatMatching,
    TransactionBancaireRapprochee,
    TransactionValorixRapprochee,
)
from core.services.candidats import rechercher_candidats_bancaires
from core.services.scoring import classer_candidats
from valorix.models import TransactionValorix


@transaction.atomic
def generer_propositions(
    transaction_valorix,
    regle,
    sens_banque_par_type=None,
):
    """
    Recherche et enregistre les propositions 1-1 pour une transaction
    Valorix.

    - Ne valide jamais automatiquement.
    - Ne modifie pas les transactions sources.
    - Ne recrée pas une paire déjà proposée, rejetée, annulée ou validée.
    - Actualise le score d'une proposition encore en attente.

    Retourne un résumé des opérations effectuées.
    """

    # Verrouille la transaction Valorix pendant cette génération.
    valorix = (
        TransactionValorix.objects
        .select_for_update()
        .get(pk=transaction_valorix.pk)
    )

    resultat = {
        "creees": 0,
        "actualisees": 0,
        "ignorees": 0,
        "propositions": [],
    }

    if not regle.active or valorix.types != regle.type_transaction_valorix:
        return resultat

    # Une transaction Valorix déjà rapprochée et validée ne doit
    # pas être utilisée dans un autre rapprochement.
    deja_validee = TransactionValorixRapprochee.objects.filter(
        transaction=valorix,
        rapprochement__statut_validation=StatutValidation.VALIDE,
    ).exists()

    if deja_validee:
        resultat["ignorees"] += 1
        return resultat

    candidats = rechercher_candidats_bancaires(
        transaction_valorix=valorix,
        regle=regle,
        sens_banque_par_type=sens_banque_par_type,
    )

    candidats = classer_candidats(candidats, regle)

    for candidat in candidats:
        transaction_banque = candidat["transaction_bancaire"]

        # Vérification de sécurité : la transaction bancaire ne doit
        # pas déjà être utilisée dans un rapprochement validé.
        banque_deja_validee = TransactionBancaireRapprochee.objects.filter(
            transaction=transaction_banque,
            rapprochement__statut_validation=StatutValidation.VALIDE,
        ).exists()

        if banque_deja_validee:
            resultat["ignorees"] += 1
            continue

        # Cherche si cette paire exacte existe déjà.
        proposition_existante = (
            Rapprochement.objects.filter(
                transactions_bancaires__transaction=transaction_banque,
                transactions_valorix__transaction=valorix,
            )
            .distinct()
            .first()
        )

        if proposition_existante:
            if (
                proposition_existante.statut_validation
                == StatutValidation.PROPOSE
            ):
                # Actualise la proposition en attente au lieu d'en créer
                # une deuxième pour la même paire.
                proposition_existante.score_correspondance = (
                    candidat["score_correspondance"]
                )
                proposition_existante.score_details = (
                    candidat["score_details"]
                )
                proposition_existante.ecart_montant = (
                    candidat["ecart_montant"]
                )
                proposition_existante.resultat = (
                    ResultatMatching.CORRESPONDANCE
                )
                proposition_existante.regle = regle

                proposition_existante.save(
                    update_fields=[
                        "score_correspondance",
                        "score_details",
                        "ecart_montant",
                        "resultat",
                        "regle",
                    ]
                )

                resultat["actualisees"] += 1
                resultat["propositions"].append(proposition_existante)
            else:
                # Ne pas recréer une paire rejetée, annulée ou validée.
                resultat["ignorees"] += 1

            continue

        # Création d'une nouvelle proposition non validée.
        proposition = Rapprochement.objects.create(
            statut_validation=StatutValidation.PROPOSE,
            resultat=ResultatMatching.CORRESPONDANCE,
            score_correspondance=candidat["score_correspondance"],
            score_details=candidat["score_details"],
            ecart_montant=candidat["ecart_montant"],
            regle=regle,
        )

        TransactionBancaireRapprochee.objects.create(
            rapprochement=proposition,
            transaction=transaction_banque,
        )

        TransactionValorixRapprochee.objects.create(
            rapprochement=proposition,
            transaction=valorix,
        )

        resultat["creees"] += 1
        resultat["propositions"].append(proposition)

    return resultat



def generer_toutes_les_propositions(sens_banque_par_type=None):
    """
    Parcourt les transactions Valorix éligibles
    et génère leurs propositions selon les règles actives.
    """
    aujourd_hui = timezone.localdate()

    bilan = {
        "transactions_traitees": 0,
        "creees": 0,
        "actualisees": 0,
        "ignorees": 0,
        "propositions": [],
    }

    regles = RegleMatching.objects.filter(active=True)

    for regle in regles:
        transactions = TransactionValorix.objects.filter(
            types=regle.type_transaction_valorix,
        )

        # Par défaut, traiter uniquement les transactions
        # Valorix créées aujourd'hui.
        if not regle.prendre_valorix_anciennes:
            transactions = transactions.filter(
                created_at__date=aujourd_hui,
            )

        # Exclure les transactions déjà rapprochées et validées.
        transactions = transactions.exclude(
            pk__in=TransactionValorixRapprochee.objects.filter(
                rapprochement__statut_validation=StatutValidation.VALIDE,
            ).values("transaction_id")
        )

        for transaction_valorix in transactions.iterator():
            bilan["transactions_traitees"] += 1

            resultat = generer_propositions(
                transaction_valorix=transaction_valorix,
                regle=regle,
                sens_banque_par_type=sens_banque_par_type,
            )

            bilan["creees"] += resultat["creees"]
            bilan["actualisees"] += resultat["actualisees"]
            bilan["ignorees"] += resultat["ignorees"]
            bilan["propositions"].extend(
                resultat["propositions"]
            )

    return bilan
