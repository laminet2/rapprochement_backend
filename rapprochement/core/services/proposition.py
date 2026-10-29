"""Création / mise à jour des propositions de rapprochement en base."""

from django.db import transaction
from django.db.models import Q

from core.models import (
    LigneDocumentRapprochee,
    OrigineRapprochement,
    Rapprochement,
    RegleMatching,
    ResultatMatching,
    StatutValidation,
    TransactionBancaireRapprochee,
    TransactionValorixRapprochee,
)
from core.services.matching import rechercher_propositions
from core.services.regles import ParametresRegle
from documents.models import LigneDocument
from valorix.models import TransactionValorix


def _par_lots(valeurs, taille=500):
    valeurs = list(valeurs)
    for i in range(0, len(valeurs), taille):
        yield valeurs[i:i + taille]


def lien_contrepartie(params):
    """Modèle de lien entre un rapprochement et sa contrepartie."""
    return LigneDocumentRapprochee if params.est_document else TransactionBancaireRapprochee


def charger_existants(ids_contre, ids_valorix, lien):
    """
    Rapprochements (tous statuts) qui touchent ces transactions.
    Retourne {(frozenset(ids contrepartie), frozenset(ids valorix)): (id, statut)}.
    """
    rids = set()
    for lot in _par_lots(ids_contre):
        rids.update(
            lien.objects.filter(transaction_id__in=lot)
            .values_list("rapprochement_id", flat=True)
        )
    for lot in _par_lots(ids_valorix):
        rids.update(
            TransactionValorixRapprochee.objects.filter(transaction_id__in=lot)
            .values_list("rapprochement_id", flat=True)
        )
    if not rids:
        return {}

    banque, valorix, statuts = {}, {}, {}
    for lot in _par_lots(rids):
        for rid, tid in lien.objects.filter(
            rapprochement_id__in=lot
        ).values_list("rapprochement_id", "transaction_id"):
            banque.setdefault(rid, set()).add(tid)
        for rid, tid in TransactionValorixRapprochee.objects.filter(
            rapprochement_id__in=lot
        ).values_list("rapprochement_id", "transaction_id"):
            valorix.setdefault(rid, set()).add(tid)
        statuts.update(
            Rapprochement.objects.filter(id__in=lot)
            .values_list("id", "statut_validation")
        )

    return {
        (frozenset(banque.get(rid, ())), frozenset(valorix.get(rid, ()))): (rid, statut)
        for rid, statut in statuts.items()
    }


def _details(candidat):
    details = dict(candidat["score_details"])
    details["type_rapprochement"] = candidat["type_rapprochement"]
    details["nombre_contrepartie"] = len(candidat["lignes_contrepartie"])
    details["nombre_valorix"] = len(candidat["lignes_valorix"])
    details["montant_contrepartie"] = str(candidat["montant_contrepartie"])
    details["montant_valorix"] = str(candidat["montant_valorix"])
    return details


@transaction.atomic
def generer_pour_regle(params, lot_valorix_ids=None, lot_contrepartie_ids=None,
                       inclure_regroupements=True):
    """Génère les propositions pour UNE règle (un type Valorix + une contrepartie)."""
    candidats, stats = rechercher_propositions(
        params, lot_valorix_ids, lot_contrepartie_ids, inclure_regroupements
    )

    lien = lien_contrepartie(params)
    ids_c = {l.id for c in candidats for l in c["lignes_contrepartie"]}
    ids_v = {l.id for c in candidats for l in c["lignes_valorix"]}
    existants = charger_existants(ids_c, ids_v, lien)
    snapshot = params.en_snapshot()

    a_creer, liens_c, liens_v, a_maj = [], [], [], []
    bilan = {
        "type_transaction_valorix": params.type_transaction_valorix,
        "source": params.source_nom,
        **stats,
        "propositions_creees": 0,
        "propositions_actualisees": 0,
        "propositions_deja_traitees": 0,
        "propositions_1_1": 0,
        "propositions_regroupees": 0,
        "propositions_ids": [],
    }

    for c in candidats:
        cle = (
            frozenset(l.id for l in c["lignes_contrepartie"]),
            frozenset(l.id for l in c["lignes_valorix"]),
        )
        existant = existants.get(cle)

        if existant:
            rid, statut = existant
            if statut == StatutValidation.PROPOSE:
                a_maj.append((rid, c))
            else:
                bilan["propositions_deja_traitees"] += 1
            continue

        rapprochement = Rapprochement(
            statut_validation=StatutValidation.PROPOSE,
            resultat=ResultatMatching.CORRESPONDANCE,
            origine=OrigineRapprochement.AUTO,
            type_document_id=params.type_document_id,
            score_correspondance=c["score_correspondance"],
            ecart_montant=c["ecart_montant"],
            score_details=_details(c),
            regle_snapshot=snapshot,
        )
        a_creer.append(rapprochement)
        liens_c += [
            lien(rapprochement=rapprochement, transaction_id=l.id)
            for l in c["lignes_contrepartie"]
        ]
        liens_v += [
            TransactionValorixRapprochee(rapprochement=rapprochement, transaction_id=l.id)
            for l in c["lignes_valorix"]
        ]
        bilan["propositions_creees"] += 1
        bilan["propositions_ids"].append(str(rapprochement.id))
        bilan[
            "propositions_1_1" if c["type_rapprochement"] == "1-1"
            else "propositions_regroupees"
        ] += 1

    Rapprochement.objects.bulk_create(a_creer, batch_size=500)
    lien.objects.bulk_create(liens_c, batch_size=500)
    TransactionValorixRapprochee.objects.bulk_create(liens_v, batch_size=500)

    for rid, c in a_maj:
        Rapprochement.objects.filter(pk=rid).update(
            score_correspondance=c["score_correspondance"],
            ecart_montant=c["ecart_montant"],
            score_details=_details(c),
            regle_snapshot=snapshot,
        )
        bilan["propositions_actualisees"] += 1
        bilan["propositions_ids"].append(str(rid))

    return bilan


def generer_toutes_les_propositions(
    lot_valorix_ids=None, lot_banque_ids=None, lot_document_ids=None, types=None,
    inclure_regroupements=True,
):
    """
    Applique toutes les règles actives (une par type Valorix et par contrepartie).

    Sans lot Valorix, des lots de contrepartie restreignent aussi les règles :
    importer un relevé bancaire ne relance que les règles « banque », importer
    un document ne relance que les règles de son type de document.
    """
    regles = RegleMatching.objects.select_related("type_document").filter(actif=True)
    if types:
        regles = regles.filter(type_transaction_valorix__in=types)

    if not lot_valorix_ids and (lot_banque_ids or lot_document_ids):
        visees = Q(pk__in=[])
        if lot_banque_ids:
            visees |= Q(type_document__isnull=True)
        if lot_document_ids:
            ids_types = LigneDocument.objects.filter(
                lot_id__in=lot_document_ids
            ).values_list("type_document_id", flat=True).distinct()
            visees |= Q(type_document_id__in=list(ids_types))
        regles = regles.filter(visees)

    par_type = []
    for regle in regles:
        params = ParametresRegle.depuis_objet(regle)
        lots = lot_document_ids if params.est_document else lot_banque_ids
        par_type.append(
            generer_pour_regle(
                params, lot_valorix_ids or None, lots or None, inclure_regroupements
            )
        )

    # Types Valorix sans aucune règle active : à signaler.
    qs = TransactionValorix.objects.all()
    if lot_valorix_ids:
        qs = qs.filter(lot_id__in=lot_valorix_ids)
    types_presents = set(qs.values_list("types", flat=True).distinct())
    types_avec_regle = set(
        RegleMatching.objects.filter(actif=True)
        .values_list("type_transaction_valorix", flat=True)
    )
    if types:
        types_presents &= set(types)

    total = lambda cle: sum(b[cle] for b in par_type)
    return {
        "propositions_creees": total("propositions_creees"),
        "propositions_actualisees": total("propositions_actualisees"),
        "propositions_deja_traitees": total("propositions_deja_traitees"),
        "propositions_1_1": total("propositions_1_1"),
        "propositions_regroupees": total("propositions_regroupees"),
        "valorix_examinees": total("valorix_examinees"),
        "contrepartie_examinees": total("contrepartie_examinees"),
        "types_sans_regle": sorted(types_presents - types_avec_regle),
        "details_par_type": par_type,
    }
