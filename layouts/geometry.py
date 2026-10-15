import math
from decimal import Decimal

from core.errors import DomainError

CHAIR_RADIUS = 0.25
EPSILON = 0.001


def quantize(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise DomainError("invalid_number", "Coordinates and sizes must be finite numbers.")
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise DomainError("invalid_number", "Coordinates and sizes must be finite numbers.") from exc
    if not number.is_finite():
        raise DomainError("invalid_number", "Coordinates and sizes must be finite numbers.")
    return number.quantize(Decimal("0.001"))


def positive(value, label):
    number = quantize(value)
    if number <= 0:
        raise DomainError("invalid_dimension", f"{label} must be greater than zero.", field_errors={label: "Must be greater than zero."})
    return number


def chair_offsets(count, diameter):
    count = int(count)
    radius = float(diameter) / 2 + 0.45
    offsets = []
    for index in range(count):
        angle = (2 * math.pi * index / count) - (math.pi / 2)
        offsets.append((quantize(radius * math.cos(angle)), quantize(radius * math.sin(angle)), quantize(math.degrees(angle) % 360)))
    return offsets


def world_point(center_x, center_y, rotation, rel_x, rel_y):
    radians = math.radians(float(rotation or 0))
    dx = float(rel_x)
    dy = float(rel_y)
    x = float(center_x) + dx * math.cos(radians) - dy * math.sin(radians)
    y = float(center_y) + dx * math.sin(radians) + dy * math.cos(radians)
    return x, y


def table_polygon(table):
    cx, cy = float(table.center_x), float(table.center_y)
    if table.shape == "custom" and table.polygon:
        return [world_point(cx, cy, table.rotation, point["x"], point["y"]) for point in table.polygon]
    if table.shape == "round":
        radius = float(table.width_m) / 2
        return [
            (
                cx + radius * math.cos(2 * math.pi * index / 16),
                cy + radius * math.sin(2 * math.pi * index / 16),
            )
            for index in range(16)
        ]
    hw, hh = float(table.width_m) / 2, float(table.height_m) / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return [world_point(cx, cy, table.rotation, x, y) for x, y in corners]


def circle_polygon(x, y, radius, steps=8):
    return [
        (x + radius * math.cos(2 * math.pi * index / steps), y + radius * math.sin(2 * math.pi * index / steps))
        for index in range(steps)
    ]


def seat_polygon(table, seat):
    x, y = world_point(table.center_x, table.center_y, table.rotation, seat.rel_x, seat.rel_y)
    return circle_polygon(x, y, CHAIR_RADIUS)


def _project(axis, polygon):
    dots = [point[0] * axis[0] + point[1] * axis[1] for point in polygon]
    return min(dots), max(dots)


def polygons_overlap(first, second):
    for polygon in (first, second):
        for index, start in enumerate(polygon):
            end = polygon[(index + 1) % len(polygon)]
            axis = (start[1] - end[1], end[0] - start[0])
            length = math.hypot(*axis) or 1
            axis = (axis[0] / length, axis[1] / length)
            a_min, a_max = _project(axis, first)
            b_min, b_max = _project(axis, second)
            if a_max <= b_min + EPSILON or b_max <= a_min + EPSILON:
                return False
    return True


def inside_room(polygon, width, height):
    return all(-EPSILON <= x <= width + EPSILON and -EPSILON <= y <= height + EPSILON for x, y in polygon)


def inflate(polygon, margin):
    cx = sum(point[0] for point in polygon) / len(polygon)
    cy = sum(point[1] for point in polygon) / len(polygon)
    inflated = []
    for x, y in polygon:
        dx, dy = x - cx, y - cy
        length = math.hypot(dx, dy) or 1
        inflated.append((x + margin * dx / length, y + margin * dy / length))
    return inflated


def obstacle_polygon(obstacle):
    return [(float(point["x"]), float(point["y"])) for point in obstacle.polygon]


def validate_layout(room, tables, override_reason=""):
    errors = []
    warnings = []
    width, height = float(room.width_m), float(room.height_m)
    if width <= 0 or height <= 0:
        errors.append("Room dimensions must be positive.")
    active = [table for table in tables if table.retired_at is None]
    footprints = []
    for table in active:
        try:
            positive(table.width_m, "width")
            positive(table.height_m, "height")
            quantize(table.center_x)
            quantize(table.center_y)
            quantize(table.rotation)
        except DomainError as exc:
            errors.append(exc.message)
            continue
        polygon = table_polygon(table)
        if not inside_room(polygon, width, height):
            errors.append(f"Table {table.label} is outside the room.")
        footprints.append((table, polygon, None))
        for seat in table.seats.all():
            if seat.retired_at or seat.availability == "retired":
                continue
            chair = seat_polygon(table, seat)
            if not inside_room(chair, width, height):
                errors.append(f"Seat {table.label}-{seat.label} is outside the room.")
            footprints.append((table, chair, seat))
    for index, (table, polygon, seat) in enumerate(footprints):
        for other_table, other, other_seat in footprints[index + 1 :]:
            same_table = table.id == other_table.id
            if same_table and (seat is None or other_seat is None):
                continue
            if polygons_overlap(polygon, other):
                errors.append(f"{table.label} overlaps {other_table.label}.")
            elif (
                not same_table
                and float(room.clearance_m) > 0
                and polygons_overlap(inflate(polygon, float(room.clearance_m)), other)
            ):
                warnings.append(f"{table.label} is closer than the clearance margin to {other_table.label}.")
    for obstacle in room.obstacles.all():
        zone = obstacle_polygon(obstacle)
        if len(zone) < 3:
            errors.append(f"Obstacle {obstacle.name or obstacle.kind} needs a polygon.")
            continue
        for table, polygon, _seat in footprints:
            if polygons_overlap(polygon, zone):
                message = f"{table.label} crosses {obstacle.kind} {obstacle.name}".strip()
                if obstacle.clearance_policy == "block":
                    errors.append(message)
                else:
                    warnings.append(message)
    if errors:
        raise DomainError("invalid_geometry", " ".join(errors), extra={"errors": errors, "warnings": warnings})
    if warnings and not override_reason:
        raise DomainError(
            "clearance_warning",
            "Clearance warnings need an audit reason before they can be saved.",
            extra={"warnings": warnings, "overridable": True},
        )
    return warnings
