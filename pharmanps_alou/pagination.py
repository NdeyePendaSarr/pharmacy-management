from django.core.paginator import Paginator


def paginate(request, queryset, per_page):
    """
    Page demandée par ?page=… ; un numéro invalide ou hors limites renvoie la
    première ou la dernière page plutôt qu'une erreur. Le gabarit affiche
    les liens avec partials/pagination.html.
    """
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))
