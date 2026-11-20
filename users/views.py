from django.conf import settings
from django.http import Http404
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from datetime import timedelta

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone


def login_view(request):
    """Vue de connexion"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            # « Se souvenir de moi » : sans la case, la session s'arrête à la
            # fermeture du navigateur (poste de caisse partagé) ; avec, elle
            # dure SESSION_COOKIE_AGE (2 semaines par défaut).
            if request.POST.get('remember'):
                request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            else:
                request.session.set_expiry(0)
            messages.success(request, f'Bienvenue {user.username} ! 👋')
            return redirect('dashboard')
        else:
            messages.error(request, 'Nom d\'utilisateur ou mot de passe incorrect.')
    
    return render(request, 'users/login.html', {'allow_registration': settings.ALLOW_REGISTRATION})


def register_view(request):
    """Vue d'inscription (fermée sauf si ALLOW_REGISTRATION=True)"""
    if not settings.ALLOW_REGISTRATION:
        raise Http404("Inscription fermée")
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        
        # Validation
        if password != password_confirm:
            messages.error(request, 'Les mots de passe ne correspondent pas.')
            return render(request, 'users/register.html')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Ce nom d\'utilisateur existe déjà.')
            return render(request, 'users/register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Cet email est déjà utilisé.')
            return render(request, 'users/register.html')
        
        # Vérifier le mot de passe selon les règles définies dans AUTH_PASSWORD_VALIDATORS
        try:
            validate_password(password)
        except ValidationError as e:
            for error in e.messages:
                messages.error(request, error)
            return render(request, 'users/register.html')
        
        # Créer l'utilisateur
        User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        
        messages.success(request, 'Compte créé avec succès ! Vous pouvez maintenant vous connecter.')
        return redirect('login')
    
    return render(request, 'users/register.html')


@require_POST
def logout_view(request):
    """Vue de déconnexion"""
    logout(request)
    messages.info(request, 'Vous êtes déconnecté(e). À bientôt ! 👋')
    return redirect('login')


@login_required
@permission_required('sales.view_sale', raise_exception=True)
def dashboard_view(request):
    """
    Vue du tableau de bord.

    Toutes les statistiques sont calculées en base par des agrégations
    groupées : le nombre de requêtes ne dépend ni du nombre de jours
    affichés ni du volume de ventes.
    """
    from medications.models import Medication
    from sales.models import Sale, SaleItem, Customer

    today = timezone.localdate()
    debut_semaine = today - timedelta(days=today.weekday())   # lundi de cette semaine
    debut_mois = today.replace(day=1)
    debut_7_jours = today - timedelta(days=6)

    # 1) Médicaments : total et alertes de stock, en une requête
    stock = Medication.objects.aggregate(
        total=Count('id'),
        low=Count('id', filter=Q(quantity__lte=F('min_quantity'))),
    )

    # 2) Chiffre d'affaires par période (ventes complétées), en une requête
    ventes_ok = Sale.objects.filter(status='completee')
    ca = ventes_ok.aggregate(
        jour=Sum('total', filter=Q(created_at__date=today)),
        nb_jour=Count('id', filter=Q(created_at__date=today)),
        semaine=Sum('total', filter=Q(created_at__date__gte=debut_semaine)),
        mois=Sum('total', filter=Q(created_at__date__gte=debut_mois)),
        total=Sum('total'),
    )

    # 3) Ventes des 7 derniers jours, groupées par jour, en une requête
    par_jour = {
        row['jour']: row
        for row in ventes_ok.filter(created_at__date__gte=debut_7_jours)
        .annotate(jour=TruncDate('created_at'))
        .values('jour')
        .annotate(montant=Sum('total'), nombre=Count('id'))
    }
    jours = [debut_7_jours + timedelta(days=i) for i in range(7)]
    labels_jours = [jour.strftime('%d/%m') for jour in jours]
    donnees_ventes = [float(par_jour.get(jour, {}).get('montant') or 0) for jour in jours]
    recap_jours = [
        {
            'date': jour.strftime('%d/%m/%Y'),
            'montant': float(par_jour.get(jour, {}).get('montant') or 0),
            'nombre': par_jour.get(jour, {}).get('nombre', 0),
        }
        for jour in reversed(jours)  # plus récent en premier
    ]

    # 4) Top 5 des médicaments les plus vendus (par quantité)
    top_items = (
        SaleItem.objects
        .values('medication__name')
        .annotate(qte=Sum('quantity'))
        .order_by('-qte')[:5]
    )
    labels_produits = [t['medication__name'] for t in top_items]
    donnees_produits = [int(t['qte']) for t in top_items]

    # 5) Clients
    total_customers = Customer.objects.count()

    context = {
        'total_medications': stock['total'],
        'total_sales': ca['nb_jour'],
        'total_sales_amount': ca['jour'] or 0,
        'total_customers': total_customers,
        'low_stock_count': stock['low'],
        # graphiques (sérialisés par le filtre json_script dans le gabarit)
        'chart_sales_labels': labels_jours,
        'chart_sales_data': donnees_ventes,
        'chart_products_labels': labels_produits,
        'chart_products_data': donnees_produits,
        # cumuls par période
        'ca_jour': ca['jour'] or 0,
        'ca_semaine': ca['semaine'] or 0,
        'ca_mois': ca['mois'] or 0,
        'ca_total': ca['total'] or 0,
        'recap_jours': recap_jours,
    }
    return render(request, 'users/dashboard.html', context)