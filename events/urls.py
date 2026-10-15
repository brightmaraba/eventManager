from django.urls import path

from accounts import views as account_views
from checkin import views as checkin_views
from communications import views as communication_views
from events import views
from guests import views as guest_views
from layouts import views as layout_views
from reports import views as report_views
from seating import views as seating_views

urlpatterns = [
    path("", views.event_list, name="event-list"),
    path("new/", views.event_create, name="event-create"),
    path("<uuid:event_id>/", views.event_detail, name="event-detail"),
    path("<uuid:event_id>/edit/", views.event_edit, name="event-edit"),
    path("<uuid:event_id>/grants/", account_views.event_grant, name="event-grant"),
    path("<uuid:event_id>/actions/<str:action>/", views.event_action, name="event-action"),
    path("<uuid:event_id>/layout/", layout_views.editor, name="layout-editor"),
    path("<uuid:event_id>/layout.json", layout_views.layout_api, name="layout-api"),
    path("<uuid:event_id>/tables/", layout_views.tables, name="tables"),
    path("<uuid:event_id>/tables/<uuid:table_id>/duplicate/", layout_views.duplicate_table, name="table-duplicate"),
    path("<uuid:event_id>/tables/<uuid:table_id>/retire/", layout_views.retire_table, name="table-retire"),
    path("<uuid:event_id>/tables/<uuid:table_id>/chairs/", layout_views.add_chairs_view, name="table-chairs"),
    path("<uuid:event_id>/publications/", layout_views.publications, name="publications"),
    path("<uuid:event_id>/imports/", guest_views.imports, name="imports"),
    path("<uuid:event_id>/imports/<uuid:batch_id>/", guest_views.import_detail, name="import-detail"),
    path("<uuid:event_id>/imports/<uuid:batch_id>/commit/", guest_views.import_commit, name="import-commit"),
    path("<uuid:event_id>/imports/<uuid:batch_id>/valid/", guest_views.import_valid, name="import-valid"),
    path("<uuid:event_id>/imports/<uuid:batch_id>/errors.csv", guest_views.import_errors, name="import-errors"),
    path("<uuid:event_id>/bookings/", guest_views.bookings, name="bookings"),
    path("<uuid:event_id>/tickets/<uuid:ticket_id>/", guest_views.ticket_edit, name="ticket-edit"),
    path("<uuid:event_id>/holds/", seating_views.holds, name="holds"),
    path("<uuid:event_id>/assignments/", seating_views.assignments, name="assignments"),
    path("<uuid:event_id>/assignments/swap/", seating_views.swap, name="assignment-swap"),
    path("<uuid:event_id>/campaigns/", communication_views.campaigns, name="campaigns"),
    path("<uuid:event_id>/campaigns/<uuid:campaign_id>/", communication_views.campaign_detail, name="campaign-detail"),
    path("<uuid:event_id>/exports/", report_views.exports, name="exports"),
    path("<uuid:event_id>/exports/<uuid:job_id>/", report_views.export_detail, name="export-detail"),
    path("<uuid:event_id>/print/<str:kind>/", report_views.print_view, name="print"),
    path("<uuid:event_id>/check-ins/", checkin_views.checkins, name="checkins"),
]
