from django.contrib import admin

# Register your models here.
from .models import Banque, CompteBancaire, TransactionBancaire

@admin.register(Banque)
class BanqueAdmin(admin.ModelAdmin):
    list_display = ('id', 'nom')
    search_fields = ('nom',)

@admin.register(CompteBancaire)
class CompteBancaireAdmin(admin.ModelAdmin):
    list_display = ('id', 'banque', 'numero_compte', 'devise')
    list_filter = ('banque',)
    search_fields = ('numero_compte',)

@admin.register(TransactionBancaire)
class TransactionBancaireAdmin(admin.ModelAdmin):
    list_display = ('id', 'compte', 'date_transaction', 'type_transaction', 'debit', 'credit', 'statut')
    list_filter = ( 'statut','type_transaction', 'compte__banque')
    search_fields = ('libelle_brut', 'reference_bancaire')
    date_hierarchy = 'date_transaction'