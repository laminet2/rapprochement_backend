
# core/tests/test_actions.py

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    Rapprochement,
    StatutValidation,
)
from core.services.actions import (
    ActionRapprochementError,
    annuler_rapprochement,
    rejeter_rapprochement,
)


class ActionsRapprochementTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.utilisateur = User.objects.create_user(
            username="gestionnaire_test",
            password="test-password",
        )

        self.rapprochement = Rapprochement.objects.create(
            statut_validation=StatutValidation.PROPOSE,
            resultat="CORRESPONDANCE",
            score_correspondance=85,
            commentaire="Proposition générée par le moteur.",
        )

    def test_rejeter_proposition(self):
        resultat = rejeter_rapprochement(
            rapprochement_id=self.rapprochement.pk,
            utilisateur=self.utilisateur,
            motif="La référence bancaire ne correspond pas.",
        )

        self.assertEqual(
            resultat.statut_validation,
            StatutValidation.REJETE,
        )
        self.assertIn(
            "La référence bancaire ne correspond pas.",
            resultat.commentaire,
        )
        self.assertIn(
            "Proposition générée par le moteur.",
            resultat.commentaire,
        )

    def test_annuler_proposition(self):
        resultat = annuler_rapprochement(
            rapprochement_id=self.rapprochement.pk,
            utilisateur=self.utilisateur,
            motif="Proposition créée en double.",
        )

        self.assertEqual(
            resultat.statut_validation,
            StatutValidation.ANNULE,
        )
        self.assertIn(
            "Proposition créée en double.",
            resultat.commentaire,
        )

    def test_motif_obligatoire(self):
        with self.assertRaises(ActionRapprochementError):
            rejeter_rapprochement(
                rapprochement_id=self.rapprochement.pk,
                utilisateur=self.utilisateur,
                motif=" ",
            )

    def test_impossible_de_rejeter_une_proposition_validee(self):
        self.rapprochement.statut_validation = StatutValidation.VALIDE
        self.rapprochement.save(update_fields=["statut_validation"])

        with self.assertRaises(ActionRapprochementError):
            rejeter_rapprochement(
                rapprochement_id=self.rapprochement.pk,
                utilisateur=self.utilisateur,
                motif="Tentative de rejet tardive.",
            )
