# =============================================================================
#  nx_recipes - per-part-type rules for the nx-model journals
#
#  A "recipe" owns everything that is specific to one kind of part:
#    * the parameters it takes
#    * how combinations are rejected BEFORE NX is touched
#    * the analytic volume / face count that the build self-check and the
#      independent verifier both measure against
#
#  Adding a part type means adding a recipe here plus a builder journal beside
#  it. The existing journals do not change: they go through
#  nx_common.validate_part() / part_metrics() / cylindrical_faces().
#
#  THIS FILE IMPORTS NOTHING ELSE FROM THE SKILL and uses only the standard
#  library, so plain Python can import it and unit-test the rules with no NX
#  installed. That is deliberate - it is where the pure geometry logic lives.
# =============================================================================
import math


class RecipeError(Exception):
    """A part type has no recipe registered."""


PLATE = "mounting_plate"
DEFAULT_PART = PLATE           # what a spec gets when it names no part type


def unknown_part_message(name):
    """The human-readable complaint for a part type nobody registered."""
    return ("unknown part type %r - this skill knows: %s"
            % (name, ", ".join(known_parts()) or "(none registered)"))


# -----------------------------------------------------------------------------
# registry
# -----------------------------------------------------------------------------
_RECIPES = {}


def register(name, param_keys, validate, metrics, cylindrical_faces, aliases=()):
    """Register one part type. `aliases` are alternate accepted spec values."""
    entry = {
        "name": name,
        "param_keys": tuple(param_keys),
        "validate": validate,
        "metrics": metrics,
        "cylindrical_faces": cylindrical_faces,
    }
    _RECIPES[name] = entry
    for alias in aliases:
        _RECIPES[alias] = entry
    return entry


def known_parts():
    """Registered part names, excluding aliases, sorted for messages."""
    return sorted({e["name"] for e in _RECIPES.values()})


def has_recipe(name):
    return name in _RECIPES


def canonical_name(name):
    """The registered name behind a spec's `part` value, resolving aliases.

    Recorded in the result file, so a spec saying "flange" and one saying
    "circular_flange" do not look like two different part types in the output.
    """
    return _lookup(name)["name"]


def _lookup(name):
    try:
        return _RECIPES[name]
    except (KeyError, TypeError):
        raise RecipeError(unknown_part_message(name))


def param_keys(name):
    return _lookup(name)["param_keys"]


def validate(name, params):
    return list(_lookup(name)["validate"](params))


def metrics(name, params):
    return _lookup(name)["metrics"](params)


def cylindrical_faces(name, params):
    return _lookup(name)["cylindrical_faces"](params)


# -----------------------------------------------------------------------------
# recipe: mounting_plate
#
# A rectangular plate with optional corner holes, a central bore and corner
# fillets. Every number below is analytic; the volume must match what NX
# measures or the build is declared wrong.
# -----------------------------------------------------------------------------
PLATE_PARAM_KEYS = ("plate_w", "plate_h", "plate_t",
                    "hole_d", "hole_inset", "bore_d", "fillet_r")


def _fillet_corner_gap(i, fr):
    """Shortest distance from the hole centre (i, i) to the region a corner fillet removes.

    That region is bounded by the two plate edges running from the corner out to
    `fr`, and by the fillet ARC between them. The hole is a disc of radius d/2, so
    it only collides when this gap is <= d/2.

    The subtlety that makes this worth a named function: the fillet CIRCLE and the
    hole CIRCLE can overlap while the arc - which only spans the 90 degrees facing
    the corner - is nowhere near the hole. A plain centre-to-centre circle test
    therefore rejects perfectly legal parts. That mistake shipped here once: an
    R8 fillet with holes inset 12 was refused, even though NX builds it and the
    analytic volume for it matches to 0.0000. Do not go back to a circle test.
    """
    u = i - fr
    cands = [
        u * u + i * i,                                            # arc ends, where it meets the edges
        2 * u * u + 2 * math.sqrt(2) * u * fr + fr * fr,           # where the arc crosses the diagonal
    ]
    if i < fr:
        cands.append(i * i)                                       # foot of the perpendicular on an edge
    return math.sqrt(max(min(cands), 0.0))


def plate_validate(params):
    """Return a list of human-readable problems. Empty list means buildable.

    These are the conflicts that otherwise surface as an opaque kernel error
    halfway through a build, or worse, as silently wrong geometry. Every return
    is phrased for a person reading a log, not for a machine parsing codes.
    """
    p = {k: params.get(k) for k in PLATE_PARAM_KEYS}
    bad = []

    for k in PLATE_PARAM_KEYS:
        v = p[k]
        if v is None:
            bad.append("missing parameter '%s'" % k)
        elif not isinstance(v, (int, float)) or isinstance(v, bool):
            bad.append("parameter '%s' must be a number, got %r" % (k, v))
    if bad:
        return bad

    w, h, t = p["plate_w"], p["plate_h"], p["plate_t"]
    hd, i = p["hole_d"], p["hole_inset"]
    bd, fr = p["bore_d"], p["fillet_r"]

    if w <= 0 or h <= 0 or t <= 0:
        bad.append("plate_w/plate_h/plate_t must all be > 0 (got %s/%s/%s)" % (w, h, t))
    if hd < 0 or bd < 0 or fr < 0:
        bad.append("hole_d/bore_d/fillet_r must be >= 0 (got %s/%s/%s)" % (hd, bd, fr))
    if bad:
        return bad

    if hd > 0:
        if i - hd / 2.0 <= 0.0:
            bad.append(
                "corner holes break through the plate edge: hole_inset=%.3f with "
                "hole_d=%.3f needs hole_inset > %.3f" % (i, hd, hd / 2.0))
        elif i >= min(w, h) / 2.0:
            bad.append(
                "hole_inset=%.3f is at or past the centreline of a %.1fx%.1f plate, so "
                "the four corner holes coincide. Need hole_inset < %.3f"
                % (i, w, h, min(w, h) / 2.0))
        elif (w - 2.0 * i) <= hd or (h - 2.0 * i) <= hd:
            bad.append(
                "adjacent corner holes overlap: they are %.3f and %.3f apart but "
                "hole_d=%.3f" % (w - 2.0 * i, h - 2.0 * i, hd))
        # corner hole vs corner fillet. The fillet removes the region bounded by
        # the two plate edges out to fr and the arc between them; only a hole that
        # actually reaches that region collides.
        if fr > 0:
            gap = _fillet_corner_gap(i, fr)
            if gap <= hd / 2.0:
                bad.append(
                    "corner fillet R%.3f collides with the hole at (%.3f, %.3f): the "
                    "fillet comes within %.3f of the hole centre but the hole radius "
                    "is %.3f" % (fr, i, i, gap, hd / 2.0))

    if bd > 0:
        if bd >= min(w, h):
            bad.append("bore_d=%.3f does not fit in a %.1fx%.1f plate" % (bd, w, h))
        if hd > 0:
            c = math.hypot(w / 2.0 - i, h / 2.0 - i)
            if c <= bd / 2.0 + hd / 2.0:
                bad.append(
                    "central bore D%.3f overlaps the corner holes "
                    "(centres %.3f apart)" % (bd, c))

    if fr > 0:
        if fr >= min(w, h) / 2.0:
            bad.append("fillet_r=%.3f is too large for a %.1fx%.1f plate" % (fr, w, h))

    return bad


def plate_metrics(params):
    """Analytic (volume, face count) for the mounting-plate recipe."""
    w, h, t = params["plate_w"], params["plate_h"], params["plate_t"]
    hd, i = params["hole_d"], params["hole_inset"]
    bd, fr = params["bore_d"], params["fillet_r"]

    vol = w * h * t
    # top + bottom, then the four sides: flat without a fillet, and with one the
    # four flats are replaced by 4 cylinders plus 4 flat strips between them
    faces = 2 + (8 if fr > 0 else 4)
    if hd > 0:
        vol -= 4 * math.pi * (hd / 2.0) ** 2 * t
        faces += 4
    if bd > 0:
        vol -= math.pi * (bd / 2.0) ** 2 * t
        faces += 1
    if fr > 0:
        vol -= 4 * (fr ** 2 - math.pi * fr ** 2 / 4.0) * t
    return vol, faces


def plate_cylindrical_faces(params):
    """Holes + bore + fillet arcs, used by the verifier as a topology check."""
    hd, bd, fr = params["hole_d"], params["bore_d"], params["fillet_r"]
    n = (4 if hd > 0 else 0) + (1 if bd > 0 else 0)
    if fr > 0:
        n += 4
    return n


register(PLATE,
         PLATE_PARAM_KEYS,
         plate_validate,
         plate_metrics,
         plate_cylindrical_faces)


# -----------------------------------------------------------------------------
# recipe: circular_flange
#
# A disc with a central bore, a bolt circle and an optional chamfer on both outer
# rims. Every number is analytic; the volume must match what NX measures.
# -----------------------------------------------------------------------------
FLANGE = "circular_flange"
FLANGE_PARAM_KEYS = ("od", "id", "thk", "bcd", "n_bolts", "bolt_d", "chamfer")


def flange_validate(params):
    p = {k: params.get(k) for k in FLANGE_PARAM_KEYS}
    bad = []
    for k in FLANGE_PARAM_KEYS:
        v = p[k]
        if v is None:
            bad.append("missing parameter '%s'" % k)
        elif not isinstance(v, (int, float)) or isinstance(v, bool):
            bad.append("parameter '%s' must be a number, got %r" % (k, v))
    if bad:
        return bad

    od, idia, thk = p["od"], p["id"], p["thk"]
    bcd, n, bd, ch = p["bcd"], p["n_bolts"], p["bolt_d"], p["chamfer"]

    if od <= 0 or thk <= 0:
        bad.append("od and thk must both be > 0 (got %s/%s)" % (od, thk))
    if idia < 0 or bd < 0 or ch < 0 or n < 0:
        bad.append("id/bolt_d/chamfer/n_bolts must be >= 0 (got %s/%s/%s/%s)"
                   % (idia, bd, ch, n))
    if bad:
        return bad
    if abs(n - round(n)) > 1e-9:
        bad.append("n_bolts must be a whole number, got %s" % n)
    if idia >= od / 2.0:
        bad.append("id=%.3f leaves no wall inside od=%.3f (id must be < od/2)"
                   % (idia, od))

    # chamfer runs inward from the outer radius; it must not eat the full wall
    if ch > 0:
        if ch >= thk / 2.0:
            bad.append("chamfer=%.3f is too deep for thk=%.3f - the two rim "
                       "chamfers would meet (need chamfer < thk/2)" % (ch, thk))
        if idia > 0 and ch >= (od - idia) / 2.0:
            bad.append("chamfer=%.3f is wider than the wall between od=%.3f and "
                       "id=%.3f" % (ch, od, idia))

    if n > 0 and bd > 0:
        outer = bcd / 2.0 + bd / 2.0
        inner = bcd / 2.0 - bd / 2.0
        if outer >= od / 2.0 - ch:
            bad.append("bolt holes reach past the outer edge: bcd/2 + bolt_d/2 = "
                       "%.3f but the usable radius is %.3f (od/2 - chamfer)"
                       % (outer, od / 2.0 - ch))
        if idia > 0 and inner <= idia / 2.0:
            bad.append("bolt holes break into the bore: bcd/2 - bolt_d/2 = %.3f "
                       "but the bore radius is %.3f" % (inner, idia / 2.0))
        # adjacent holes must not merge
        if n >= 2:
            chord = 2.0 * (bcd / 2.0) * math.sin(math.pi / n)
            if chord <= bd:
                bad.append("%d bolt holes D%.3f on BCD %.3f would merge: adjacent "
                           "centres are only %.3f apart" % (n, bd, bcd, chord))
    return bad


def flange_metrics(params):
    od, idia, thk = params["od"], params["id"], params["thk"]
    bcd, n, bd, ch = params["bcd"], params["n_bolts"], params["bolt_d"], params["chamfer"]

    vol = math.pi * (od / 2.0) ** 2 * thk
    # top + bottom + the outer cylinder
    faces = 3
    if idia > 0:
        vol -= math.pi * (idia / 2.0) ** 2 * thk
        faces += 1
    if n > 0 and bd > 0:
        vol -= n * math.pi * (bd / 2.0) ** 2 * thk
        faces += int(round(n))
    if ch > 0:
        # each rim chamfer removes a right triangle of legs ch x ch revolved about
        # the axis: area ch^2/2 with its centroid at radius od/2 - ch/3, so
        #   V = 2*pi * (ch^2/2) * (od/2 - ch/3) = pi*ch^2*(od/2 - ch/3)
        vol -= 2.0 * math.pi * ch * ch * (od / 2.0 - ch / 3.0)
        faces += 2                       # two conical faces
    return vol, faces


def flange_cylindrical_faces(params):
    n = 1 if params["od"] > 0 else 0        # outer cylinder
    if params["id"] > 0:
        n += 1                              # bore
    if params["n_bolts"] > 0 and params["bolt_d"] > 0:
        n += int(round(params["n_bolts"]))
    return n


register(FLANGE,
         FLANGE_PARAM_KEYS,
         flange_validate,
         flange_metrics,
         flange_cylindrical_faces,
         aliases=("flange",))


# -----------------------------------------------------------------------------
# recipe: l_bracket
#
# An L-shaped profile extruded across its width, with two mounting holes through
# the horizontal leg. Profile area = base_l*base_t + wall_t*(total_h - base_t).
# -----------------------------------------------------------------------------
BRACKET = "l_bracket"
BRACKET_PARAM_KEYS = ("base_l", "base_t", "wall_t", "total_h", "width",
                      "hole_d", "hole_inset_x")


def bracket_validate(params):
    p = {k: params.get(k) for k in BRACKET_PARAM_KEYS}
    bad = []
    for k in BRACKET_PARAM_KEYS:
        v = p[k]
        if v is None:
            bad.append("missing parameter '%s'" % k)
        elif not isinstance(v, (int, float)) or isinstance(v, bool):
            bad.append("parameter '%s' must be a number, got %r" % (k, v))
    if bad:
        return bad

    bl, bt, wt, th, wd = (p["base_l"], p["base_t"], p["wall_t"], p["total_h"], p["width"])
    hd, ix = p["hole_d"], p["hole_inset_x"]

    if min(bl, bt, wt, th, wd) <= 0:
        bad.append("base_l/base_t/wall_t/total_h/width must all be > 0 (got %s/%s/%s/%s/%s)"
                   % (bl, bt, wt, th, wd))
    if hd < 0:
        bad.append("hole_d must be >= 0 (got %s)" % hd)
    if bad:
        return bad

    if bt >= th:
        bad.append("base_t=%.3f must be less than total_h=%.3f, or there is no "
                   "vertical leg" % (bt, th))
    if wt >= bl:
        bad.append("wall_t=%.3f must be less than base_l=%.3f" % (wt, bl))

    if hd > 0:
        if ix - hd / 2.0 <= 0.0:
            bad.append("mounting hole breaks through the free end: hole_inset_x=%.3f "
                       "with hole_d=%.3f needs hole_inset_x > %.3f"
                       % (ix, hd, hd / 2.0))
        elif bl - ix - hd / 2.0 <= wt:
            bad.append("mounting hole at x=%.3f reaches into the wall (wall_t=%.3f); "
                       "need hole_inset_x < %.3f" % (bl - ix, wt, bl - wt - hd / 2.0))
        elif 2.0 * ix >= bl:
            bad.append("hole_inset_x=%.3f puts the two holes at or past the centre "
                       "of base_l=%.3f - they would coincide" % (ix, bl))
        elif hd >= bt:
            bad.append("hole_d=%.3f is not smaller than base_t=%.3f, so the hole "
                       "would break through the leg" % (hd, bt))
    return bad


def bracket_metrics(params):
    bl, bt, wt, th, wd = (params["base_l"], params["base_t"], params["wall_t"],
                          params["total_h"], params["width"])
    hd = params["hole_d"]

    area = bl * bt + wt * (th - bt)
    vol = area * wd
    # 6 faces around the L profile + the two end faces
    faces = 8
    if hd > 0:
        vol -= 2 * math.pi * (hd / 2.0) ** 2 * wd
        faces += 2
    return vol, faces


def bracket_cylindrical_faces(params):
    return 2 if params["hole_d"] > 0 else 0


register(BRACKET,
         BRACKET_PARAM_KEYS,
         bracket_validate,
         bracket_metrics,
         bracket_cylindrical_faces,
         aliases=("bracket", "l-bracket"))


# -----------------------------------------------------------------------------
# recipe: extruded_profile
#
# ANY straight-sided part: a closed polygon extruded to a thickness, with circular
# holes through it. This is the shape to reach for when a drawing is not one of the
# named parts - most plate-like components (brackets, covers, gussets, channels,
# link plates) are exactly this, and the volume is exact:
#
#     |shoelace area of the polygon| * thickness  -  sum(pi * r^2 * thickness)
#
# Unlinke the named recipes, params here are STRUCTURED:
#     "points": [[x, y], ...]        the closed outline, in order (at least 3)
#     "thickness": number            extrusion depth
#     "holes":  [[x, y, dia], ...]   optional through-holes
#
# The polygon is taken as closed - do not repeat the first point at the end.
# Straight edges only: an arc in the outline needs a named recipe with its own
# analytic formula (a circle is not a polygon).
# -----------------------------------------------------------------------------
PROFILE = "extruded_profile"
PROFILE_PARAM_KEYS = ("points", "thickness", "holes")


def _as_point(value, what):
    """Validate one [x, y] pair, returning (x, y) or raising ValueError."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("%s must be [x, y], got %r" % (what, value))
    out = []
    for c in value:
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            raise ValueError("%s must be numbers, got %r" % (what, value))
        out.append(float(c))
    return out[0], out[1]


def _shoelace(points):
    """Signed area of a closed polygon (positive = counter-clockwise)."""
    total = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def _point_in_polygon(pt, points):
    """Ray casting - True when the point is strictly inside."""
    x, y = pt
    inside = False
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xin = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xin:
                inside = not inside
    return inside


def _distance_to_polygon_edge(pt, points):
    """Shortest distance from a point to any edge of the polygon."""
    px, py = pt
    best = float("inf")
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        seg2 = dx * dx + dy * dy
        if seg2 <= 0.0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / seg2))
        d = math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
        if d < best:
            best = d
    return best


def profile_validate(params):
    """Validate a structured spec. Returns human-readable problems."""
    raw_points = params.get("points")
    thickness = params.get("thickness")
    raw_holes = params.get("holes") or []

    if raw_points is None:
        return ["missing parameter 'points' - the closed outline as [[x, y], ...]"]
    if not isinstance(raw_points, (list, tuple)):
        return ["'points' must be a list of [x, y] pairs, got %s"
                % type(raw_points).__name__]
    if thickness is None:
        return ["missing parameter 'thickness' (the extrusion depth, mm)"]
    bad = []
    if isinstance(thickness, bool) or not isinstance(thickness, (int, float)):
        bad.append("'thickness' must be a number, got %r" % (thickness,))
    elif thickness <= 0:
        bad.append("'thickness' must be > 0, got %s" % thickness)

    if len(raw_points) < 3:
        bad.append("'points' needs at least 3 pairs to enclose an area, got %d"
                   % len(raw_points))
    points = []
    for i, pv in enumerate(raw_points):
        try:
            points.append(_as_point(pv, "points[%d]" % i))
        except ValueError as exc:
            bad.append(str(exc))
    if bad:
        return bad

    n = len(points)
    for i in range(n):
        if points[i] == points[(i + 1) % n]:
            bad.append("points[%d] and points[%d] are the same point - the outline "
                       "has a zero-length edge" % (i, (i + 1) % n))
            break
    area = _shoelace(points)
    if abs(area) < 1e-9:
        bad.append("the outline encloses no area (shoelace area ~ 0) - the points "
                   "are probably collinear")

    holes = []
    if not isinstance(raw_holes, (list, tuple)):
        bad.append("'holes' must be a list of [x, y, dia], got %s"
                   % type(raw_holes).__name__)
    else:
        for i, hv in enumerate(raw_holes):
            if not isinstance(hv, (list, tuple)) or len(hv) != 3:
                bad.append("holes[%d] must be [x, y, dia], got %r" % (i, hv))
                continue
            try:
                hx, hy = _as_point(hv[:2], "holes[%d]" % i)
            except ValueError as exc:
                bad.append(str(exc))
                continue
            dia = hv[2]
            if isinstance(dia, bool) or not isinstance(dia, (int, float)):
                bad.append("holes[%d] diameter must be a number, got %r" % (i, dia))
                continue
            if dia <= 0:
                bad.append("holes[%d] diameter must be > 0, got %s" % (i, dia))
                continue
            holes.append((hx, hy, float(dia)))
    if bad:
        return bad

    for i, (hx, hy, dia) in enumerate(holes):
        if not _point_in_polygon((hx, hy), points):
            bad.append("hole %d at (%.3f, %.3f) is outside the outline" % (i, hx, hy))
            continue
        gap = _distance_to_polygon_edge((hx, hy), points)
        if gap <= dia / 2.0:
            bad.append("hole %d at (%.3f, %.3f) crosses the outline: it is %.3f from "
                       "the nearest edge but its radius is %.3f"
                       % (i, hx, hy, gap, dia / 2.0))
    if not bad:
        for i in range(len(holes)):
            for j in range(i + 1, len(holes)):
                ax, ay, ad = holes[i]
                bx, by, bd = holes[j]
                if math.hypot(ax - bx, ay - by) <= ad / 2.0 + bd / 2.0:
                    bad.append("holes %d and %d overlap (centres %.3f apart, radii "
                               "%.3f + %.3f)" % (i, j, math.hypot(ax - bx, ay - by),
                                                 ad / 2.0, bd / 2.0))
    return bad


def profile_metrics(params):
    points = [_as_point(p, "point") for p in params["points"]]
    thickness = params["thickness"]
    holes = [_as_point(h[:2], "hole") + (float(h[2]),)
             for h in (params.get("holes") or [])]

    area = abs(_shoelace(points))
    vol = area * thickness
    # one side face per edge, plus the two end faces
    faces = len(points) + 2
    for _hx, _hy, dia in holes:
        if dia > 0:
            vol -= math.pi * (dia / 2.0) ** 2 * thickness
            faces += 1
    return vol, faces


def profile_cylindrical_faces(params):
    return len([h for h in (params.get("holes") or []) if float(h[2]) > 0])


register(PROFILE,
         PROFILE_PARAM_KEYS,
         profile_validate,
         profile_metrics,
         profile_cylindrical_faces,
         aliases=("profile", "extrude"))
