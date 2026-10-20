
from types import SimpleNamespace
from django.test import SimpleTestCase

from core.services.scoring import (
    calculer_score,
    classer_candidats,
)


class TestScoring(SimpleTestCase):

    def setUp(self):
        self.regle = SimpleNamespace(
            fenetre_jours_avant=2,
            fenetre_jours_apres=3,
        )

    def test_score_maximal(self):
        candidat = {
            "ecart_montant": 0,
            "tolerance": 1000,
            "ecart_jours": 0,
            "reference_correspond": True,
            "sens_verifie": True,
        }

        resultat = calculer_score(candidat, self.regle)

        self.assertEqual(resultat["score"], 100)

    def test_score_sans_reference(self):
        candidat = {
            "ecart_montant": 0,
            "tolerance": 1000,
            "ecart_jours": 0,
            "reference_correspond": False,
            "sens_verifie": True,
        }

        resultat = calculer_score(candidat, self.regle)

        self.assertEqual(resultat["score"], 75)

    def test_score_baisse_si_montant_ecarte(self):
        candidat = {
            "ecart_montant": 800,
            "tolerance": 1000,
            "ecart_jours": 0,
            "reference_correspond": True,
            "sens_verifie": True,
        }

        resultat = calculer_score(candidat, self.regle)

        self.assertEqual(resultat["score"], 68)

    def test_classement_du_meilleur_candidat(self):
        candidats = [
            {
                "ecart_montant": 800,
                "tolerance": 1000,
                "ecart_jours": 1,
                "reference_correspond": False,
                "sens_verifie": True,
            },
            {
                "ecart_montant": 0,
                "tolerance": 1000,
                "ecart_jours": 0,
                "reference_correspond": True,
                "sens_verifie": True,
            },
        ]

        resultats = classer_candidats(candidats, self.regle)

        self.assertEqual(resultats[0]["score_correspondance"], 100)
        self.assertGreaterEqual(
            resultats[0]["score_correspondance"],
            resultats[1]["score_correspondance"],
        )
