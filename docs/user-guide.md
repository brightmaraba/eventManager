# User guide

Sign in at `/accounts/login/`. In development, `python manage.py seed_demo` creates North Hall and the Spring dinner event for `owner@example.test`.

## Events

Create an event from the event list. The timezone is an IANA name, and the start, end, and doors-open times are local to that timezone. A time that does not exist, such as a daylight-saving gap, is rejected. Capacity is the number of active seats, not the table count typed at creation.

Archive can be reversed. Completing and cancelling are explicit actions. Cancelling stops unsent campaigns. Hard delete is not available from the event form.

## Import

The CSV needs `email` and `ticket_count`. An `attendee_names` column is rejected. The default preview rejects duplicate emails in the file and replaces each booking's ticket total. It does not delete bookings that are absent from the file. Replacing the whole roster is a separate choice and needs confirmation. Commit fails if the roster changed after the preview. Limits are 5 MB and 10,000 rows.

## Seating

The layout page has an SVG canvas and the same actions as forms: add a table, assign, unassign, swap, hold a table, and seat a party. Adding a table from the form places it in the next open grid position. Moving or renaming a table keeps seat IDs. Removing a seat or table that still has an assignment or hold stops and lists the impact.

Publish creates a numbered snapshot. Later draft edits do not change that snapshot. Publishing does not send email. Guest links and printouts use the published snapshot, while check-in still reads the live ticket.

## Mail, check-in, and print

Message drafts can target all bookings or a filtered audience. A test send and a bulk send create one outbox row per recipient. SMTP acceptance means the message was submitted, not that it was delivered. A complaint suppression blocks later sends to that address.

Check-in search finds a party. A repeat check-in of the same ticket does not create a second arrival. Undo requires a reason. Cancelled tickets cannot be checked in.

Exports can render a room plan, roster, table cards, place cards, or seating slips as HTML or PDF. Public output leaves out email and notes. CSV cells that start with a spreadsheet formula are prefixed so the spreadsheet treats them as text.
