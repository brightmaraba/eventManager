from django.shortcuts import redirect, render
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from accounts.permissions import can_communicate, can_view
from communications.models import Campaign
from communications.services import cancel_campaign, create_campaign, get_campaign, preview_campaign, queue_campaign
from core.http import require_login
from events.views import load_event


@require_login
@require_http_methods(["GET", "POST"])
def campaigns(request, event_id):
    event = load_event(request, event_id, can_communicate if request.method == "POST" else can_view)
    if request.method == "POST":
        campaign = create_campaign(
            event=event, actor=request.user, kind=request.POST.get("kind", "invitation"),
            subject=request.POST.get("subject", ""), audience_filter={"kind": request.POST.get("audience", "all")},
            request_id=request.request_id,
        )
        return redirect("campaign-detail", event_id=event.id, campaign_id=campaign.id)
    return render(request, "communications/list.html", {"event": event, "campaigns": event.campaigns.all(), "kinds": Campaign.Kind.choices})


@require_login
@require_http_methods(["GET", "POST"])
def campaign_detail(request, event_id, campaign_id):
    event = load_event(request, event_id, can_view)
    campaign = get_campaign(event, campaign_id)
    preview = None
    if request.method == "POST":
        event = load_event(request, event_id, can_communicate)
        action = request.POST.get("action")
        if action == "preview":
            preview = preview_campaign(campaign)
        elif action == "test":
            queue_campaign(campaign=campaign, actor=request.user, request_id=request.request_id, test_recipient=request.POST.get("test_recipient", ""))
            from communications.services import dispatch_pending
            dispatch_pending()
            return redirect("campaign-detail", event_id=event.id, campaign_id=campaign.id)
        elif action == "send":
            when = parse_datetime(request.POST.get("scheduled_at", "")) if request.POST.get("scheduled_at") else None
            queue_campaign(campaign=campaign, actor=request.user, request_id=request.request_id, when=when)
            from communications.services import dispatch_pending
            dispatch_pending()
            return redirect("campaign-detail", event_id=event.id, campaign_id=campaign.id)
        elif action == "cancel":
            cancel_campaign(campaign=campaign, actor=request.user, request_id=request.request_id, reason=request.POST.get("reason", "cancelled"))
            return redirect("campaign-detail", event_id=event.id, campaign_id=campaign.id)
    return render(request, "communications/detail.html", {"event": event, "campaign": campaign, "preview": preview})
