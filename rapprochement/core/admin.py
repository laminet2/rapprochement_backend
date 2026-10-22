from django.contrib import admin
from core.models import (
    RegleMatching,
    Rapprochement,
    TransactionBancaireRapprochee,
    TransactionValorixRapprochee,
)


class TransactionBancaireInline(admin.TabularInline):
    model = TransactionBancaireRapprochee
    extra = 0
    readonly_fields = ('transaction_id',)


class TransactionValorixInline(admin.TabularInline):
    model = TransactionValorixRapprochee
    extra = 0
    readonly_fields = ('transaction_id',)


@admin.register(RegleMatching)
class RegleMatchingAdmin(admin.ModelAdmin):
    list_display = (
        'nom',
        'fenetre_jours_avant',
        'fenetre_jours_apres',
        'tolerance_fixe',
        'tolerance_pourcentage',
        'default_regle',
        "prendre_banque_anciennes",
        "prendre_valorix_anciennes"
    )
    list_editable = ('default_regle',)
    search_fields = ('nom',)


@admin.register(Rapprochement)
class RapprochementAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'statut_validation',
        'resultat',
        'score_correspondance',
        'ecart_montant',
        'regle',
        'valide_par',
        'cree_le',
    )
    list_filter = (
        'statut_validation',
        'resultat',
        'cree_le',
        'regle',
    )
    search_fields = (
        'id',
        'commentaire',
        'valide_par__username',
    )
    readonly_fields = (
        'cree_le',
        'valide_le',
        'valide_par',
        'ecart_montant',
        'score_correspondance',
        'score_details',
    )
    inlines = [TransactionBancaireInline, TransactionValorixInline]
    
    fieldsets = (
        ("Informations Générales", {
            'fields': ('statut_validation', 'resultat', 'regle', 'commentaire')
        }),
        ("Scores et Analyse", {
            'fields': ('score_correspondance', 'ecart_montant', 'score_details')
        }),
        ("Traçabilité", {
            'fields': ('cree_le', 'valide_le', 'valide_par')
        }),
    )