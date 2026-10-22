
from decimal import Decimal


def _score_montant(ecart, tolerance):
    """Attribue jusqu'à 30 points selon la proximité des montants."""
    ecart = Decimal(str(ecart))
    tolerance = Decimal(str(tolerance))

    if ecart < 0 or tolerance < 0:
        raise ValueError(
            "L'écart et la tolérance doivent être positifs ou nuls."
        )

    if ecart > tolerance:
        return 0

    if tolerance == 0:
        return 30 if ecart == 0 else 0

    proportion = (tolerance - ecart) / tolerance
    return round(float(proportion * Decimal("30")))


def _score_date(ecart_jours, regle):
    """Attribue jusqu'à 15 points selon la proximité des dates."""
    ecart_jours = int(ecart_jours)
    distance = abs(ecart_jours)

    if ecart_jours < 0:
        fenetre = regle.fenetre_jours_avant
    else:
        fenetre = regle.fenetre_jours_apres

    if distance == 0:
        return 15

    if fenetre <= 0 or distance > fenetre:
        return 0

    proportion = Decimal(fenetre - distance) / Decimal(fenetre)
    return round(float(proportion * Decimal("15")))


def _sens_inverse_correct(candidat):
    """Vérifie que le sens bancaire est inverse du sens Valorix."""
    sens_valorix = candidat.get("sens_valorix")
    sens_banque = candidat.get("sens_banque")

    return (
        (sens_valorix == "DEBIT" and sens_banque == "CREDIT")
        or
        (sens_valorix == "CREDIT" and sens_banque == "DEBIT")
    )


def calculer_score(candidat, regle):
    """
    Calcule un score de 0 à 100.

    Le score classe les candidats mais ne valide jamais
    automatiquement un rapprochement.
    """
    ecart = Decimal(str(candidat["ecart_montant"]))
    tolerance = Decimal(str(candidat["tolerance"]))

    score_montant = _score_montant(ecart, tolerance)
    score_date = _score_date(candidat["ecart_jours"], regle)

    # La référence exacte et le numéro de chèque appartiennent
    # au même critère : on ne cumule pas leurs points.
    reference_correspond = bool(
        candidat.get("reference_correspond", False)
    )
    cheque_correspond = bool(
        candidat.get("numero_cheque_correspond", False)
    )
    identifiant_correspond = (
        reference_correspond or cheque_correspond
    )
    score_reference = 25 if identifiant_correspond else 0

    compte_correspond = bool(
        candidat.get("compte_correspond", False)
    )
    score_compte = 15 if compte_correspond else 0

    nom_correspond = bool(candidat.get("nom_correspond", False))
    score_nom = 10 if nom_correspond else 0

    sens_correct = _sens_inverse_correct(candidat)
    score_sens = 5 if sens_correct else 0

    score_total = (
        score_montant
        + score_date
        + score_reference
        + score_compte
        + score_nom
        + score_sens
    )

    details = {
        "montant": {
            "score": score_montant,
            "maximum": 30,
            "ecart": str(ecart),
            "tolerance": str(tolerance),
        },
        "date": {
            "score": score_date,
            "maximum": 15,
            "ecart_jours": candidat["ecart_jours"],
        },
        "reference": {
            "score": score_reference,
            "maximum": 25,
            "correspond": reference_correspond,
            "numero_cheque_correspond": cheque_correspond,
        },
        "compte": {
            "score": score_compte,
            "maximum": 15,
            "correspond": compte_correspond,
        },
        "nom_client": {
            "score": score_nom,
            "maximum": 10,
            "correspond": nom_correspond,
        },
        "sens": {
            "score": score_sens,
            "maximum": 5,
            "verifie": sens_correct,
            "sens_valorix": candidat.get("sens_valorix"),
            "sens_banque": candidat.get("sens_banque"),
        },
    }

    return {
        "score": score_total,
        "details": details,
    }


def classer_candidats(candidats, regle):
    """
    Ajoute un score à chaque candidat et les classe du meilleur
    au moins bon. Ne modifie pas les transactions sources.
    """
    resultats = []

    for candidat in candidats:
        evaluation = calculer_score(candidat, regle)

        resultats.append({
            **candidat,
            "score_correspondance": evaluation["score"],
            "score_details": evaluation["details"],
        })

    resultats.sort(
        key=lambda item: (
            -item["score_correspondance"],
            item["ecart_montant"],
            abs(item["ecart_jours"]),
        )
    )

    return resultats
