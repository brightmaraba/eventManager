import contextvars
import json
import logging
import re

request_id_var = contextvars.ContextVar("request_id", default="")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TOKEN_PATH_RE = re.compile(r"(/(?:guest|checkin/t)/)[A-Za-z0-9_\-]+")
SECRET_RE = re.compile(r"(?i)(api[_-]?key|secret|password|token)(['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]+)")


def redact(text):
    value = EMAIL_RE.sub("[redacted-email]", str(text))
    value = TOKEN_PATH_RE.sub(r"\1[redacted-token]", value)
    value = SECRET_RE.sub(r"\1\2[redacted]", value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        job_id = getattr(record, "job_id", None)
        if job_id:
            payload["job_id"] = str(job_id)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)
