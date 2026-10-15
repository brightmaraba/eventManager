import uuid

from django.utils.deprecation import MiddlewareMixin

from core.logging import request_id_var


class RequestIdMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
        request_id_var.set(request.request_id)

    def process_response(self, request, response):
        response["X-Request-ID"] = getattr(request, "request_id", "")
        response["Referrer-Policy"] = "same-origin"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class ContentSecurityPolicyMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if request.path.startswith("/admin/"):
            return response
        response["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response


class OrganizationMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.organization = None
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return
        org_id = request.session.get("organization_id")
        if not org_id:
            return
        from accounts.models import Organization

        request.organization = Organization.objects.filter(pk=org_id).first()
