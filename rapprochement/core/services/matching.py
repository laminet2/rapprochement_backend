
from core.services.candidats import rechercher_candidats_bancaires
from core.services.scoring import classer_candidats


def rechercher_et_classer(
    transaction_valorix,
    regle,
    sens_banque_par_type=None,
):
    candidats = rechercher_candidats_bancaires(
        transaction_valorix=transaction_valorix,
        regle=regle,
        sens_banque_par_type=sens_banque_par_type,
    )

    return classer_candidats(candidats, regle)
