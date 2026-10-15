# Acceptance results

Recorded on 15 October 2026 against the development stack. `pytest -q` reported 37 passed. `tests/test_foundation.py::test_new_table_finds_open_space` was added after that run and passed. Automated Playwright tests were not run because the browser binaries are not installed.

| ID | Result | Evidence |
|---|---|---|
| A01 | Pass | `test_ten_tables_then_two_chairs`: 10×8 seats is 80, then two added chairs is 82. |
| A02 | Partial | `test_occupied_table_retirement_reports_impact` blocks retirement and keeps the table. A successful explicit reassignment of that occupied table was not executed as its own test. |
| A03 | Pass | Import test creates four stable tickets and a repeat import does not double them. |
| A04 | Pass | Invalid rows, in-file duplicates, and `attendee_names` are rejected without a partial commit. |
| A05 | Pass | Dropping quantity on a seated booking raises `protected_tickets`. |
| A06 | Pass | Two concurrent assignments of one seat: one success, one conflict, one occupancy. |
| A07 | Pass | One ticket raced onto two seats keeps a single occupancy. |
| A08 | Pass | A table hold raced with a new chair left no active seat without a hold. |
| A09 | Pass | An already expired hold was assigned without beat, with release and assignment audit rows. |
| A10 | Pass | Geometry with the wrong revision raises conflict. Moving a table keeps seat IDs. |
| A11 | Pass | A verified owner from another organization receives 404. Check-in staff can view and cannot create a table (403). |
| A12 | Pass | The first publication snapshot stays unchanged after a later move and a second publication. |
| A13 | Pass | Outbox tests submit one locmem message per recipient. A live MailDev capture contained one message, subject `Spring dinner`, to `guest@example.test` only. |
| A14 | Partial | Local ECDSA tests reject a bad signature, ignore a duplicate `sg_event_id`, keep a bounce ahead of a late delivery, and suppress a later send after a complaint. No SendGrid staging SMTP or webhook call was made. |
| A15 | Pass | `cache.clear()` left the pending outbox row in PostgreSQL, and the next scan submitted it. |
| A16 | Partial | WeasyPrint produced a PDF beginning with `%PDF`, and the browser export page reported `room_plan · ready`. Public HTML omitted the guest email. Clipping on A3/tiled paper was not measured by eye. |
| A17 | Pass | Unit test: repeat check-in is idempotent and a cancelled ticket conflicts. Browser desk search for Ada returned the party and reported `Checked in.` |
| A18 | Partial | Development database restored into `event_tables_restore` in 5.75 seconds, counts were read, and that database was dropped. Private-file restore and a production-sized RPO/RTO measurement were not run. |
| A19 | Pass | In the browser, Add table created T3, Assign seated Ada at T3 seat 1, and Unassign returned that seat to available. |
| A20 | Partial | `check --deploy` with `DJANGO_DEBUG=0` reported only `security.W005`, `security.W009`, and `security.W021`. W009 is the development secret. No public HTTPS login was performed. |

Performance targets (p95 page/API under 500 ms, assignment under 750 ms, 10,000-row import under 60 seconds, first usable layout under 3 seconds) were not measured and are not recorded as passes.
