from django.contrib import admin
from .models import Category, Medication, StockMovement

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_at')
    search_fields = ('name',)

@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    list_display = ('name', 'dci', 'category', 'form', 'dosage', 'quantity', 'selling_price', 'expiry_date')
    list_filter = ('category', 'form', 'requires_prescription')
    search_fields = ('name', 'dci')
    # Le stock ne change que par des mouvements (medications.stock.apply_movement).
    readonly_fields = ('quantity', 'created_at', 'updated_at')

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('medication', 'movement_type', 'quantity', 'reason', 'reference', 'created_at', 'created_by')
    list_filter = ('movement_type', 'medication')
    search_fields = ('medication__name', 'reason', 'reference')
    readonly_fields = ('created_at',)

    # Historique en lecture seule : un mouvement saisi ici ne mettrait pas le
    # stock à jour. Les mouvements se créent depuis la fiche du médicament.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
