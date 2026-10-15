class DomainError(Exception):
    def __init__(self, code, message, status=400, field_errors=None, revision=None, extra=None):
        self.code = code
        self.message = message
        self.status = status
        self.field_errors = field_errors or {}
        self.revision = revision
        self.extra = extra or {}
        super().__init__(message)


class Conflict(DomainError):
    def __init__(self, code, message, **kwargs):
        super().__init__(code, message, status=kwargs.pop("status", 409), **kwargs)


class Denied(DomainError):
    def __init__(self, message="You do not have permission to do that.", code="denied"):
        super().__init__(code, message, status=403)


class NotFound(DomainError):
    def __init__(self, message="Not found.", code="not_found"):
        super().__init__(code, message, status=404)


class TooLarge(DomainError):
    def __init__(self, message="That upload is too large.", code="too_large"):
        super().__init__(code, message, status=413)


class Throttled(DomainError):
    def __init__(self, message="Too many requests. Wait and try again.", code="throttled"):
        super().__init__(code, message, status=429)
