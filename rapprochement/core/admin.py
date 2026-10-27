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
    
        "prendre_banque_anciennes",
        "prendre_valorix_anciennes"
    )
    search_fields = ('nom',)


@admin.register(Rapprochement)
class RapprochementAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'statut_validation',
        'resultat',
        'score_correspondance',
        'ecart_montant',
        'cree_le',
    )
    list_filter = (
        'statut_validation',
        'resultat',
        'cree_le'
    )
    search_fields = (
        'id',
        'commentaire',
    )
    readonly_fields = (
        'cree_le',
        'valide_le',
        'ecart_montant',
        'score_correspondance',
        'score_details',
    )
    inlines = [TransactionBancaireInline, TransactionValorixInline]
    
    fieldsets = (
        ("Informations Générales", {
            'fields': ('statut_validation', 'resultat', 'commentaire')
        }),
        ("Scores et Analyse", {
            'fields': ('score_correspondance', 'ecart_montant', 'score_details')
        }),
        ("Traçabilité", {
            'fields': ('cree_le', 'valide_le')
        }),
    )