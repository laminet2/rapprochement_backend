from django.contrib import admin
from .models import TransactionValorix

# Register your models here.
class TransactioonValorixAdmin(admin.ModelAdmin):
    list_display = [field.name for field in TransactionValorix._meta.fields]