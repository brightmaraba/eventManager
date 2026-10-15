from django.contrib import admin

from seating.models import Hold, SeatOccupancy


@admin.register(Hold)
class HoldAdmin(admin.ModelAdmin):
    list_display = ("purpose", "event", "released_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SeatOccupancy)
class SeatOccupancyAdmin(admin.ModelAdmin):
    list_display = ("seat", "ticket", "hold")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
