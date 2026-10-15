from django.contrib import admin

from accounts.models import EventGrant, Membership, Organization, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "is_platform_admin", "is_staff")
    search_fields = ("email",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role")


@admin.register(EventGrant)
class EventGrantAdmin(admin.ModelAdmin):
    list_display = ("user", "event", "role", "can_export")
