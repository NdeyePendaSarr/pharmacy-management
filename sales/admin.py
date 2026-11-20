from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from .models import Customer, Sale, SaleItem, Prescription


class ReadOnlyAdminMixin:
    """
    Consultation seule dans l'admin, y compris pour un superutilisateur.

    Une vente ne se crée qu'à la caisse (sales.services.create_sale), qui
    met à jour le stock, l'encours de crédit et l'ordonnance dans la même
    transaction. Ajouter, modifier ou supprimer une vente, une ligne ou une
    ordonnance depuis l'admin contournerait ces règles : le stock et les
    mouvements, les totaux ou la traçabilité deviendraient faux.
    """

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SaleItemInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = SaleItem
    extra = 0
    can_delete = False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'customer_type', 'loyalty_points', 'current_credit', 'credit_limit', 'is_active')
    list_filter = ('is_active', 'customer_type')
    search_fields = ('first_name', 'last_name', 'phone', 'email')
    # L'encours de crédit n'évolue que par les ventes à crédit (caisse) :
    # le modifier à la main effacerait ou inventerait une dette.
    # L'archivage passe par les actions « Archiver » / « Réactiver ».
    readonly_fields = ('current_credit', 'is_active', 'archived_at')
    actions = ['archive_customers', 'reactivate_customers']

    def get_actions(self, request):
        # Pas de suppression groupée : elle contournerait le contrôle client
        # par client de delete_view.
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    @admin.action(description="Archiver les clients sélectionnés (historique conservé)", permissions=['change'])
    def archive_customers(self, request, queryset):
        count = queryset.filter(is_active=True).update(is_active=False, archived_at=timezone.now())
        self.message_user(
            request,
            f"{count} client(s) archivé(s) : masqués de la liste et de la caisse, ventes, ordonnances et crédit conservés.",
            messages.SUCCESS,
        )

    @admin.action(description="Réactiver les clients sélectionnés", permissions=['change'])
    def reactivate_customers(self, request, queryset):
        count = queryset.filter(is_active=False).update(is_active=True, archived_at=None)
        self.message_user(request, f"{count} client(s) réactivé(s).", messages.SUCCESS)

    def delete_view(self, request, object_id, extra_context=None):
        # Un client avec un historique n'est jamais supprimé : on explique
        # pourquoi et on propose l'archivage, au lieu d'une erreur brute.
        customer = self.get_object(request, unquote(object_id))
        if customer is not None:
            reasons = customer.deletion_blockers()
            if reasons:
                self.message_user(
                    request,
                    f"Impossible de supprimer « {customer.full_name} » : ce client a {', '.join(reasons)}. "
                    "Son historique doit être conservé. Utilisez l'action « Archiver » pour le retirer "
                    "de la liste et de la caisse.",
                    messages.ERROR,
                )
                return redirect(reverse('admin:sales_customer_change', args=[customer.pk]))
        return super().delete_view(request, object_id, extra_context)


@admin.register(Sale)
class SaleAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ('sale_number', 'customer', 'total', 'payment_method', 'status', 'created_at', 'created_by')
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('sale_number', 'customer__first_name', 'customer__last_name')
    inlines = [SaleItemInline]


@admin.register(SaleItem)
class SaleItemAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ('sale', 'medication', 'quantity', 'unit_price', 'subtotal')
    search_fields = ('sale__sale_number', 'medication__name')


@admin.register(Prescription)
class PrescriptionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ('customer', 'doctor_name', 'prescription_date', 'sale', 'created_at')
    list_filter = ('prescription_date',)
    search_fields = ('customer__first_name', 'customer__last_name', 'doctor_name')
