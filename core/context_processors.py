def shell(request):
    return {"current_organization": getattr(request, "organization", None)}
