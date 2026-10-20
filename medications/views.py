from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.db import transaction
from datetime import timedelta

from django.db.models import F, Q, ProtectedError
from django.utils import timezone
from .models import Medication, Category, StockMovement
from .forms import CategoryForm, MedicationForm, StockMovementForm
from .stock import StockError, apply_movement


@login_required
@permission_required('medications.view_medication', raise_exception=True)
def medication_list(request):
    """Liste des médicaments avec recherche et filtres"""
    medications = Medication.objects.select_related('category')
    categories = Category.objects.all()
    
    # Recherche
    search = request.GET.get('search', '')
    if search:
        medications = medications.filter(
            Q(name__icontains=search) |
            Q(dci__icontains=search) |
            Q(barcode__icontains=search)
        )
    
    # Filtres
    category_filter = request.GET.get('category', '')
    if category_filter:
        medications = medications.filter(category_id=category_filter)
    
    # Filtres de stock calculés en base (mêmes règles que is_low_stock,
    # is_expired et is_expiring_soon) : le résultat reste un queryset.
    stock_filter = request.GET.get('stock', '')
    today = timezone.localdate()
    if stock_filter == 'low':
        medications = medications.filter(quantity__lte=F('min_quantity'))
    elif stock_filter == 'expired':
        medications = medications.filter(expiry_date__lt=today)
    elif stock_filter == 'expiring':
        medications = medications.filter(expiry_date__gt=today, expiry_date__lte=today + timedelta(days=30))
    
    context = {
        'medications': medications,
        'categories': categories,
        'search': search,
        'category_filter': category_filter,
        'stock_filter': stock_filter,
    }
    return render(request, 'medications/medication_list.html', context)


@login_required
@permission_required('medications.view_medication', raise_exception=True)
def medication_detail(request, pk):
    """Détails d'un médicament"""
    medication = get_object_or_404(Medication, pk=pk)
    movements = medication.movements.all()[:10]  # 10 derniers mouvements
    
    context = {
        'medication': medication,
        'movements': movements,
    }
    return render(request, 'medications/medication_detail.html', context)


@login_required
@permission_required('medications.add_medication', raise_exception=True)
def medication_create(request):
    """Créer un nouveau médicament (le stock initial devient un mouvement d'entrée)."""
    form = MedicationForm(request.POST or None, request.FILES or None)

    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            medication = form.save(commit=False)
            medication.created_by = request.user
            medication.quantity = 0
            medication.save()
            initial_quantity = form.cleaned_data.get('quantity') or 0
            if initial_quantity:
                apply_movement(medication, 'entrée', initial_quantity, user=request.user, reason="Stock initial")
        messages.success(request, f'Médicament "{medication.name}" créé avec succès ! ✅')
        return redirect('medication_detail', pk=medication.pk)

    context = {
        'form': form,
        'categories': Category.objects.all(),
        'form_choices': Medication.FORM_CHOICES,
    }
    return render(request, 'medications/medication_form.html', context)


@login_required
@permission_required('medications.change_medication', raise_exception=True)
def medication_update(request, pk):
    """Modifier la fiche d'un médicament (le stock ne change que par un mouvement)."""
    medication = get_object_or_404(Medication, pk=pk)
    form = MedicationForm(request.POST or None, request.FILES or None, instance=medication)

    if request.method == 'POST' and form.is_valid():
        medication = form.save()
        messages.success(request, f'Médicament "{medication.name}" modifié avec succès ! ✅')
        return redirect('medication_detail', pk=medication.pk)

    context = {
        'form': form,
        'medication': medication,
        'categories': Category.objects.all(),
        'form_choices': Medication.FORM_CHOICES,
        'is_update': True,
    }
    return render(request, 'medications/medication_form.html', context)


@login_required
@permission_required('medications.delete_medication', raise_exception=True)
def medication_delete(request, pk):
    """Supprimer un médicament"""
    medication = get_object_or_404(Medication, pk=pk)
    
    if request.method == 'POST':
        name = medication.name
        try:
            medication.delete()
            messages.success(request, f'Médicament "{name}" supprimé avec succès ! 🗑️')
        except ProtectedError:
            # Le médicament est lié à des ventes : on protège l'historique.
            messages.error(
                request,
                f'Impossible de supprimer "{name}" : il est rattaché à des ventes existantes. '
                f'Vous pouvez le désactiver ou ajuster son stock à la place.'
            )
        return redirect('medication_list')
    
    context = {
        'medication': medication,
    }
    return render(request, 'medications/medication_confirm_delete.html', context)


@login_required
@permission_required('medications.view_category', raise_exception=True)
def category_list(request):
    """Liste des catégories"""
    categories = Category.objects.all()
    
    # 🚨 DÉBUT DE LA MODIFICATION 🚨
    # Calcule le nombre total de médicaments dans la base de données
    total_medications = Medication.objects.count()
    
    context = {
        'categories': categories,
        'total_medications': total_medications, # Ajout de la variable dans le contexte
    }
    # 🚨 FIN DE LA MODIFICATION 🚨
    
    return render(request, 'medications/category_list.html', context)


@login_required
@permission_required('medications.add_category', raise_exception=True)
def category_create(request):
    """Créer une catégorie"""
    form = CategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        category = form.save()
        messages.success(request, f'Catégorie "{category.name}" créée avec succès ! ✅')
        return redirect('category_list')
    return render(request, 'medications/category_form.html', {'form': form})


@login_required
@permission_required('medications.change_category', raise_exception=True)
def category_update(request, pk):
    """Modifier une catégorie existante"""
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        category = form.save()
        messages.success(request, f'✅ Catégorie "{category.name}" modifiée avec succès !')
        return redirect('category_list')
    return render(request, 'medications/category_update.html', {
        'form': form,
        'category': category,
        'title': 'Modifier la Catégorie',
        'action': 'update'
    })


# ✅ NOUVELLE VUE DE SUPPRESSION
@login_required
@permission_required('medications.delete_category', raise_exception=True)
def category_delete(request, pk):
    """Supprimer une catégorie"""
    category = get_object_or_404(Category, pk=pk)
    
    # Vérifier si la catégorie a des médicaments
    medications_count = category.medications.count()
    
    if request.method == 'POST':
        category_name = category.name
        category.delete()
        messages.success(request, f'✅ Catégorie "{category_name}" supprimée avec succès !')
        return redirect('category_list')
    
    return render(request, 'medications/category_confirm_delete.html', {
        'category': category,
        'medications_count': medications_count
    })

@login_required
@permission_required('medications.add_stockmovement', raise_exception=True)
def stock_movement_create(request, medication_pk):
    """Créer un mouvement de stock (seul moyen de modifier la quantité)."""
    medication = get_object_or_404(Medication, pk=medication_pk)
    form = StockMovementForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        try:
            apply_movement(
                medication,
                form.cleaned_data['movement_type'],
                form.cleaned_data['quantity'],
                user=request.user,
                reason=form.cleaned_data['reason'],
                reference=form.cleaned_data['reference'],
            )
        except StockError as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, 'Mouvement de stock enregistré avec succès ! ✅')
            return redirect('medication_detail', pk=medication.pk)

    context = {
        'medication': medication,
        'form': form,
        'movement_types': StockMovement.MOVEMENT_TYPES,
    }
    return render(request, 'medications/stock_movement_form.html', context)
