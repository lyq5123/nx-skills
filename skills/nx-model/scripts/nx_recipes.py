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
# ANY flat part: an outline of straight lines and circular arcs, extruded to a
# thickness, with circular holes through it. This is the shape to reach for when a drawing is not one of the
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
PROFILE_PARAM_KEYS = ("points", "outline", "thickness", "holes")


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


# -----------------------------------------------------------------------------
# outline segments: straight AND circular
#
# An outline is a list of segments, each either
#     ["line", x1, y1, x2, y2]
#     ["arc",  xs, ys, xm, ym, xe, ye]     # start, a point ON the arc, end
#   the legacy "points" form is still accepted and means straight edges throughout
#
# The arc form is THREE POINTS rather than centre/radius/angles, on purpose. An
# angle pair plus a direction flag cannot distinguish the short arc from the long
# one between the same two angles - that ambiguity was written wrong twice while
# building this, which is the argument for removing it. Three points are what a
# drawing shows and what CAD tools ask for; the centre, radius and sweep are
# derived, and the direction is implied by which side the middle point is on.
#
# The area contribution of a segment comes from Green's theorem, 1/2 * integ(x dy
# - y dx). For a line that is (x1*y2 - x2*y1)/2; for a circular arc it has a closed
# form (below), so a profile with rounded corners or a slot is still EXACT - not
# tessellated, not approximated.
# -----------------------------------------------------------------------------
def _arc_from_three_points(xs, ys, xm, ym, xe, ye):
    """(cx, cy, r, a1_deg, sweep_deg) through three points, or None if collinear."""
    d = 2.0 * (xs * (ym - ye) + xm * (ye - ys) + xe * (ys - ym))
    if abs(d) < 1e-12:
        return None
    s1 = xs * xs + ys * ys
    s2 = xm * xm + ym * ym
    s3 = xe * xe + ye * ye
    cx = (s1 * (ym - ye) + s2 * (ye - ys) + s3 * (ys - ym)) / d
    cy = (s1 * (xe - xm) + s2 * (xs - xe) + s3 * (xm - xs)) / d
    r = math.hypot(xs - cx, ys - cy)
    a1 = math.degrees(math.atan2(ys - cy, xs - cx))
    a2 = math.degrees(math.atan2(ye - cy, xe - cx))
    sweep = (a2 - a1) % 360.0
    if d < 0.0:                      # the middle point sits on the clockwise side
        sweep -= 360.0
    return cx, cy, r, a1, sweep


def _parse_segments(params, bad):
    """Normalise params into a list of segments, appending problems to `bad`."""
    raw = params.get("outline")
    if raw is None:
        pts = params.get("points")
        if not isinstance(pts, (list, tuple)):
            bad.append("'points' must be a list of [x, y] pairs, got %s"
                       % type(pts).__name__)
            return []
        if len(pts) < 3:
            bad.append("'points' needs at least 3 pairs to enclose an area, got %d"
                       % len(pts))
            return []
        try:
            xy = [_as_point(p, "points[%d]" % i) for i, p in enumerate(pts)]
        except ValueError as exc:
            bad.append(str(exc))
            return []
        segs = []
        n = len(xy)
        for i in range(n):
            x1, y1 = xy[i]
            x2, y2 = xy[(i + 1) % n]
            if math.hypot(x2 - x1, y2 - y1) <= 1e-12:
                bad.append("points[%d] and points[%d] are the same point - the "
                           "outline has a zero-length edge" % (i, (i + 1) % n))
                return []
            segs.append(("line", x1, y1, x2, y2))
        return segs

    if not isinstance(raw, (list, tuple)):
        bad.append("'outline' must be a list of segments, got %s"
                   % type(raw).__name__)
        return []
    segs = []
    for i, s in enumerate(raw):
        where = "outline[%d]" % i
        if not isinstance(s, (list, tuple)) or not s:
            bad.append("%s must be a list starting with \"line\" or \"arc\", got %r"
                       % (where, s))
            continue
        kind = s[0]
        nums = s[1:]
        if kind not in ("line", "arc"):
            bad.append("%s: unknown segment type %r - use \"line\" or \"arc\""
                       % (where, kind))
            continue
        want = 4 if kind == "line" else 6
        if len(nums) != want:
            bad.append("%s: \"%s\" takes %d numbers, got %d%s"
                       % (where, kind, want, len(nums),
                          " (arc is start x,y, a point on the arc x,y, end x,y)"
                          if kind == "arc" else ""))
            continue
        ok = True
        for c in nums:
            if isinstance(c, bool) or not isinstance(c, (int, float)):
                bad.append("%s: all coordinates must be numbers, got %r" % (where, c))
                ok = False
                break
        if not ok:
            continue
        v = [float(c) for c in nums]
        if kind == "line":
            if math.hypot(v[2] - v[0], v[3] - v[1]) <= 1e-12:
                bad.append("%s: zero-length line" % where)
                continue
            segs.append(("line", v[0], v[1], v[2], v[3]))
        else:
            arc = _arc_from_three_points(*v)
            if arc is None:
                bad.append("%s: the three arc points are collinear, so they do not "
                           "define a circle" % where)
                continue
            cx, cy, r, a1, sweep = arc
            if r <= 1e-9:
                bad.append("%s: the arc has zero radius" % where)
                continue
            segs.append(("arc", cx, cy, r, a1, sweep))
    return segs


def _seg_start(s):
    if s[0] == "line":
        return s[1], s[2]
    _k, cx, cy, r, a1, _sw = s
    return cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))


def _seg_end(s):
    if s[0] == "line":
        return s[3], s[4]
    _k, cx, cy, r, a1, sw = s
    b = math.radians(a1 + sw)
    return cx + r * math.cos(b), cy + r * math.sin(b)


def _seg_mid(s):
    if s[0] == "line":
        return (s[1] + s[3]) / 2.0, (s[2] + s[4]) / 2.0
    _k, cx, cy, r, a1, sw = s
    b = math.radians(a1 + sw / 2.0)
    return cx + r * math.cos(b), cy + r * math.sin(b)


def _seg_length(s):
    if s[0] == "line":
        return math.hypot(s[3] - s[1], s[4] - s[2])
    return abs(math.radians(s[5])) * s[3]


def _seg_area_term(s):
    """Green's theorem contribution, 1/2 * integ(x dy - y dx), keeping the sign."""
    if s[0] == "line":
        _k, x1, y1, x2, y2 = s
        return (x1 * y2 - x2 * y1) / 2.0
    _k, cx, cy, r, a1, sw = s
    a = math.radians(a1)
    b = math.radians(a1 + sw)
    # int over the arc of  r^2 + r*(cx*cos t + cy*sin t)  dt
    inner = r * r * (b - a) + r * (cx * (math.sin(b) - math.sin(a))
                                  - cy * (math.cos(b) - math.cos(a)))
    return inner / 2.0


def _outline_area(segs):
    return sum(_seg_area_term(s) for s in segs)


def _seg_distance(pt, s):
    """Shortest distance from a point to one segment."""
    px, py = pt
    if s[0] == "line":
        _k, x0, y0, x1, y1 = s
        dx, dy = x1 - x0, y1 - y0
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 <= 0.0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / seg2))
        return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
    _k, cx, cy, r, a1, sw = s
    d = math.hypot(px - cx, py - cy)
    if d <= 1e-12:
        return r                        # the centre itself: every arc point is r away
    ang = math.degrees(math.atan2(py - cy, px - cx))
    # is the direction of the point inside the swept range?
    off = (ang - a1) % 360.0
    if sw > 0 and off <= sw + 1e-9:
        return abs(d - r)
    if sw < 0 and (off - 360.0) >= sw - 1e-9:
        return abs(d - r)
    sx, sy = _seg_start(s)
    ex, ey = _seg_end(s)
    return min(math.hypot(px - sx, py - sy), math.hypot(px - ex, py - ey))


def _discount_arcs(segs, step_deg=2.0):
    """Polygon approximation of the outline, for the inside/outside test only.

    The inside test is a yes/no and holes must additionally clear the outline by
    their full radius (checked exactly, below), so a fine tessellation here cannot
    turn a bad hole into an accepted one.
    """
    pts = []
    for s in segs:
        if s[0] == "line":
            pts.append((s[1], s[2]))
        else:
            _k, cx, cy, r, a1, sw = s
            n = max(2, int(abs(sw) / step_deg) + 1)
            for i in range(n):
                b = math.radians(a1 + sw * i / float(n))
                pts.append((cx + r * math.cos(b), cy + r * math.sin(b)))
    return pts


def _distance_to_outline(pt, segs):
    return min(_seg_distance(pt, s) for s in segs)


def profile_validate(params):
    """Validate a structured spec. Returns human-readable problems."""
    thickness = params.get("thickness")
    raw_holes = params.get("holes") or []
    if params.get("outline") is None and params.get("points") is None:
        return ["missing 'outline' (or the straight-edge 'points' form) - the closed "
                "boundary of the extruded profile"]

    bad = []
    if thickness is None:
        bad.append("missing parameter 'thickness' (the extrusion depth, mm)")
    elif isinstance(thickness, bool) or not isinstance(thickness, (int, float)):
        bad.append("'thickness' must be a number, got %r" % (thickness,))
    elif thickness <= 0:
        bad.append("'thickness' must be > 0, got %s" % thickness)

    segs = _parse_segments(params, bad)
    if bad:
        return bad
    if len(segs) < 3:
        bad.append("an outline needs at least 3 segments to enclose an area, got %d"
                   % len(segs))

    # the segments must join end to end into one closed loop
    tol = 1e-6
    for i in range(len(segs)):
        ex, ey = _seg_end(segs[i])
        nx_, ny_ = _seg_start(segs[(i + 1) % len(segs)])
        if math.hypot(ex - nx_, ey - ny_) > tol:
            bad.append("segment %d ends at (%.4f, %.4f) but segment %d starts at "
                       "(%.4f, %.4f) - the outline is not a closed loop; list the "
                       "segments in order, each starting where the last ended"
                       % (i, ex, ey, (i + 1) % len(segs), nx_, ny_))
            break
    if bad:
        return bad

    if abs(_outline_area(segs)) < 1e-9:
        bad.append("the outline encloses no area (Green's area ~ 0)")

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

    outline_poly = _discount_arcs(segs)
    for i, (hx, hy, dia) in enumerate(holes):
        if not _point_in_polygon((hx, hy), outline_poly):
            bad.append("hole %d at (%.3f, %.3f) is outside the outline" % (i, hx, hy))
            continue
        gap = _distance_to_outline((hx, hy), segs)      # exact, arcs included
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
    bad = []
    segs = _parse_segments(params, bad)
    if bad:
        raise RecipeError("cannot measure this outline: %s" % "; ".join(bad))
    thickness = params["thickness"]
    holes = [h for h in (params.get("holes") or []) if float(h[2]) > 0]

    vol = abs(_outline_area(segs)) * thickness
    faces = len(segs) + 2                  # one side face per segment + the two ends
    for _hx, _hy, dia in holes:
        vol -= math.pi * (dia / 2.0) ** 2 * thickness
        faces += 1
    return vol, faces


def profile_cylindrical_faces(params):
    bad = []
    segs = _parse_segments(params, bad)
    n = len([s for s in segs if s[0] == "arc"])
    n += len([h for h in (params.get("holes") or []) if float(h[2]) > 0])
    return n


def profile_segments(params):
    """The outline as normalised segments, for the builder to turn into curves.

    Each segment is either ("line", x1, y1, x2, y2) or ("arc", cx, cy, r, a1_deg,
    sweep_deg) - a positive sweep is counter-clockwise. Raises RecipeError rather
    than returning a partial list, because a builder cannot do anything useful with
    half an outline.
    """
    bad = []
    segs = _parse_segments(params, bad)
    if bad:
        raise RecipeError("this outline cannot be built: %s" % "; ".join(bad))
    return segs


def profile_seed(params):
    """A point ON the outline, to seed the section chain.

    The first segment's midpoint is on the profile by construction, which is what
    the section builder wants; an averaged 'centroid' of the vertices can fall
    outside a concave outline and then the chain fails.
    """
    return _seg_mid(profile_segments(params)[0])


register(PROFILE,
         PROFILE_PARAM_KEYS,
         profile_validate,
         profile_metrics,
         profile_cylindrical_faces,
         aliases=("profile", "extrude"))


# -----------------------------------------------------------------------------
# recipe: shaft_cradle
#
# A base plate carrying an upper block with a semicircular groove for a shaft,
# two ears with horizontal holes, and rounded upper outer corners. Modelled on
# StudyCADCAM 3D exercise 16.
#
# This is the first multi-body recipe: a base extrusion, a united upper block, a
# groove cut ALONG Y (so its profile is drawn in XZ and contains an arc), blends on
# edges that do not all run along Z, and holes in two directions.
#
# The volume is a decomposition, and each term is a shape this project already
# reasons about: a plate (with corner round-offs), a block, a groove = opening
# rectangle minus the half-disc of material that stays, and round-offs and holes
# that run through the depth.
#
# FACE COUNT IS NOT DERIVED. Several blends and the groove meet on shared faces, so
# an honest analytic count is not available; metrics() returns None for it and the
# journals report it without asserting it. Asserting a number copied from a build
# would be self-consistency dressed up as verification. The cylindrical face count
# IS derived, and it catches the commonest failure here - a blend or a hole that
# silently did not apply.
# -----------------------------------------------------------------------------
CRADLE = "shaft_cradle"
CRADLE_PARAM_KEYS = ("base_l", "base_w", "base_t", "corner_r",
                     "top_l", "top_w", "top_h", "top_setback",
                     "saddle_w", "saddle_r", "ear_r", "hole_d",
                     "base_hole_x", "base_hole_y", "ear_hole_x", "ear_hole_z")


def cradle_validate(params):
    p = {k: params.get(k) for k in CRADLE_PARAM_KEYS}
    bad = []
    for k in CRADLE_PARAM_KEYS:
        v = p[k]
        if v is None:
            bad.append("missing parameter '%s'" % k)
        elif not isinstance(v, (int, float)) or isinstance(v, bool):
            bad.append("parameter '%s' must be a number, got %r" % (k, v))
    if bad:
        return bad

    bl, bw, bt = p["base_l"], p["base_w"], p["base_t"]
    cr, tl, tw, th, sb = (p["corner_r"], p["top_l"], p["top_w"], p["top_h"],
                          p["top_setback"])
    sw, sr, er, hd = p["saddle_w"], p["saddle_r"], p["ear_r"], p["hole_d"]
    bhx, bhy, ehx, ehz = p["base_hole_x"], p["base_hole_y"], p["ear_hole_x"], p["ear_hole_z"]

    if min(bl, bw, bt, tl, tw, th) <= 0:
        bad.append("base_l/base_w/base_t/top_l/top_w/top_h must all be > 0")
    if min(cr, sr, er, sb, bhx, bhy, ehx, ehz) < 0:
        bad.append("corner_r/saddle_r/ear_r/top_setback and the hole positions "
                   "must be >= 0")
    if hd <= 0:
        bad.append("hole_d must be > 0, got %s" % hd)
    if sw <= 0:
        bad.append("saddle_w must be > 0, got %s" % sw)
    if bad:
        return bad

    if tl > bl:
        bad.append("top_l=%.3f is longer than base_l=%.3f" % (tl, bl))
    if tw > bw:
        bad.append("top_w=%.3f is deeper than base_w=%.3f" % (tw, bw))
    if sb + tw > bw:
        bad.append("top_setback=%.3f + top_w=%.3f overhangs base_w=%.3f"
                   % (sb, tw, bw))
    if cr > 0 and cr >= min(bl, bw) / 2.0:
        bad.append("corner_r=%.3f is too large for a %.1fx%.1f base" % (cr, bl, bw))

    if sr <= 0:
        bad.append("saddle_r must be > 0, got %s" % sr)
    elif 2.0 * sr > sw:
        bad.append("saddle_w=%.3f is narrower than the groove diameter 2*saddle_r="
                   "%.3f - the arc would not fit inside the opening" % (sw, 2 * sr))
    if sr > th:
        bad.append("saddle_r=%.3f is deeper than top_h=%.3f, so the groove would cut "
                   "into the base plate" % (sr, th))
    if sw >= tl:
        bad.append("saddle_w=%.3f leaves no ear: it must be less than top_l=%.3f"
                   % (sw, tl))

    ear_w = (tl - sw) / 2.0
    if er > 0:
        if er >= th:
            bad.append("ear_r=%.3f is too large for top_h=%.3f" % (er, th))
        if er >= ear_w:
            bad.append("ear_r=%.3f is wider than the ear itself (ear width %.3f)"
                       % (er, ear_w))

    # base holes: inside the base, and clear of the R10 corner rounds
    for name, x, y in (("left", bhx, bhy), ("right", bl - bhx, bhy)):
        if x - hd / 2.0 <= 0.0 or y - hd / 2.0 <= 0.0:
            bad.append("base hole (%s) breaks through the plate edge: centre "
                       "(%.3f, %.3f), dia %.3f" % (name, x, y, hd))
        elif (bl - x) - hd / 2.0 <= 0.0 or (bw - y) - hd / 2.0 <= 0.0:
            bad.append("base hole (%s) breaks through the far edge" % name)
        elif cr > 0:
            # the hole must sit inside the rounded corner's circle, or it breaks out
            # through the round
            centre = min(x, bl - x) if y < bw / 2.0 else None
            if y <= cr and x <= cr:
                d = math.hypot(cr - x, cr - y)
                if d + hd / 2.0 > cr:
                    bad.append("base hole (%s) breaks out through the R%.3f corner "
                               "round: it is %.3f from the round's centre and its "
                               "radius is %.3f" % (name, cr, d, hd / 2.0))
            del centre

    # ear holes: inside the ear, between the base top and the top face
    if ehx - hd / 2.0 <= 0.0:
        bad.append("ear hole breaks through the end face: ear_hole_x=%.3f, dia %.3f"
                   % (ehx, hd))
    elif ehx + hd / 2.0 >= ear_w:
        bad.append("ear hole is not fully on the ear: ear_hole_x + radius = %.3f but "
                   "the ear is only %.3f wide" % (ehx + hd / 2.0, ear_w))
    if ehz - hd / 2.0 <= bt:
        bad.append("ear hole dips below the base top: ear_hole_z=%.3f, radius %.3f, "
                   "base_t=%.3f" % (ehz, hd / 2.0, bt))
    elif ehz + hd / 2.0 >= bt + th:
        bad.append("ear hole breaks through the top face: ear_hole_z=%.3f, radius "
                   "%.3f, top face at z=%.3f" % (ehz, hd / 2.0, bt + th))
    return bad


def cradle_metrics(params):
    bl, bw, bt = params["base_l"], params["base_w"], params["base_t"]
    cr, tl, tw, th = (params["corner_r"], params["top_l"], params["top_w"],
                      params["top_h"])
    sw, sr, er, hd = (params["saddle_w"], params["saddle_r"], params["ear_r"],
                      params["hole_d"])
    r_hole = hd / 2.0

    # base plate, less the two front corner round-offs
    vol = bl * bw * bt
    if cr > 0:
        vol -= 2.0 * (cr * cr - math.pi * cr * cr / 4.0) * bt
    # base holes run through the base only
    vol -= 2 * math.pi * r_hole ** 2 * bt

    # upper block
    vol += tl * tw * th

    # groove: the opening rectangle less the material that stays below the arc.
    #
    # That "material kept" is NOT the half-disc. The half-disc is bounded by the
    # arc and the DIAMETER at the level of the groove's centre; what actually stays
    # is the thinner sliver between the arc and the base top:
    #     integral over the arc of (arc(x) - z0) dx  =  R^2 * (2 - pi/2)
    # Using pi*R^2/2 instead is wrong by R^2*(pi - 2). It was wrong here until the
    # staged volumes caught it - the kernel removed 703.429 mm^2 per unit depth
    # where the half-disc predicted 446.571, a gap that accounted for the entire
    # 8990 mm^3 discrepancy. The model was right; this formula was not.
    if sr > 0:
        kept_area = sr * sr * (2.0 - math.pi / 2.0)
        groove_area = sw * th - kept_area
        vol -= groove_area * tw

    # blends and holes that run through the block's depth
    if er > 0:
        vol -= 2.0 * (er * er - math.pi * er * er / 4.0) * tw
    vol -= 2 * math.pi * r_hole ** 2 * tw

    # None: no honest analytic face count for this shape (see the note above)
    return vol, None


def cradle_cylindrical_faces(params):
    n = 0
    if params["corner_r"] > 0:
        n += 2                      # the two base corner rounds
    if params["hole_d"] > 0:
        n += 2                      # base holes
        n += 2                      # ear holes
    if params["ear_r"] > 0:
        n += 2                      # the two upper outer rounds
    if params["saddle_r"] > 0:
        n += 1                      # the groove
    return n


register(CRADLE,
         CRADLE_PARAM_KEYS,
         cradle_validate,
         cradle_metrics,
         cradle_cylindrical_faces,
         aliases=("cradle", "saddle"))
