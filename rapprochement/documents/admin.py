from django.contrib import admin

from documents.models import LigneDocument, TypeDocument


@admin.register(TypeDocument)
class TypeDocumentAdmin(admin.ModelAdmin):
    list_display = ("nom", "sens", "actif", "cree_le")


@admin.register(LigneDocument)
class LigneDocumentAdmin(admin.ModelAdmin):
    list_display = ("type_document", "date_transaction", "numero_compte", "debit", "credit", "lot")
    list_filter = ("type_document",)
    search_fields = ("numero_compte",)
