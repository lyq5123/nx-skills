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
