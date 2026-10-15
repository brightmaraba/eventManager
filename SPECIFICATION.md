# Event Table Management System

Version 1.0 — implementation specification — 15 October 2026

## 1. Purpose and delivery scope

Provide event administrators with a reliable way to manage events, import ticket holders, arrange tables and chairs visually, reserve capacity, assign individual tickets to seats, communicate seating details, and print operational documents.

The accompanying Docker configurations and Django project are an infrastructure starter, not the completed business application. This specification defines the application to build. The starter implements Django admin, health endpoints, PostgreSQL connectivity, Redis/Celery configuration, development MailDev, production SendGrid SMTP configuration, and an HTTPS reverse proxy.

### Assumptions

- A deployment can support multiple organizations, each with multiple events. Every domain query is organization scoped; memberships determine access.
- Each event initially has one room. The data model permits multiple rooms without changing ticket identity.
- Tickets are imported from an external ticketing system; payment processing, sales and refunds are outside version 1.
- One ticket admits one person and consumes one seat. An email represents a booking party, not necessarily one attendee.
- Staff assign seats. Guest self-selection, offline synchronization and external ticketing integrations are later options.
- Dates are stored in UTC and displayed in the event's explicit IANA timezone. The application must not infer it from the server or venue address.
- Initial deployment uses Docker Compose on one Linux host. This is not a highly available cluster.

## 2. Roles and authorization

| Role | Permissions |
|---|---|
| Platform administrator | Provision organizations; audited emergency access; platform operations |
| Organization owner | Memberships, all organization events, retention/export settings |
| Event administrator | Event CRUD, imports, rooms, tables, seats, reservations, publication, communications, exports |
| Seating coordinator | Layout and assignments on explicitly granted events; no membership management or event deletion |
| Check-in staff | Search assigned event guests, view seats, check individual tickets in/out; no bulk export or layout editing |
| Read-only staff | View explicitly granted event and seating; exports only with a separate permission |
| Guest | Optional expiring signed link to their own booking's published seating only |

Use Django session authentication, CSRF protection and server-side permissions on every endpoint, including downloads and asynchronous job status. UUIDs are identifiers, not access controls. Require MFA for privileged production accounts. Generic Django admin must not bypass domain service validation.

## 3. Event lifecycle and CRUD

### Fields

UUID, organization, name, slug/reference, description, venue name, address lines, locality, region, postal code, country, contact name/email/phone, logo, optional room plan image, start and end datetimes, timezone, doors-open time, initial table count, default seats per table, status, accessibility notes, internal notes, version, created/updated metadata and retention date.

Validate required name and venue/address; end after start; doors-open no later than start; timezone valid; nonnegative table count and positive default seat count. Initial table count and default seats are creation inputs. Actual table count and capacity are derived from active tables/seats; editing the defaults does not silently rebuild existing furniture.

Lifecycle: `DRAFT -> PUBLISHED -> COMPLETED -> ARCHIVED`; `DRAFT` or `PUBLISHED -> CANCELLED`. Reopening a completed event requires an administrator and audit reason. Archive is reversible; hard deletion is an owner-only retention process. Disallow silent destruction of imports, assignments or communication history. Cancellation stops scheduled sends and offers a separately confirmed cancellation message.

Create with an optional layout template; duplicate copies event metadata and geometry but excludes guests, holds, assignments, check-ins and message history by default. Search/filter by date, status and venue. Dashboard shows tickets, active capacity, blocked seats, held seats, assigned seats, unassigned tickets, and checked-in tickets.

Publishing requires a valid room layout and a capacity check. Unassigned tickets may remain only if the administrator explicitly acknowledges them; guest messages must then say seating is pending. Publishing is distinct from emailing.

## 4. Room, table and chair management

Room: name, width/height in metres, scale, background image, origin, obstacles, exits, accessibility zones and optional configured maximum occupancy. A background image must have a calibrated scale. Occupancy limits are entered by the venue; the software does not certify regulatory compliance.

Table: immutable UUID, room, unique event-wide display label, round/rectangle/custom shape, dimensions, center X/Y, rotation, optional category and notes. Support create, rename, duplicate, bulk generate, move, rotate and retire. Moving a table moves all of its chairs using local coordinates.

Seat: immutable UUID, table, label unique within table, relative X/Y, orientation, accessibility features and availability (`ACTIVE`, `BLOCKED`, `RETIRED`). Chairs may be added or removed individually, and capacity may be changed in bulk. Seat IDs survive renumbering. A chair must belong to a table in version 1; a labelled seating section can represent theatre-style rows later.

Deletion/retirement rules:

- Empty unreserved furniture can be removed in one transaction.
- Held or assigned furniture cannot disappear implicitly. Show affected tickets/holds and require an explicit release or atomic reassignment first.
- Reducing capacity never deletes occupied seats or cancels tickets.
- Historical published snapshots retain removed furniture and historical labels.
- Duplicating furniture creates new IDs and does not copy reservations or assignments.

Capacity is the count of active usable seats, not `number_of_tables * default_seats`. Available seats = active seats minus held seats minus assigned seats. Holds and assignments are mutually exclusive. Blocked/retired seats cannot receive either.

## 5. Graphical layout editor

Use server-rendered Django HTML/CSS plus a focused JavaScript SVG editor. JavaScript is necessary for drag/drop, zoom and geometry; a full SPA is unnecessary.

Provide a room canvas, furniture palette, searchable unassigned-ticket sidebar, table/seat inspector, legend, zoom/pan, fit-to-room, grid snapping, alignment tools, multi-select, keyboard movement, rotation and undo/redo. Show table labels, seat labels and occupancy. Use both color and icons/text to indicate available, held, assigned, blocked and checked-in status.

Allow drag of a ticket onto an available seat, drag of a booking onto a table, and an accessible list-based assignment form. Group assignment previews exact seats, never splits a party without confirmation, and reports insufficient capacity. Manual swaps are atomic. Moving geometry must preserve all seat assignments.

Reject geometry outside room boundaries and overlapping table/chair footprints; allow a configurable clearance margin. Warn about blocked exits/aisles using configured zones. Administrators may override clearance warnings with an audit reason, but not invalid coordinates or out-of-room placement. These checks are planning aids.

Save geometry in metres independent of screen resolution. Geometry updates include a layout version. A stale save returns HTTP 409 with current version; do not overwrite another administrator's changes. Poll revision changes initially; WebSockets are optional later. Undo issues a new validated mutation against the current revision rather than overwriting history.

Draft and published layouts are separate. Publishing creates an immutable snapshot of geometry, labels and assignments, with publication number, timestamp and actor. Structural changes after publication create a new draft. Guest-facing views and printouts use a selected published snapshot. If current ticket cancellation makes a published seat invalid, revoke guest access to that cancelled ticket immediately and flag republishing as required.

## 6. Reservations and seating invariants

Distinguish three concepts: a guest ticket, an admin hold, and an assigned seat. A hold can reserve one seat, selected seats or an entire table for a party/VIP/purpose with a reason and optional expiry. Holds may exist before a booking is imported.

A whole-table hold locks the table and creates one hold occupancy per active seat. It fails atomically if any seat is assigned or held by someone else. New chairs added to a held table inherit its hold. Releasing a table hold releases all its seat occupancies. Changing a table hold to an assignment consumes the selected hold occupancies atomically; remaining seats remain held unless released. Changing the structure of a held table must use the same table lock as assignment operations.

Critical invariants:

1. A ticket has at most one current seat; a seat has at most one current occupant (hold or ticket).
2. Assigned ticket, seat, booking and hold all belong to the same event and organization.
3. Only active tickets and active usable seats can be assigned.
4. Cancelled tickets cannot be checked in or assigned; retired furniture retains history only.
5. Party ticket quantity is the number of active ticket records; edits never allow negative quantities.
6. Expired holds are considered releasable in the same locked transaction, even if the cleanup worker is delayed.

Use PostgreSQL transactions with row locks (`select_for_update`) for assignment, swap, table hold, ticket quantity change, capacity reduction and import commit. Lock affected tables, seats and tickets in a consistent sorted order. Store all current hold/assignment occupancy in one table with unique seat and unique non-null ticket constraints. Enforce exactly one of ticket or hold on an occupancy row using a database check constraint. Validate event consistency inside the shared domain service while locking referenced rows; prohibit alternative write paths. Consider a database trigger for cross-table event consistency if multiple writers are introduced.

Return conflicts explicitly; never silently replace an occupant. Bulk seating is all-or-nothing unless the user chooses and previews a partial assignment operation. Audit actor, reason, before/after IDs and revision. Use request idempotency keys for retryable mutations and a unique key per organization/operation.

## 7. CSV guest import

Required UTF-8 CSV columns: `email,ticket_count`. Optional: `booking_reference,party_name,attendee_names,notes`. Version 1 treats `attendee_names` as optional display data, never as a source of ticket quantity; preferably use individual attendee editing after import. Document its encoding before enabling this optional column.

```csv
email,ticket_count,booking_reference,party_name
alex@example.com,4,ORDER-1001,Alex family
sam@example.com,2,ORDER-1002,Sam party
```

Flow: upload -> parse -> validate -> preview changes/errors -> explicit commit -> reconciliation summary. Enforce configurable defaults of 5 MB and 10,000 rows. Accept a UTF-8 BOM; use a real CSV parser for quotes, commas and CRLF. Validate email syntax and positive integer count (default per-row maximum 100, configurable). Never silently drop invalid rows. Default is atomic import; the user may explicitly select only valid rows for a new preview.

Normalize email with whitespace trimming and a documented case-insensitive business rule, retaining the original spelling. The base product has one booking per event + normalized email; booking_reference is external metadata. Multiple orders for one email are consolidated upstream or through an explicitly selected sum mode.

Default duplicate policy: reject duplicate emails within a file. Optional aggregate mode shows combined counts before commit. Default existing-record policy: replace the booking's total entitlement with the imported total, not add tickets. Optional additive mode must be explicitly labelled and confirmed. Reupload of the same file + mode returns the original completed result unless the administrator deliberately starts a new import. Use a file digest, event, mode and import idempotency key.

An increased count creates additional numbered ticket records. A decreased count retires unassigned, unchecked-in tickets first. If more must be removed, stop and ask for explicit ticket selection/reassignment; never remove occupied/checked-in tickets silently. A normal import does not delete bookings absent from the file. A separate replace-roster workflow must preview all removals and impacts.

Store import batch, uploader, digest, mode, row results, totals and timestamps. Preview records the roster revision; commit revalidates under locks and returns a conflict if the roster changed. CSV and detailed error reports expire under retention policy. Escaping spreadsheet formula prefixes in exported text prevents exported cells from becoming formulas.

Tickets are generated as stable UUIDs plus party sequence numbers, e.g. `Alex family — guest 1/4`. Optional attendee names can be added later without changing ticket identity. Importing email addresses does not constitute marketing consent.

## 8. Email and guest experience

Templates: invitation/event information, seating confirmation, changed seating, reminder and cancellation. Use Django escaped templates with HTML and plain-text alternatives. Include event name/logo, local date/time/timezone, venue address, booking ticket total, published table/seat labels, accessibility/contact information and an optional calendar attachment.

Audience selection: all active bookings, selected bookings, assigned/unassigned, changed since a selected publication, or delivery failures. Show recipient count, publication number and preview; allow a test email; require explicit send/schedule action. Send one separate email per booking, never a visible bulk recipient list. Changed-seating campaigns contain only affected parties after republishing.

Use Celery for delivery and a PostgreSQL outbox for durable intent. Store a unique logical key `(campaign, booking, publication)` and states pending, claimed, submitted, delivered, bounced, failed, suppressed and ambiguous. SMTP acceptance is submitted, not delivered. Commit outbox rows with the business transaction; enqueue after commit and periodically scan pending rows so Redis loss does not lose intent.

Retry transient errors with exponential backoff/jitter and bounded attempts. Do not retry permanent invalid-recipient failures. Rate-limit per provider and organization. SMTP cannot guarantee exactly-once delivery: if the connection drops after acceptance, mark delivery ambiguous and reconcile or require an explicit resend instead of blindly duplicating. Preserve attempt history and provider message identifiers when available.

Production uses SendGrid SMTP with STARTTLS on port 587, username `apikey` and API key supplied as a secret. Authenticate the sender domain and use a narrowly scoped Mail Send key. MailDev captures development SMTP on port 1025 and exposes a local inbox on 1080.

Implement SendGrid Event Webhook signature verification and replay protection before relying on delivered/bounced status. Webhook receipts are idempotent and may arrive out of order. A bounce/complaint suppression list prevents repeated sends. Operational event messages and opt-in marketing must be separate categories.

Optional guest links use high-entropy, hashed tokens, scoped to one booking with expiry/revocation and rate limiting. Avoid email addresses or ticket IDs in URLs. Guest views show only that booking's details, no complete seating roster. Do not place personal details in QR codes; use opaque revocable tokens.

## 9. Printing, export and check-in

Generate print-friendly HTML immediately and background PDFs for large exports. Support:

- Full room plan with legend, table/seat labels, capacity, publication number and timestamp; A4/A3 landscape, fit-to-page and tiled printing.
- Table roster, alphabetical attendee/party list, and table-number order.
- Table number cards, individual place cards and booking seating slips.
- Unassigned-ticket, accessibility-needs (restricted), reservations and check-in reports.
- CSV export of active ticket assignments and an event data export for authorized owners.

Public signage hides emails and private notes by default; staff rosters include emails only when explicitly requested. Every export records snapshot/revision and generation time. Store reports privately with authenticated downloads, expiry and audit records. A generated report must read one consistent snapshot, not a mixture of concurrent updates.

Check-in is per ticket with timestamp, actor and optional device reference. A second check-in is idempotent and reports the earlier scan. Booking search allows partial check-in (e.g. 2 of 4 arrived). Undo check-in requires a reason. Internet connectivity is required in version 1.

## 10. Proposed data model

| Entity | Principal fields and constraints |
|---|---|
| Organization / Membership | Organization identity; unique user+organization; role; event grants |
| Event | Organization FK; metadata; lifecycle; roster revision; layout revision; active publication |
| Room | Event FK; dimensions; units; background file reference |
| RoomObstacle | Room FK; polygon; kind; clearance policy |
| EventTable | Event/room FK; UUID; label; shape; dimensions; position; rotation; retired_at |
| Seat | Table FK; UUID; label; relative position; accessibility; availability; retired_at |
| Booking | Event FK; normalized email; original email; party name; reference; unique event+email |
| Ticket | Booking FK; stable sequence; display name; active/cancelled; unique booking+sequence |
| Hold | Event FK; optional booking/table FK; purpose; expiry; active/released; created_by |
| SeatOccupancy | Unique seat FK; nullable unique ticket FK; nullable hold FK; XOR check; assigned_by |
| LayoutPublication | Event FK; unique revision; immutable JSON geometry and assignment snapshot; actor/time |
| ImportBatch / ImportRow | File reference/digest; mode; revision; row diagnostics; commit state |
| Campaign / EmailDelivery | Template snapshot; audience snapshot; publication; schedule; outbox key; attempts |
| ProviderEvent | Unique provider event ID; verified payload reference; delivery association |
| ExportJob | Requester; snapshot; format; state; private artifact; expiry |
| CheckIn | Unique ticket FK; current status; actor/time; history in audit log |
| AuditLog | Organization/event; actor; operation; object; redacted before/after; request ID; timestamp |

Index event/status, event/email, table/seat, hold expiry, pending outbox scheduled_at, and event audit timestamp. Use `PROTECT` for historical dependencies. Current occupancies may be removed when released but history remains append-only. Ticket quantities and capacity are derived, with caches permitted only when transactionally maintained and reconciled.

## 11. Application architecture and routes

Modules: `accounts`, `events`, `layouts`, `guests`, `seating`, `communications`, `reports`, `checkin`, `audit`. Keep domain operations in services shared by HTML views, JSON endpoints, admin actions and Celery tasks. PostgreSQL is authoritative. Redis is the Celery broker and optional ephemeral cache; do not use it as the sole booking or reservation store.

Routes below are proposed implementation contracts, not routes already implemented in the starter:

| Route | Method / behavior |
|---|---|
| `/events/` | GET list; POST create |
| `/events/{id}/` | GET detail; PATCH metadata; DELETE archive intent |
| `/events/{id}/tables/` | GET/POST; table/seat subroutes PATCH/DELETE with impact checks |
| `/events/{id}/layout/` | GET draft; PATCH geometry with expected_version |
| `/events/{id}/publications/` | POST validate and publish snapshot |
| `/events/{id}/imports/` | POST upload; GET status/preview |
| `/events/{id}/imports/{batch}/commit/` | POST with preview revision and idempotency key |
| `/events/{id}/holds/` | POST hold; DELETE release; PATCH expiry |
| `/events/{id}/assignments/` | POST assign/group assign; DELETE unassign |
| `/events/{id}/assignments/swap/` | POST atomic swap |
| `/events/{id}/campaigns/` | POST draft; dedicated preview/test/send/cancel actions |
| `/events/{id}/exports/` | POST export; GET authenticated status/download |
| `/events/{id}/check-ins/` | POST check-in/undo with ticket and idempotency key |
| `/integrations/sendgrid/events/` | POST signed webhook; narrowly exempt from CSRF |
| `/guest/{token}/` | GET booking-scoped published seating |
| `/health/live/`, `/health/ready/` | Process liveness; PostgreSQL/Redis readiness |

HTML form actions use POST where browsers cannot issue PATCH/DELETE. JSON errors include code, safe message, field errors, current revision and request ID. Use 400 validation, 403 denied, 404 inaccessible object, 409 conflict, 413 oversized import, 429 throttling. Successful background operations return 202 plus a status URL.

Example assignment request: `{"ticket_id":"uuid","seat_id":"uuid","expected_version":12,"idempotency_key":"uuid"}`. A concurrent assignment returns `409 seat_unavailable` and refreshes the affected seats. Bulk requests return one transaction result and affected revision.

## 12. Nonfunctional requirements

Initial acceptance workload: 10,000 tickets, 1,000 tables per event, 20 concurrent staff users on a reference server of 4 vCPU / 8 GB RAM with SSD; benchmark and adjust before committing capacity. Aim for p95 ordinary page/API latency below 500 ms excluding network and exports, p95 seat assignment below 750 ms, a 10,000-row import below 60 seconds, and usable first layout rendering below 3 seconds. Use level of detail at low zoom, pagination and indexed searches. These are targets, not measured starter performance.

Meet WCAG 2.2 AA intent for keyboard use, focus, contrast and form labels; test with screen readers. All graphical seating operations have a list/form equivalent. Layout editing is desktop/tablet first; guest views and check-in are mobile responsive.

Security: HTTPS, secure cookies, CSRF, escaped content, strong password policy/MFA, login throttling, tenant isolation tests and least privilege. Validate uploaded logos as decoded PNG/JPEG/WebP with dimensions/size limits and re-encode them; reject active SVG/HTML. Store uploaded files and reports outside public static paths. Staff exports and accessibility data require specific permissions. Redact emails, tokens and private notes from logs. Add a restrictive CSP compatible with the chosen editor.

Proposed retention defaults, subject to owner policy: source imports 30 days; reports 7 days; identifiable event data 90 days after completion; audit trail 365 days with personal fields redacted when retention expires. Support an owner-reviewed export/deletion workflow and ensure backup expiry follows the same policy. Do not claim legal compliance without jurisdiction-specific review.

Operational targets: daily encrypted database and media backups, off-host storage, 30-day retention, monthly restore test; baseline RPO 24 hours and RTO 4 hours. If a live event requires shorter loss windows, enable PostgreSQL WAL archiving/PITR and define a tested 15-minute RPO. Single-host Compose requires planned maintenance and does not guarantee continuous availability.

Observability: structured stdout logs with request/job IDs; error tracking; latency/error metrics; queue age; worker heartbeat; failed/ambiguous mail; database disk and backup age; import failures. Alert on unavailable web/DB, queue age over 5 minutes and failed backups. Docker health status alone does not restart an unhealthy running container; external monitoring and an operator runbook are required.

## 13. Background jobs and recovery

Celery queues: `default`, `imports`, `mail`, `reports`. Starter worker consumes all four; split pools when measurements justify it. Tasks take IDs, not serialized personal records, and recheck organization and lifecycle state. Persist progress/results in PostgreSQL. Use short tasks and bounded timeouts; late acknowledgement only for idempotent tasks.

Periodic jobs: expire holds, dispatch scheduled outbox, reconcile abandoned claims, expire files and perform retention cleanup. Store schedules/due times in PostgreSQL and periodically scan; do not use distant Celery ETA tasks as the durable schedule. Run exactly one beat instance. The scaffold runs beat but does not yet define these business jobs.

Worker failure must not leave a partially committed import or assignment. Retry safe work from persisted checkpoints; abandoned delivery claims need reconciliation. Redis AOF is useful, but database outbox reconciliation remains required. Disk-full, provider outage and broker loss must produce visible operational errors rather than data corruption.

## 14. Test and acceptance plan

| ID | Acceptance scenario |
|---|---|
| A01 | Create event with 10 tables x 8 chairs: capacity 80; add two chairs: capacity 82 |
| A02 | Delete or shrink an occupied table: blocked with affected tickets; explicit atomic reassign succeeds |
| A03 | Import 4 tickets for one email: creates four stable tickets; repeat default import leaves four |
| A04 | Duplicate, malformed email, negative/fractional count and oversized file yield row-level errors; no partial default commit |
| A05 | Decreasing a seated booking's quantity cannot silently remove assigned or checked-in tickets |
| A06 | Two transactions assign the same chair: one succeeds, one returns conflict; one occupancy persists |
| A07 | One ticket assigned concurrently to two seats: one assignment persists |
| A08 | Whole-table hold races with chair creation or assignment: no unheld or double-booked seat escapes |
| A09 | Expired hold can be reused even with beat stopped; audit records release/assignment |
| A10 | Stale geometry save returns 409; rotating/moving tables retains seat IDs and occupants |
| A11 | Cross-organization IDs cannot be read, mutated or exported through any route/job |
| A12 | Published layout remains stable during draft edits; new publication marks affected bookings |
| A13 | Email preview/test/bulk delivery works in MailDev; each message has one recipient and correct snapshot |
| A14 | SendGrid sandbox/staging verifies SMTP, webhook signature/replay rejection, bounce suppression and ambiguous-send handling |
| A15 | Redis/worker restart recovers pending outbox work without losing business intent |
| A16 | A4/A3 plan, roster, cards and private/public variants render without clipping or unwanted personal data |
| A17 | Duplicate QR scan cannot double check-in; cancelled ticket is rejected |
| A18 | Restore PostgreSQL plus private files into a clean environment and verify seating, imports and report access |
| A19 | Keyboard-only user can create a table, select a chair and assign/unassign a ticket |
| A20 | Production deployment passes Django deployment checks, HTTPS/CSRF login, health and queue smoke tests |

Use PostgreSQL integration tests (not SQLite) and real separate transactions for concurrency. Use browser tests for drag/drop, conflict recovery, keyboard alternatives and print layout. Test both daylight-saving transitions and differing event/user timezones. Load tests must use representative furniture geometry and roster sizes.

## 15. Delivery phases

1. Foundation: authentication, organization isolation, event CRUD, schema/migrations, audit, container CI.
2. Inventory and imports: rooms/tables/chairs, ticket quantities, preview/commit/reconciliation and constraints.
3. Seating: holds, assignments, transaction/concurrency tests, editor, revision conflict handling and publication.
4. Operations: emails/outbox/webhooks, print/PDF, guest links and check-in.
5. Release hardening: accessibility, load tests, backups/restores, monitoring, deployment rehearsal and acceptance sign-off.

Version 1 is complete only when A01–A20 pass on staging. Optional later work: automated seating optimization, guest self-selection, ticketing integration, multiple room sessions, offline check-in and high availability.

## 16. Technical references

The selected baseline is Python 3.12, Django 5.2 LTS, PostgreSQL 17, Redis 7.4 and Celery 5.6. These are selected compatibility families, not a claim that they are the newest releases. Resolve tested patched versions and immutable image digests during release preparation.

- Django releases: https://www.djangoproject.com/download/
- Django deployment checklist: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- Docker Compose production: https://docs.docker.com/compose/how-tos/production/
- Compose secrets: https://docs.docker.com/compose/how-tos/use-secrets/
- Celery Redis operation: https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html
- MailDev: https://maildev.github.io/maildev/docs/quickstart/
- SendGrid SMTP: https://www.twilio.com/docs/sendgrid/for-developers/sending-email/integrating-with-the-smtp-api
