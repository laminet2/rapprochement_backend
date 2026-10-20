
from decimal import Decimal


def _score_montant(ecart, tolerance):
    """
    Jusqu'à 40 points.
    Un écart nul donne le maximum ; un écart égal à la tolérance
    donne zéro point pour ce critère, sauf si la tolérance est nulle.
    """
    ecart = Decimal(str(ecart))
    tolerance = Decimal(str(tolerance))

    if ecart < 0 or tolerance < 0:
        raise ValueError("L'écart et la tolérance doivent être positifs ou nuls.")

    if ecart > tolerance:
        return 0

    if tolerance == 0:
        return 40 if ecart == 0 else 0

    proportion = (tolerance - ecart) / tolerance
    return round(float(proportion * Decimal("40")))


def _score_date(ecart_jours, regle):
    """
    Jusqu'à 25 points, selon la proximité de la date.
    La fenêtre avant et la fenêtre après sont évaluées séparément.
    """
    ecart_jours = int(ecart_jours)
    distance = abs(ecart_jours)

    if ecart_jours < 0:
        fenetre = regle.fenetre_jours_avant
    else:
        fenetre = regle.fenetre_jours_apres

    if distance == 0:
        return 25

    if fenetre <= 0 or distance > fenetre:
        return 0

    proportion = Decimal(fenetre - distance) / Decimal(fenetre)
    return round(float(proportion * Decimal("25")))


def calculer_score(candidat, regle):
    """
    Calcule un score de 0 à 100 et détaille les critères.

    Le candidat doit provenir de rechercher_candidats_bancaires().
    Ce score sert au classement et ne valide jamais une opération.
    """
    ecart = Decimal(str(candidat["ecart_montant"]))
    tolerance = Decimal(str(candidat["tolerance"]))

    score_montant = _score_montant(ecart, tolerance)
    score_date = _score_date(candidat["ecart_jours"], regle)

    score_reference = (
        25 if candidat.get("reference_correspond", False) else 0
    )

    # Ces points ne sont attribués que si une règle de sens
    # a été explicitement configurée et que le candidat l'a respectée.
    score_sens = 10 if candidat.get("sens_verifie", False) else 0

    score_total = min(
        100,
        score_montant + score_date + score_reference + score_sens,
    )

    details = {
        "montant": {
            "score": score_montant,
            "maximum": 40,
            "ecart": str(ecart),
            "tolerance": str(tolerance),
        },
        "date": {
            "score": score_date,
            "maximum": 25,
            "ecart_jours": candidat["ecart_jours"],
        },
        "reference": {
            "score": score_reference,
            "maximum": 25,
            "correspond": bool(
                candidat.get("reference_correspond", False)
            ),
        },
        "sens": {
            "score": score_sens,
            "maximum": 10,
            "verifie": bool(candidat.get("sens_verifie", False)),
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
