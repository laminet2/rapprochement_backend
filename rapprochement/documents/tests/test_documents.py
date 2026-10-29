import io
from datetime import date, datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APITestCase

from core.models import Rapprochement, RegleMatching
from core.services.decision import decision_groupee
from core.services.proposition import generer_toutes_les_propositions
from core.services.validation import valider_rapprochement
from core.tests.factories import (
    creer_regle, creer_type_document, ligne_document, tx_banque, tx_valorix,
)
from documents.importers import detecter_colonnes
from documents.models import LigneDocument, TypeDocument
from importation.models import LotImport


def xlsx(lignes):
    wb = Workbook()
    for l in lignes:
        wb.active.append(l)
    s = io.BytesIO()
    wb.save(s)
    return s.getvalue()


def fichier(nom, contenu):
    return SimpleUploadedFile(nom, contenu)


class TypeDocumentApiTests(APITestCase):
    def creer(self, **extra):
        return self.client.post(
            "/documents/types/",
            {"nom": "Orange Money", "sens": "CREDIT", "types_valorix": ["DEPOT_ESPECES", "TRANSFERT"], **extra},
            format="json",
        )

    def test_creation_cree_une_regle_par_type_valorix(self):
        r = self.creer()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(sorted(r.data["types_valorix"]), ["DEPOT_ESPECES", "TRANSFERT"])
        regles = RegleMatching.objects.filter(type_document_id=r.data["id"])
        self.assertEqual(regles.count(), 2)
        self.assertTrue(all(x.sens_transaction_document_cible == "CREDIT" for x in regles))

    def test_nom_unique(self):
        self.creer()
        self.assertEqual(self.creer().status_code, 400)

    def test_types_valorix_inconnus_refuses(self):
        self.assertEqual(self.creer(types_valorix=["INCONNU"]).status_code, 400)

    def test_sens_modifiable_tant_qu_il_n_y_a_pas_de_lignes(self):
        id_ = self.creer().data["id"]
        r = self.client.patch(f"/documents/types/{id_}/", {"sens": "DEBIT"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            set(RegleMatching.objects.filter(type_document_id=id_).values_list("sens_transaction_document_cible", flat=True)),
            {"DEBIT"},
        )
        ligne_document(TypeDocument.objects.get(pk=id_), date(2026, 11, 2), 100)
        r2 = self.client.patch(f"/documents/types/{id_}/", {"sens": "CREDIT"}, format="json")
        self.assertEqual(r2.status_code, 400)

    def test_suppression_refusee_si_lignes(self):
        id_ = self.creer().data["id"]
        ligne_document(TypeDocument.objects.get(pk=id_), date(2026, 11, 2), 100)
        self.assertEqual(self.client.delete(f"/documents/types/{id_}/").status_code, 409)

    def test_suppression_ok_supprime_ses_regles(self):
        id_ = self.creer().data["id"]
        self.assertEqual(self.client.delete(f"/documents/types/{id_}/").status_code, 204)
        self.assertEqual(RegleMatching.objects.count(), 0)

    def test_liste_avec_compteurs(self):
        id_ = self.creer().data["id"]
        ligne_document(TypeDocument.objects.get(pk=id_), date(2026, 11, 2), 100)
        r = self.client.get("/documents/types/")
        self.assertEqual(r.data[0]["nombre_lignes"], 1)
        self.assertEqual(r.data[0]["lignes_non_rapprochees"], 1)


class ImportDocumentTests(APITestCase):
    def setUp(self):
        self.type = creer_type_document("Wave", "CREDIT")

    def extraire(self, nom, contenu):
        return self.client.post(
            f"/documents/types/{self.type.id}/extraire/", {"fichier": fichier(nom, contenu)}, format="multipart"
        )

    def test_detection_de_colonnes_tolerante(self):
        cols, manquantes = detecter_colonnes(["N° de compte client", "Date de transaction", "Montant Net (XOF)"])
        self.assertEqual((manquantes, cols), ([], {"montant": 2, "compte": 0, "date": 1}))

    def test_excel_valide(self):
        r = self.extraire("doc.xlsx", xlsx([
            ["Rapport"], ["Numéro compte client", "Date transaction", "Montant net"],
            ["0012345678", datetime(2026, 11, 2), 750], ["0099887766", "03/11/2026", "1 250,50"],
            ["Total", None, 2000.5],
        ]))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["nombre_lignes"], 2)
        self.assertEqual(r.data["data"][0]["date_transaction"], "2026-11-02")
        self.assertEqual(r.data["data"][1]["montant"], "1250.50")
        self.assertEqual(r.data["sens"], "CREDIT")

    def test_colonne_manquante(self):
        r = self.extraire("doc.xlsx", xlsx([["Numéro compte client", "Date transaction"], ["1", "2026-01-01"]]))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Montant net", r.data["detail"])

    def test_csv_et_montant_negatif(self):
        r = self.extraire("d.csv", "Compte client;Date;Montant net\n0012;2026-11-02;750\n0013;2026-11-02;-5\n".encode())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.data["nombre_lignes"], r.data["nombre_erreurs"]), (2, 1))

    def test_type_inconnu(self):
        r = self.client.post("/documents/types/999/extraire/", {"fichier": fichier("a.csv", b"x")}, format="multipart")
        self.assertEqual(r.status_code, 404)

    def test_enregistrement_doublons_et_sens(self):
        corps = {
            "type_document": self.type.id, "nom_fichier": "wave.csv", "ignorer_doublons": True,
            "transactions": [
                {"numero_compte": "0012", "date_transaction": "2026-11-02", "montant": "750"},
                {"numero_compte": "0012", "date_transaction": "2026-11-02", "montant": "750"},
            ],
        }
        r = self.client.post("/documents/save/", corps, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["nombre_enregistrees"], 2)  # deux lignes identiques dans le fichier
        ligne = LigneDocument.objects.first()
        self.assertEqual((ligne.credit, ligne.debit), (750, None))
        lot = LotImport.objects.get(pk=r.data["lot"])
        self.assertEqual((lot.source, lot.details["nom"]), ("DOCUMENT", "Wave"))

        r2 = self.client.post("/documents/save/", corps, format="json")
        self.assertEqual((r2.data["nombre_enregistrees"], r2.data["nombre_ignorees_doublons"]), (0, 2))

    def test_apercu_marque_les_doublons(self):
        ligne_document(self.type, date(2026, 11, 2), 750, compte="0012")
        r = self.extraire("d.csv", b"Compte;Date;Montant net\n0012;2026-11-02;750\n")
        self.assertEqual(r.data["nombre_doublons"], 1)

    def test_type_inactif_refuse(self):
        self.type.actif = False
        self.type.save()
        r = self.client.post("/documents/save/", {
            "type_document": self.type.id,
            "transactions": [{"numero_compte": "1", "date_transaction": "2026-11-02", "montant": "5"}],
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_modele_et_colonnes(self):
        self.assertEqual(self.client.get("/documents/modele/").status_code, 200)
        self.assertEqual(len(self.client.get("/documents/colonnes/").data["colonnes_obligatoires"]), 3)

    def test_annulation_du_lot_supprime_les_lignes(self):
        r = self.client.post("/documents/save/", {
            "type_document": self.type.id,
            "transactions": [{"numero_compte": "1", "date_transaction": "2026-11-02", "montant": "5"}],
        }, format="json")
        a = self.client.post(f"/imports/{r.data['lot']}/annuler/")
        self.assertEqual(a.status_code, 200, a.content)
        self.assertEqual(LigneDocument.objects.count(), 0)


class RapprochementDocumentTests(APITestCase):
    """Valorix (référence) rapproché avec un document nommé, indépendamment de la banque."""

    def setUp(self):
        self.doc = creer_type_document("Orange Money", "CREDIT")
        creer_regle(types="DEPOT_ESPECES", document=self.doc, avant=1, apres=1)
        creer_regle(types="DEPOT_ESPECES", sens="CREDIT", avant=1, apres=1)  # règle banque

    def test_une_ligne_valorix_contre_une_ligne_document(self):
        v = tx_valorix(date(2026, 11, 2), 750, "DEBIT", types="DEPOT_ESPECES", compte="0012345678")
        ligne_document(self.doc, date(2026, 11, 2), 750, compte="12345678")  # zéros de tête ignorés
        bilan = generer_toutes_les_propositions()
        self.assertEqual(bilan["propositions_creees"], 1)

        r = Rapprochement.objects.get()
        self.assertEqual(r.type_document_id, self.doc.id)
        self.assertEqual(r.score_correspondance, 100)  # normalisé : ni référence ni nom
        self.assertFalse(r.score_details["reference"]["disponible"])
        self.assertFalse(r.score_details["nom_client"]["disponible"])
        self.assertTrue(r.score_details["compte"]["correspond"])
        self.assertEqual(r.regle_snapshot["source_nom"], "Orange Money")

        valider_rapprochement(r.pk)
        r.refresh_from_db()
        self.assertEqual(r.statut_validation, "VALIDE")

    def test_compte_different_perd_des_points(self):
        tx_valorix(date(2026, 11, 2), 750, "DEBIT", types="DEPOT_ESPECES", compte="0012345678")
        ligne_document(self.doc, date(2026, 11, 2), 750, compte="9999")
        generer_toutes_les_propositions()
        r = Rapprochement.objects.get()
        self.assertLess(r.score_correspondance, 100)
        self.assertFalse(r.score_details["compte"]["correspond"])

    def test_regroupement_un_document_contre_plusieurs_valorix(self):
        for m in (100, 200):
            tx_valorix(date(2026, 11, 2), m, "DEBIT", types="DEPOT_ESPECES", compte="0012")
        ligne_document(self.doc, date(2026, 11, 2), 300, compte="0012")
        generer_toutes_les_propositions()
        r = Rapprochement.objects.get()
        self.assertEqual(r.score_details["type_rapprochement"], "1-N")
        valider_rapprochement(r.pk)

    def test_banque_et_document_sont_deux_sources_distinctes(self):
        tx_valorix(date(2026, 11, 2), 750, "DEBIT", types="DEPOT_ESPECES", compte="0012")
        tx_banque(date(2026, 11, 2), 750, "CREDIT")
        ligne_document(self.doc, date(2026, 11, 2), 750, compte="0012")
        generer_toutes_les_propositions()
        sources = {r.type_document_id for r in Rapprochement.objects.all()}
        self.assertEqual(sources, {None, self.doc.id})
        # Les deux propositions se disputent la même ligne Valorix : conflit signalé.
        liste = self.client.get("/rapprochements/?ordering=-score").data["results"]
        self.assertTrue(all(r["en_conflit"] for r in liste))
        bilan = decision_groupee()
        self.assertEqual((len(bilan["valides"]), len(bilan["conflits"])), (1, 1))

    def test_lot_document_ne_relance_que_les_regles_du_document(self):
        lot = LotImport.objects.create(source="DOCUMENT")
        tx_valorix(date(2026, 11, 2), 750, "DEBIT", types="DEPOT_ESPECES", compte="0012")
        tx_banque(date(2026, 11, 2), 750, "CREDIT")
        ligne_document(self.doc, date(2026, 11, 2), 750, compte="0012", lot=lot)
        bilan = generer_toutes_les_propositions(lot_document_ids=[lot.id])
        self.assertEqual([b["source"] for b in bilan["details_par_type"]], ["Orange Money"])

    def test_api_liste_et_detail(self):
        tx_valorix(date(2026, 11, 2), 750, "DEBIT", types="DEPOT_ESPECES", compte="0012")
        ligne_document(self.doc, date(2026, 11, 2), 750, compte="0012")
        self.client.post("/rapprochements/generer/", {}, format="json")
        liste = self.client.get(f"/rapprochements/?type_document={self.doc.id}")
        self.assertEqual(liste.data["count"], 1)
        item = liste.data["results"][0]
        self.assertEqual(item["source_contrepartie"], {"type": "DOCUMENT", "type_document": self.doc.id, "nom": "Orange Money"})
        self.assertEqual(item["contrepartie"][0]["source"], "Orange Money")
        self.assertEqual(item["total_contrepartie"], "750.00")
        self.assertEqual(self.client.get("/rapprochements/?source=banque").data["count"], 0)

    def test_rapprochement_manuel_avec_un_document(self):
        v = tx_valorix(date(2026, 11, 2), 750, "DEBIT", types="DEPOT_ESPECES", compte="0012")
        l = ligne_document(self.doc, date(2026, 11, 2), 750, compte="0012")
        corps = {"type_document": self.doc.id, "lignes_document": [l.pk], "transactions_valorix": [str(v.pk)]}
        a = self.client.post("/rapprochements/manuel/apercu/", corps, format="json")
        self.assertEqual(a.status_code, 200, a.content)
        self.assertTrue(a.data["acceptable"])
        r = self.client.post("/rapprochements/manuel/", corps, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["source_contrepartie"]["nom"], "Orange Money")
        # Mélange banque + document refusé
        mauvais = {"type_document": self.doc.id, "lignes_document": [l.pk], "transactions_bancaires": [1],
                   "transactions_valorix": [str(v.pk)]}
        self.assertEqual(self.client.post("/rapprochements/manuel/apercu/", mauvais, format="json").status_code, 400)

    def test_non_rapprochees_et_suppression(self):
        l = ligne_document(self.doc, date(2026, 11, 2), 750)
        r = self.client.get(f"/rapprochements/non-rapprochees/?source=document&type_document={self.doc.id}")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["type_document_nom"], "Orange Money")
        s = self.client.post("/rapprochements/non-rapprochees/supprimer/", {"source": "document", "ids": [l.pk]}, format="json")
        self.assertEqual(s.data["supprimees"], 1)

    def test_statistiques_par_document(self):
        ligne_document(self.doc, date(2026, 11, 2), 750)
        s = self.client.get("/rapprochements/statistiques/")
        self.assertEqual(s.data["documents"][0]["nom"], "Orange Money")
        self.assertEqual(s.data["documents"][0]["non_rapprochees"], 1)

    def test_regle_de_document_prend_le_sens_du_document(self):
        r = self.client.post("/rapprochements/regles/", {
            "type_transaction_valorix": "TRANSFERT", "type_document": self.doc.id,
            "sens_transaction_document_cible": "DEBIT",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["sens_transaction_document_cible"], "CREDIT")
        self.assertEqual(r.data["type_document_nom"], "Orange Money")
        # doublon refusé
        r2 = self.client.post("/rapprochements/regles/", {
            "type_transaction_valorix": "TRANSFERT", "type_document": self.doc.id}, format="json")
        self.assertEqual(r2.status_code, 400)
