PROMPT_DOCUMENT = """
Tu extrais les lignes d'un document tabulaire contenant au minimum les
colonnes : numéro de compte client, date de transaction, montant net.

RÈGLES STRICTES :
1. N'invente aucune ligne ni aucune valeur.
2. Ignore titres, en-têtes, totaux, sous-totaux et numéros de page.
3. Recopie le numéro de compte tel qu'il est écrit.
4. Écris la date au format YYYY-MM-DD.
5. Recopie le montant net tel qu'écrit, sans devise ni séparateur de
   milliers superflu.
6. Une ligne = une transaction. Ne fusionne rien.

Retourne exclusivement les données conformes au schéma structuré.
"""
