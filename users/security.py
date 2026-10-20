def client_ip(request):
    """
    Adresse IP du client, pour la limitation des tentatives de connexion.

    Derrière le proxy de Render, REMOTE_ADDR est celle du proxy : toutes les
    requêtes sembleraient venir de la même adresse. Le proxy ajoute l'adresse
    réelle du client en dernière position de X-Forwarded-For ; les valeurs
    placées avant peuvent être forgées par le client, on ne les lit donc pas.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR")
