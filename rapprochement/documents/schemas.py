"""Schéma Pydantic pour l'extraction LLM d'un document PDF."""

from pydantic import BaseModel, Field


class LigneDocumentExtraite(BaseModel):
    numero_compte_client: str = Field(description="Numéro de compte du client.")
    date_transaction: str = Field(description="Date de la transaction au format YYYY-MM-DD.")
    montant_net: str = Field(
        description="Montant net tel qu'écrit dans le document (nombre, sans devise)."
    )


class ExtractionDocument(BaseModel):
    transactions: list[LigneDocumentExtraite] = Field(
        description="Toutes les lignes du document, dans l'ordre."
    )
