# Using the interface

Log in at `/accounts/login/`. Development login does not ask for a second factor while `DJANGO_DEBUG=1`. After login, open an event from the list.

## Event setup

The event page shows totals, then links to layout, bookings, import, publications, messages, check-in, exports, and editing. Archive, cancel, duplicate, and access grants are the same forms as before. A status line appears when seating changed after the last publication.

## Seating

Open **Seating layout**. The canvas and the unassigned list are solid. Drag a table to move it; the page saves when you release. Arrow keys move the table while a seat in that table is focused. Zoom, fit, and undo are in the toolbar.

Every canvas action has a form under **Keyboard and form actions**: add a table, assign, unassign, swap, hold a table, or seat a party. If someone else saved first, the page says the layout changed and asks you to refresh before saving over that edit.

## Guests and check-in

Import still starts with a CSV preview. Commit only after the preview looks right. Check-in search and scanner codes are on the check-in page. A result line reports whether the guest was checked in or was already checked in.

Guest links open a public page with the event name, the party, and either the published seats or the line "Your seating is still pending."

## Print

Exports still choose the document, paper, orientation, and whether emails are included. Printed pages use a solid ivory background and olive text so they stay readable on paper.
