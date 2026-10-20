
# core/tests/test_validation.py

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    Rapprochement,
    RegleMatching,
    ResultatMatching,
    StatutValidation,
    TransactionBancaireRapprochee,
    TransactionValorixRapprochee,
)
from core.services.validation import (
    ValidationRapprochementError,
    valider_rapprochement,
)
from releverBancaire.models import (
    Banque,
    CompteBancaire,
    TransactionBancaire,
)
from valorix.models import TransactionValorix


class ValidationRapprochementTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.utilisateur = User.objects.create_user(
            username="test_rapprochement",
            password="test-password",
        )

        self.banque = Banque.objects.create(
            nom="Ecobank Test",
        )

        self.compte_bancaire = CompteBancaire.objects.create(
            banque=self.banque,
            numero_compte="COMPTE-001",
            devise="XOF",
        )

        self.regle = RegleMatching.objects.create(
            nom="Règle dépôt chèque",
            type_transaction_valorix="DEPOT_CHEQUE",
            fenetre_jours_avant=3,
            fenetre_jours_apres=3,
            tolerance_fixe=Decimal("100.00"),
            tolerance_pourcentage=Decimal("1.00"),
            active=True,
        )

        self.transaction_valorix = TransactionValorix.objects.create(
            id=uuid4(),
            numero_transaction="VAL-001",
            date_transaction=datetime(2026, 10, 15, 10, 0),
            numero_compte="CLIENT-001",
            nomComplet="Client Test",
            debit=None,
            credit=Decimal("10000.00"),
            references="9723769",
            types="DEPOT_CHEQUE",
            references_rapprochement="",
        )

        self.transaction_bancaire = TransactionBancaire.objects.create(
            compte=self.compte_bancaire,
            date_transaction=date(2026, 10, 16),
            date_valeur=date(2026, 10, 16),
            reference_rapprochement="9723769",
            libelle_brut="DEPOT CHEQUE CLIENT TEST",
            debit=None,
            credit=Decimal("10000.00"),
            solde_apres_operation=Decimal("50000.00"),
            type_transaction="AUTRE",
        )

    def creer_proposition(
        self,
        transaction_valorix=None,
        transaction_bancaire=None,
        statut=StatutValidation.PROPOSE,
    ):
        """Crée une proposition avec ses deux transactions sources."""

        rapprochement = Rapprochement.objects.create(
            statut_validation=statut,
            resultat=ResultatMatching.CORRESPONDANCE,
            score_correspondance=100,
            ecart_montant=Decimal("0.00"),
            regle=self.regle,
            score_details={"test": True},
        )

        TransactionBancaireRapprochee.objects.create(
            rapprochement=rapprochement,
            transaction=(
                transaction_bancaire or self.transaction_bancaire
            ),
        )

        TransactionValorixRapprochee.objects.create(
            rapprochement=rapprochement,
            transaction=(
                transaction_valorix or self.transaction_valorix
            ),
        )

        return rapprochement

    def test_valider_proposition_correcte(self):
        """Une proposition correcte doit pouvoir être validée."""

        proposition = self.creer_proposition()

        resultat = valider_rapprochement(
            rapprochement_id=proposition.pk,
            utilisateur=self.utilisateur,
        )

        resultat.refresh_from_db()

        self.assertEqual(
            resultat.statut_validation,
            StatutValidation.VALIDE,
        )
        self.assertEqual(resultat.valide_par, self.utilisateur)
        self.assertIsNotNone(resultat.valide_le)

    def test_empecher_double_rapprochement_bancaire(self):
        """Une transaction bancaire déjà validée ne peut être réutilisée."""

        self.creer_proposition(
            statut=StatutValidation.VALIDE,
        )

        autre_valorix = TransactionValorix.objects.create(
            id=uuid4(),
            numero_transaction="VAL-002",
            date_transaction=datetime(2026, 10, 15, 11, 0),
            numero_compte="CLIENT-002",
            nomComplet="Autre Client",
            debit=None,
            credit=Decimal("10000.00"),
            references="9723769",
            types="DEPOT_CHEQUE",
            references_rapprochement="",
        )

        proposition = self.creer_proposition(
            transaction_valorix=autre_valorix,
        )

        with self.assertRaises(ValidationRapprochementError):
            valider_rapprochement(
                rapprochement_id=proposition.pk,
                utilisateur=self.utilisateur,
            )

    def test_refuser_proposition_deja_validee(self):
        """Une proposition déjà validée ne doit pas être validée à nouveau."""

        proposition = self.creer_proposition(
            statut=StatutValidation.VALIDE,
        )

        with self.assertRaises(ValidationRapprochementError):
            valider_rapprochement(
                rapprochement_id=proposition.pk,
                utilisateur=self.utilisateur,
            )
