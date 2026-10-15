class AmbiguousSMTP(Exception):
    pass


class TransientSMTP(Exception):
    pass


class PermanentSMTP(Exception):
    pass


def deliver(delivery):
    import smtplib

    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives

    recipient = delivery.recipient_email
    if not recipient or "," in recipient or " " in recipient.strip():
        raise PermanentSMTP("A delivery must have one recipient.")
    message = EmailMultiAlternatives(
        subject=delivery.subject,
        body=delivery.text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    if message.to != [recipient] or message.bcc or message.cc:
        raise PermanentSMTP("Messages are sent to one recipient.")
    message.attach_alternative(delivery.html_body, "text/html")
    message.extra_headers = {"X-Event-Delivery": str(delivery.id)}
    if delivery.audience.campaign.kind == "seating":
        from communications.rendering import calendar_ics

        message.attach("event.ics", calendar_ics(delivery.booking.event), "text/calendar")
    try:
        sent = message.send(fail_silently=False)
    except smtplib.SMTPRecipientsRefused as exc:
        raise PermanentSMTP("Recipient refused.") from exc
    except (smtplib.SMTPServerDisconnected, TimeoutError, ConnectionError) as exc:
        raise AmbiguousSMTP("The connection closed before acceptance was confirmed.") from exc
    except smtplib.SMTPException as exc:
        raise TransientSMTP(str(exc)[:200]) from exc
    if sent != 1:
        raise AmbiguousSMTP("The server did not confirm a single accepted message.")
    return str(delivery.id)
