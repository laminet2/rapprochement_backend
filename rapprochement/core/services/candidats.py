from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

from releverBancaire.models import TransactionBancaire
from core.services.tolerance import evaluer_ecart
import re
import unicodedata




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


def normaliser_texte(texte):
    """
    Normalise un texte pour faciliter les comparaisons :
    - majuscules ;
    - suppression des accents ;
    - espaces uniformisés.
    """
    if not texte:
        return ""

    texte = str(texte).upper().strip()
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(
        caractere
        for caractere in texte
        if not unicodedata.combining(caractere)
    )

    return " ".join(texte.split())


def contient_numero_exact(texte, numero):
    """
    Recherche un numéro comme élément distinct.
    Évite les correspondances à l'intérieur d'un autre numéro.
    """
    texte = normaliser_texte(texte)
    numero = str(numero or "").strip()

    if not texte or not numero:
        return False

    motif = rf"(?<!\d){re.escape(numero)}(?!\d)"
    return re.search(motif, texte) is not None


def numero_cheque_correspond(transaction_valorix, transaction_banque):
    """
    Recherche les références Valorix dans les références et le libellé
    bancaire. Une correspondance doit être exacte au niveau du numéro.
    """
    references_valorix = [
        getattr(transaction_valorix, "references", None),
        getattr(transaction_valorix, "references_rapprochement", None),
    ]

    textes_bancaires = [
        getattr(transaction_banque, "reference_rapprochement", None),
        getattr(transaction_banque, "libelle_brut", None),
    ]

    for reference in references_valorix:
        if not reference:
            continue

        # Les références peuvent contenir plusieurs éléments séparés
        # par des espaces, virgules, tirets ou autres signes.
        numeros = re.findall(r"\d+", str(reference))

        for numero in numeros:
            for texte_bancaire in textes_bancaires:
                if contient_numero_exact(texte_bancaire, numero):
                    return True

    return False


def numero_compte_correspond(transaction_valorix, transaction_banque):
    """
    Recherche le numéro de compte Valorix dans le libellé bancaire,
    en respectant les limites numériques.
    """
    numero_compte = getattr(transaction_valorix, "numero_compte", None)
    libelle = getattr(transaction_banque, "libelle_brut", None)

    if not numero_compte or not libelle:
        return False

    return contient_numero_exact(libelle, numero_compte)


def nom_client_correspond(transaction_valorix, transaction_banque):
    """
    Compare les noms indépendamment de l'ordre des mots.
    Exige au moins deux mots significatifs correspondants pour éviter
    qu'un prénom ou nom très courant suffise à lui seul.
    """
    nom_valorix = normaliser_texte(
        getattr(transaction_valorix, "nomComplet", None)
    )
    libelle_banque = normaliser_texte(
        getattr(transaction_banque, "libelle_brut", None)
    )

    if not nom_valorix or not libelle_banque:
        return False

    mots_nom = {
        mot for mot in re.findall(r"[A-Z]+", nom_valorix)
        if len(mot) >= 2
    }

    mots_libelle = set(re.findall(r"[A-Z]+", libelle_banque))

    if len(mots_nom) < 2:
        return False

    mots_communs = mots_nom & mots_libelle

    return len(mots_communs) >= min(2, len(mots_nom))


def references_correspondent(transaction_valorix, transaction_banque):
    """
    Recherche une référence numérique Valorix dans la référence
    ou le libellé bancaire.

    Les séquences numériques sont comparées exactement :
    12345 correspond à 12345, mais pas à 9123456 ni à 123456.
    Les séquences doivent contenir au moins 4 chiffres pour éviter
    les correspondances trop faibles.
    """
    references_valorix = [
        getattr(transaction_valorix, "references", None),
        getattr(transaction_valorix, "references_rapprochement", None),
    ]

    texte_bancaire = " ".join(
        str(valeur)
        for valeur in (
            transaction_banque.reference_rapprochement,
            getattr(transaction_banque, "libelle_brut", None),
        )
        if valeur
    )

    numeros_valorix = set()

    for reference in references_valorix:
        if not reference:
            continue

        numeros_valorix.update(
            re.findall(r"(?<!\d)\d{4,}(?!\d)", str(reference))
        )

    if not numeros_valorix:
        return False

    numeros_bancaires = set(
        re.findall(r"(?<!\d)\d{4,}(?!\d)", texte_bancaire)
    )

    return bool(numeros_valorix & numeros_bancaires)



def rechercher_candidats_bancaires(
    transaction_valorix,
    regle):
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

   
    sens_document_cible_attendu = regle.sens_transaction_document_cible

    if sens_document_cible_attendu not in (None, "DEBIT", "CREDIT"):
        raise ValueError(
            "Le sens du document cible attendu doit être DEBIT, CREDIT ou None."
        )

    transactions_bancaires = TransactionBancaire.objects.filter(
        date_transaction__range=(date_debut, date_fin),
    ).select_related("compte", "compte__banque")

    if not regle.prendre_banque_anciennes:
        aujourd_hui = timezone.localdate()
        transactions_bancaires = transactions_bancaires.filter(
            created_at__date=aujourd_hui
        )

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
            sens_banque != sens_document_cible_attendu
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
            "sens_verifie": sens_document_cible_attendu is not None,
            "ecart_montant": evaluation["ecart"],
            "tolerance": evaluation["tolerance"],
            "reference_correspond": references_correspondent(
                transaction_valorix,
                transaction_banque,
            ),
            "ecart_jours": (
                transaction_banque.date_transaction - date_valorix
            ).days,
            "numero_cheque_correspond": numero_cheque_correspond(
                transaction_valorix,
                transaction_banque,
            ),
            "compte_correspond": numero_compte_correspond(
                transaction_valorix,
                transaction_banque,
            ),
            "nom_correspond": nom_client_correspond(
                transaction_valorix,
                transaction_banque,
            ),
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
