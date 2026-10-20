# Fichier: sales/views.py 

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q, Sum
from .models import Sale, Customer
from . import services
from .forms import CustomerForm
from medications.models import Medication
import json
import logging

logger = logging.getLogger(__name__)


@login_required
@permission_required('sales.add_sale', raise_exception=True)
def pos_view(request):
    """Interface de Point de Vente (POS)"""
    # Seuls les médicaments en stock et non périmés sont proposés à la caisse.
    medications = Medication.objects.sellable().select_related('category')
    customers = Customer.objects.all()
    
    context = {
        'medications': medications,
        'customers': customers,
        'max_discount': services.MAX_DISCOUNT,
    }
    return render(request, 'sales/pos.html', context)


@login_required
@permission_required('sales.add_sale', raise_exception=True)
def search_medication(request):
    """API de recherche de médicaments pour le POS"""
    query = request.GET.get('q', '')
    
    if query:
        medications = Medication.objects.sellable().filter(
            Q(name__icontains=query) |
            Q(dci__icontains=query) |
            Q(barcode__icontains=query)
        )[:10]
        
        results = []
        for med in medications:
            results.append({
                'id': med.id,
                'name': med.name,
                'dci': med.dci,
                'price': float(med.selling_price),
                'quantity': med.quantity,
                'image': med.image_display,
                'requires_prescription': med.requires_prescription,
            })
        
        return JsonResponse({'results': results})
    
    return JsonResponse({'results': []})


@login_required
@permission_required('sales.add_sale', raise_exception=True)
@require_POST
def create_sale(request):
    """Créer une vente (API de finalisation de la caisse)."""
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'success': False, 'message': "Requête invalide."}, status=400)

    try:
        sale = services.create_sale(request.user, data)
    except services.SaleError as e:
        # Message métier rédigé par nous : il peut être montré au vendeur.
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    except Exception:
        logger.exception("Échec inattendu lors de la création d'une vente")
        return JsonResponse({
            'success': False,
            'message': "Une erreur inattendue est survenue. La vente n'a pas été enregistrée.",
        }, status=500)

    return JsonResponse({
        'success': True,
        'sale_id': sale.id,
        'sale_number': sale.sale_number,
        'message': f'Vente #{sale.sale_number} créée avec succès !'
    })


@login_required
@permission_required('sales.view_sale', raise_exception=True)
def sale_list(request):
    """Liste des ventes (Historique)"""
    # Filtrer UNIQUEMENT les ventes COMPLÉTÉES pour l'historique
    sales = Sale.objects.filter(status='completee').order_by('-created_at')
    
    # Filtres
    search = request.GET.get('search', '')
    if search:
        sales = sales.filter(
            Q(sale_number__icontains=search) |
            Q(customer__first_name__icontains=search) |
            Q(customer__last_name__icontains=search)
        )
    
    date_filter = request.GET.get('date', '')
    if date_filter:
        sales = sales.filter(created_at__date=date_filter)
    
    # Statistiques
    total_sales = sales.aggregate(total=Sum('total'))['total'] or 0
    
    context = {
        'sales': sales,
        'total_sales': total_sales,
        'search': search,
        'date_filter': date_filter,
    }
    return render(request, 'sales/sale_list.html', context)


@login_required
@permission_required('sales.view_sale', raise_exception=True)
def sale_detail(request, pk):
    """Détails d'une vente"""
    sale = get_object_or_404(Sale, pk=pk)
    
    context = {
        'sale': sale,
    }
    return render(request, 'sales/sale_detail.html', context)


@login_required
@permission_required('sales.view_sale', raise_exception=True)
def sale_invoice(request, pk):
    """Générer une facture"""
    sale = get_object_or_404(Sale, pk=pk)
    
    context = {
        'sale': sale,
    }
    return render(request, 'sales/invoice.html', context)


@login_required
@permission_required('sales.view_customer', raise_exception=True)
def customer_list(request):
    """Liste des clients"""
    customers = Customer.objects.all()
    
    search = request.GET.get('search', '')
    if search:
        customers = customers.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(phone__icontains=search)
        )
    
    context = {
        'customers': customers,
        'search': search,
    }
    return render(request, 'sales/customer_list.html', context)


@login_required
@permission_required('sales.add_customer', raise_exception=True)
def customer_create(request):
    """Créer un client"""
    form = CustomerForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        customer = form.save()
        messages.success(request, f'Client "{customer.full_name}" créé avec succès !')
        return redirect('customer_list')
    return render(request, 'sales/customer_form.html', {'form': form})


@login_required
@permission_required('sales.view_customer', raise_exception=True)
def customer_detail(request, pk):
    """Détails d'un client"""
    customer = get_object_or_404(Customer, pk=pk)
    # On filtre pour afficher uniquement les 10 dernières ventes complétées
    sales = customer.sales.filter(status='completee').order_by('-created_at')[:10]
    
    # Statistiques: On agrège uniquement le total des ventes complétées
    total_spent = customer.sales.filter(status='completee').aggregate(total=Sum('total'))['total'] or 0
    
    context = {
        'customer': customer,
        'sales': sales,
        'total_spent': total_spent,
    }
    return render(request, 'sales/customer_detail.html', context)


@login_required
@permission_required('sales.change_customer', raise_exception=True)
def customer_update(request, pk):
    """Mise à jour du client existant"""
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer, user=request.user)
    if request.method == 'POST' and form.is_valid():
        customer = form.save()
        messages.success(request, f'Client "{customer.full_name}" mis à jour avec succès !')
        return redirect('customer_detail', pk=customer.pk)
    return render(request, 'sales/customer_form.html', {'form': form, 'customer': customer})


@login_required
@permission_required('sales.view_customer', raise_exception=True)
def customer_sales(request, pk):
    """Vue pour lister TOUTES les ventes d'un client (implémentation minimale)"""
    customer = get_object_or_404(Customer, pk=pk)
    
    # Récupère toutes les ventes complétées pour ce client
    all_sales = customer.sales.filter(status='completee').order_by('-created_at')
    
    context = {
        'customer': customer,
        'sales': all_sales,
        'total_sales': all_sales.aggregate(total=Sum('total'))['total'] or 0,
    }
    return render(request, 'sales/sale_list.html', context) # Utilisation temporaire de sale_list.html