"""Paramètres de règles : lecture, instantané (snapshot) et valeurs par défaut."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from core.models import RegleMatching, sens_transactions
from valorix.models import TypeTransactionCaisse


@dataclass(frozen=True)
class ParametresRegle:
    """
    Copie figée d'une règle. Expose les mêmes noms d'attributs que
    ``RegleMatching`` : les services de scoring/tolérance acceptent
    indifféremment l'un ou l'autre.
    """

    type_transaction_valorix: str
    sens_transaction_document_cible: str
    fenetre_jours_avant: int
    fenetre_jours_apres: int
    tolerance_fixe: Decimal
    tolerance_pourcentage: Decimal
    regroupement_max: int = 10
    # Contrepartie : None = relevé bancaire, sinon id d'un TypeDocument.
    type_document_id: Optional[int] = None
    source_nom: str = "Banque"

    @property
    def est_document(self):
        return self.type_document_id is not None

    @classmethod
    def depuis_objet(cls, regle):
        return cls(
            type_transaction_valorix=regle.type_transaction_valorix,
            sens_transaction_document_cible=regle.sens_transaction_document_cible,
            fenetre_jours_avant=int(regle.fenetre_jours_avant),
            fenetre_jours_apres=int(regle.fenetre_jours_apres),
            tolerance_fixe=Decimal(str(regle.tolerance_fixe)),
            tolerance_pourcentage=Decimal(str(regle.tolerance_pourcentage)),
            regroupement_max=int(getattr(regle, "regroupement_max", 10)),
            type_document_id=getattr(regle, "type_document_id", None),
            source_nom=(
                regle.type_document.nom
                if getattr(regle, "type_document_id", None) else "Banque"
            ),
        )

    @classmethod
    def depuis_snapshot(cls, donnees):
        return cls(
            type_transaction_valorix=donnees["type_transaction_valorix"],
            sens_transaction_document_cible=donnees["sens_transaction_document_cible"],
            fenetre_jours_avant=int(donnees["fenetre_jours_avant"]),
            fenetre_jours_apres=int(donnees["fenetre_jours_apres"]),
            tolerance_fixe=Decimal(str(donnees["tolerance_fixe"])),
            tolerance_pourcentage=Decimal(str(donnees["tolerance_pourcentage"])),
            regroupement_max=int(donnees.get("regroupement_max", 10)),
            type_document_id=donnees.get("type_document_id"),
            source_nom=donnees.get("source_nom", "Banque"),
        )

    def en_snapshot(self):
        """Dictionnaire JSON-compatible stocké sur le rapprochement."""
        return {
            "type_transaction_valorix": self.type_transaction_valorix,
            "sens_transaction_document_cible": self.sens_transaction_document_cible,
            "fenetre_jours_avant": self.fenetre_jours_avant,
            "fenetre_jours_apres": self.fenetre_jours_apres,
            "tolerance_fixe": str(self.tolerance_fixe),
            "tolerance_pourcentage": str(self.tolerance_pourcentage),
            "regroupement_max": self.regroupement_max,
            "type_document_id": self.type_document_id,
            "source_nom": self.source_nom,
        }


def parametres_pour_type(type_transaction, type_document_id=None, actif_seulement=True):
    """Règle (figée) applicable à un type Valorix et une contrepartie, ou None."""
    qs = RegleMatching.objects.select_related("type_document").filter(
        type_transaction_valorix=type_transaction, type_document_id=type_document_id
    )
    if actif_seulement:
        qs = qs.filter(actif=True)
    regle = qs.first()
    return ParametresRegle.depuis_objet(regle) if regle else None


def parametres_du_rapprochement(rapprochement, type_transaction=None):
    """
    Paramètres à utiliser pour (re)valider un rapprochement : son instantané
    s'il existe, sinon la règle actuelle du type (anciennes propositions).
    """
    if rapprochement.regle_snapshot:
        return ParametresRegle.depuis_snapshot(rapprochement.regle_snapshot)
    if type_transaction:
        return parametres_pour_type(
            type_transaction, rapprochement.type_document_id, actif_seulement=False
        )
    return None


def creer_regles_par_defaut():
    """
    Crée une règle (contrepartie : relevé bancaire) pour chaque type Valorix
    qui n'en a pas encore.
    Sens bancaire par défaut : DEBIT pour les retraits, CREDIT sinon
    (à vérifier selon le fonctionnement comptable réel).
    """
    existants = set(
        RegleMatching.objects.filter(type_document__isnull=True)
        .values_list("type_transaction_valorix", flat=True)
    )
    creees = []
    for valeur, _ in TypeTransactionCaisse.choices:
        if valeur in existants:
            continue
        sens = (
            sens_transactions.DEBIT if "RETRAIT" in valeur
            else sens_transactions.CREDIT
        )
        creees.append(
            RegleMatching.objects.create(
                type_transaction_valorix=valeur,
                sens_transaction_document_cible=sens,
            )
        )
    return creees
