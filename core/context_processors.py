def shell(request):
    from checkin.dashboard import door_event

    user = getattr(request, "user", None)
    return {
        "current_organization": getattr(request, "organization", None),
        "door_event": door_event(user) if user else None,
    }
