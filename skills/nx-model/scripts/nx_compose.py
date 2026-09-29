# =============================================================================
#  nx_compose - a part described as a SEQUENCE of features
#
#  The named recipes each hard-code one shape. This is the general case: a spec
#  lists operations and they are executed in order.
#
#      "part": "composed",
#      "features": [
#        {"op": "profile", "plane": "xy", "thickness": 20, "outline": [...]},
#        {"op": "profile", "plane": "xz", "at": 40, "mode": "add", "thickness": 20,
#         "outline": [...]},
#        {"op": "hole", "axis": "y", "at": [60, 80], "dia": 30, "through": true},
#        {"op": "boss", "axis": "z", "at": [110, 80], "dia": 55, "height": 25},
#        {"op": "blend",   "r": 30, "edges": {"parallel_to": "z"}},
#        {"op": "chamfer", "c": 2,  "edges": {"from_feature": 0}}
#      ]
#
#  A boss ADDS material and a hole REMOVES it, always - "hole" with "mode": "add"
#  is rejected rather than quietly overruled. Only a profile chooses, through "mode"
#  (default "add"), and only a cut may say "through": true (an addition with no end
#  would extend without limit).
#
#  PLANES place the outline's two coordinates and fix the extrusion direction:
#      "xy"  u->x  v->y  normal +z      "xz"  u->x  v->z  normal +y
#      "yz"  u->y  v->z  normal +x
#  so a hole along Y is a circle in the "xz" plane, and a boss along Z is a circle
#  in "xy" - the axis and the plane are two views of the same thing.
#
#  SELECTORS say which edges a blend or chamfer applies to. They are geometric,
#  never an index into a face list, because that order is not stable across
#  rebuilds:
#      {"from_feature": n}          the edges/faces feature n created
#                                   (Feature.GetEdges(); NOT GetEntities, which
#                                   returns nothing - verified on NX 2406)
#      {"parallel_to": "x"|"y"|"z"} edges running along that axis
#      {"mid_at": {"z": 20}}        ...whose midpoint is at that coordinate
#  The keys combine with AND.
#
#  THE VOLUME HAS NO CLOSED FORM for an arbitrary feature list, so the reference
#  value is SAMPLED. It is still an independent path - it never asks NX, so it
#  catches a bad boolean or a missing feature - but it is a ~1% check where the
#  named recipes are exact, and blends/chamfers are not modelled in it at all.
#  Report it as sampled, not as verified to 0.0000.
# =============================================================================
import json
import math
import random

import nx_recipes

from nx_recipes import (
    RecipeError, _as_point, _discount_arcs, _outline_area, _parse_segments,
    _seg_end, _seg_mid, _seg_start,
)

COMPOSED = "composed"
PLANES = ("xy", "xz", "yz")
AXES = ("x", "y", "z")
OPS = ("profile", "hole", "boss", "blend", "chamfer")
_SOLID_OPS = ("profile", "hole", "boss")

# (u axis, v axis, normal axis) for each plane
_PLANE_AXES = {"xy": ("x", "y", "z"), "xz": ("x", "z", "y"), "yz": ("y", "z", "x")}
# a hole/boss along an axis is a profile in the plane perpendicular to it
_AXIS_PLANE = {"x": "yz", "y": "xz", "z": "xy"}

CIRCLE_SEGMENTS = 48

# The reference volume is SAMPLED, so the agreement demanded of the kernel is
# looser than for a closed form. 1% is roughly 3 standard errors at this sample
# count for a part filling about a sixth of its bounding box; composed_report()
# returns the actual sigma so the log can show how tight the check really was.
SAMPLES = 400000
SAMPLING_TOLERANCE = 0.01


def plane_axes(plane):
    """(u axis, v axis, normal axis) for a plane name - what a builder places curves in."""
    return _PLANE_AXES[plane]


def seed_point(feature):
    """A point ON the feature's outline, to seed the section chain.

    The first segment's midpoint is on the profile by construction; an averaged
    'centroid' of the vertices can fall outside a concave outline and then the
    chain fails. Same reasoning as profile_seed() for the flat profile recipe.
    """
    return _seg_mid(feature["_segments"][0])


def length_of(feature):
    """How far along its normal the feature's material reaches, or None for "through"."""
    return feature["thickness"]


def circle_outline(cx, cy, dia, segments=CIRCLE_SEGMENTS):
    """A circle as a closed polygon outline.

    Chords, not arcs: this is what the reference sampler integrates, and it is also
    a fine section for the kernel. Use an explicit `arc` outline when the exact area
    of a curved profile matters.
    """
    pts = []
    r = dia / 2.0
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return [("line", pts[i][0], pts[i][1],
             pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1])
            for i in range(len(pts))]


def _outline_segments(feature, bad):
    """The profile outline as segments, checked for being one closed loop."""
    segs = _parse_segments(feature, bad)
    if not segs:
        return []
    if len(segs) < 3:
        bad.append("an outline needs at least 3 segments to enclose an area")
        return []
    tol = 1e-6
    for i in range(len(segs)):
        ex, ey = _seg_end(segs[i])
        nx_, ny_ = _seg_start(segs[(i + 1) % len(segs)])
        if math.hypot(ex - nx_, ey - ny_) > tol:
            bad.append("outline segment %d ends at (%.4f, %.4f) but segment %d starts "
                       "at (%.4f, %.4f) - the outline is not a closed loop; list the "
                       "segments in order" % (i, ex, ey, (i + 1) % len(segs), nx_, ny_))
            return []
    if abs(_outline_area(segs)) < 1e-9:
        bad.append("the outline encloses no area")
        return []
    return segs


def _positive(value, where, name, bad):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        bad.append("%s: %s must be a positive number, got %r" % (where, name, value))
        return None
    return float(value)


def parse_features(features, bad):
    """Validate and normalise a feature list. Returns [] when anything is wrong."""
    if not isinstance(features, (list, tuple)) or not features:
        bad.append("'features' must be a non-empty list of operations")
        return []
    out = []
    for i, raw in enumerate(features):
        where = "features[%d]" % i
        if not isinstance(raw, dict):
            bad.append("%s must be an object, got %s" % (where, type(raw).__name__))
            continue
        op = raw.get("op")
        if op not in OPS:
            bad.append("%s: unknown op %r - use one of %s"
                       % (where, op, ", ".join(OPS)))
            continue
        f = dict(raw)
        f["index"] = i
        # What the spec SAID, read before any defaulting. Reading it afterwards is
        # how "hole declared add" and "boss declared cut" both slipped through once:
        # the default had already overwritten the contradiction being looked for.
        stated_mode = raw.get("mode")

        if op in _SOLID_OPS:
            if op in ("hole", "boss"):
                axis = f.setdefault("axis", "z")
                if axis not in AXES:
                    bad.append("%s: axis must be x, y or z, got %r" % (where, axis))
                    continue
                f["plane"] = _AXIS_PLANE[axis]
                at = f.get("at")
                if not isinstance(at, (list, tuple)) or len(at) != 2:
                    bad.append("%s: 'at' must be [u, v] in the plane perpendicular to "
                               "%s, got %r" % (where, axis, at))
                    continue
                try:
                    f["at_uv"] = _as_point(at, "%s.at" % where)
                except ValueError as exc:
                    bad.append(str(exc))
                    continue
                f["at_offset"] = 0.0
                f["dia"] = _positive(f.get("dia"), where, "dia", bad)
                if f["dia"] is None:
                    continue
                f["_segments"] = circle_outline(f["at_uv"][0], f["at_uv"][1], f["dia"])
                # A hole or a boss is a CYLINDER, and it is built as one. The
                # polygon above exists only so that the sampler and the boundary of
                # the bounding box have a uniform representation; the sampler uses
                # this disc instead, because a 48-gon would understate the area by
                # 0.29% - enough to bias the reference value, and more than enough
                # to make the built cylinder look wrong against it.
                f["_disc"] = (f["at_uv"][0], f["at_uv"][1], f["dia"] / 2.0)
            else:
                plane = f.setdefault("plane", "xy")
                if plane not in PLANES:
                    bad.append("%s: plane must be xy, xz or yz, got %r" % (where, plane))
                    continue
                f["plane"] = plane
                off = f.get("at", 0.0)
                if isinstance(off, bool) or not isinstance(off, (int, float)):
                    bad.append("%s: 'at' must be a number (the offset of the plane "
                               "along its normal), got %r" % (where, off))
                    continue
                f["at_offset"] = float(off)
                segs = _outline_segments(f, bad)
                if not segs:
                    continue
                f["_segments"] = segs

            f["mode"] = "add" if op == "boss" else f.setdefault("mode", "add")
            if f["mode"] not in ("add", "cut"):
                bad.append("%s: mode must be 'add' or 'cut', got %r"
                           % (where, f["mode"]))
                continue
            # A boss adds and a hole removes - that is what the words mean. The
            # recipe rewrites `mode` to match, but a spec that SAYS otherwise is
            # rejected rather than quietly overruled: someone who wrote "mode": "cut"
            # on a boss was thinking of something else, and silently building a boss
            # is how a drawing gets misread without anyone noticing.
            if op == "boss" and stated_mode == "cut":
                bad.append("%s: a boss ADDS material - \"mode\": \"cut\" contradicts "
                           "it; use \"op\": \"profile\" with \"mode\": \"cut\" to "
                           "remove that shape" % where)
                continue
            if op == "hole" and stated_mode == "add":
                bad.append("%s: a hole REMOVES material - \"mode\": \"add\" "
                           "contradicts it; use \"op\": \"boss\" to add that shape"
                           % where)
                continue
            f["mode"] = "cut" if op == "hole" else "add" if op == "boss" else stated_mode or "add"
            start = f.setdefault("start", 0.0)
            if isinstance(start, bool) or not isinstance(start, (int, float)):
                bad.append("%s: 'start' must be a number, got %r" % (where, start))
                continue
            f["start"] = float(start)
            if f.get("through"):
                if f["mode"] != "cut":
                    bad.append("%s: \"through\": true only makes sense for a cut - an "
                               "addition with no end would extend without limit; give "
                               "it a \"thickness\" (or \"height\")" % where)
                    continue
                f["thickness"] = None                 # resolved against the body
            else:
                t = f.get("thickness", f.get("height"))
                if t is None:
                    bad.append("%s: needs 'thickness' (or \"through\": true); a boss "
                               "may use 'height'" % where)
                    continue
                t = _positive(t, where, "thickness", bad)
                if t is None:
                    continue
                f["thickness"] = t
        else:                                         # blend / chamfer
            sel = f.get("edges")
            if not isinstance(sel, dict) or not sel:
                bad.append("%s: %s needs an 'edges' selector, e.g. {\"parallel_to\": "
                           "\"z\"} or {\"from_feature\": 0}" % (where, op))
                continue
            for key in sel:
                if key not in ("from_feature", "parallel_to", "mid_at"):
                    bad.append("%s: unknown selector key %r - use from_feature, "
                               "parallel_to or mid_at" % (where, key))
            if bad:
                continue
            if "parallel_to" in sel and sel["parallel_to"] not in AXES:
                bad.append("%s: selector parallel_to must be x, y or z" % where)
                continue
            if "from_feature" in sel:
                n = sel["from_feature"]
                if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < i:
                    bad.append("%s: from_feature must name an EARLIER feature "
                               "(0..%d), got %r" % (where, i - 1, n))
                    continue
                if features[n].get("op") in ("blend", "chamfer"):
                    bad.append("%s: from_feature %d is itself a %s - it creates no "
                               "edges to blend" % (where, n, features[n].get("op")))
                    continue
            if "mid_at" in sel:
                m = sel["mid_at"]
                if not isinstance(m, dict) or not m or any(k not in AXES for k in m):
                    bad.append("%s: mid_at must be a non-empty map of x/y/z to a "
                               "number, got %r" % (where, m))
                    continue
            name = "r" if op == "blend" else "c"
            size = _positive(f.get(name), where, name, bad)
            if size is None:
                continue
            f[name] = size
        out.append(f)
    return out


def validate_composed(params):
    """Human-readable problems with a composed spec. Empty list = buildable."""
    bad = []
    features = parse_features(params.get("features"), bad)
    if bad:
        return bad
    first = features[0]
    if first["op"] not in _SOLID_OPS:
        return ["the first feature must create material (profile, hole or boss) - a "
                "%s has nothing to work on yet" % first["op"]]
    if first["mode"] == "cut":
        return ["the first feature must CREATE material - a %s on its own removes "
                "material that does not exist yet" % first["op"]]
    if features[0].get("through"):
        return ["the first feature cannot be \"through\": true - it would extend "
                "forever with no material to bound it"]
    return []


def bounding_box(features, pad=None):
    """(min, max) corners covering every solid feature, plus working room."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    spans = []
    for f in features:
        if f["op"] not in _SOLID_OPS:
            continue
        ua, va, na = _PLANE_AXES[f["plane"]]
        start = f["start"]
        span = f["thickness"]
        if span is not None:
            spans.append(span)
        for s in f["_segments"]:
            for u, v in (_seg_start(s), _seg_end(s)):
                for axis, val in ((ua, u), (va, v)):
                    lo[AXES.index(axis)] = min(lo[AXES.index(axis)], val)
                    hi[AXES.index(axis)] = max(hi[AXES.index(axis)], val)
        if span is None:
            continue
        for nval in (f["at_offset"] + start, f["at_offset"] + start + span):
            lo[AXES.index(na)] = min(lo[AXES.index(na)], nval)
            hi[AXES.index(na)] = max(hi[AXES.index(na)], nval)
    biggest = max(spans) if spans else 1.0
    # room for the outline's own extent along the normal axis and for "through" cuts
    room = (pad or 0.0) + biggest + 1.0
    # the normal axis of a planar profile may have no extent yet: give it the room
    for i in range(3):
        if lo[i] == float("inf"):
            lo[i], hi[i] = 0.0, 0.0
    return (tuple(v - room for v in lo), tuple(v + room for v in hi))


def solid_models(features):
    """The add/cut operations as prisms the sampler can test, spans resolved."""
    models = []
    for f in features:
        if f["op"] not in _SOLID_OPS:
            continue
        start, thickness = f["start"], f["thickness"]
        if thickness is None:                    # "through": overshoot generously
            start, thickness = -1.0e4, 2.0e4
        models.append({
            "index": f["index"],
            "op": f["op"],
            "mode": f["mode"],
            # a circle is tested as a disc (exact area); anything else is the outline
            # with its arcs tessellated at 1 degree, which is 10x below the sampling
            # error and never feeds the kernel
            "disc": f.get("_disc"),
            "poly": None if f.get("_disc") else _discount_arcs(f["_segments"], step_deg=1.0),
            "u": _PLANE_AXES[f["plane"]][0],
            "v": _PLANE_AXES[f["plane"]][1],
            "n": _PLANE_AXES[f["plane"]][2],
            "at": f["at_offset"],
            "lo": start,
            "hi": start + thickness,
        })
    return models


def _in_polygon(px, py, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > py) != (y1 > py):
            if px < x0 + (py - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


def sample_volume(features, bbox, samples=400000, seed=20260926):
    """Monte-Carlo volume of the feature list over `bbox`, deterministic in `seed`.

    Sequential booleans: a point is solid if the LAST operation whose prism covers
    it adds material, and void if the last one cuts. Blends and chamfers are not
    modelled, so the value runs slightly high on a part that has them - the caller
    states a tolerance rather than implying an exact check.
    """
    (x0, y0, z0), (x1, y1, z1) = bbox
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    if dx <= 0 or dy <= 0 or dz <= 0:
        raise RecipeError("degenerate bounding box for sampling")

    models = solid_models(features)
    if not models:
        return 0.0
    rng = random.Random(seed)
    hits = 0
    for _ in range(samples):
        pt = {"x": x0 + rng.random() * dx,
              "y": y0 + rng.random() * dy,
              "z": z0 + rng.random() * dz}
        solid = False
        for m in models:
            t = pt[m["n"]] - m["at"]
            if t < m["lo"] or t > m["hi"]:
                continue
            if m["disc"] is not None:
                cx, cy, r = m["disc"]
                if math.hypot(pt[m["u"]] - cx, pt[m["v"]] - cy) > r:
                    continue
            elif not _in_polygon(pt[m["u"]], pt[m["v"]], m["poly"]):
                continue
            solid = (m["mode"] == "add")
        if solid:
            hits += 1
    return dx * dy * dz * (hits / float(samples))


def composed_metrics(params):
    vol, _span = _sampled(params)
    # None: no honest analytic face count for an arbitrary feature list
    return vol, None


_SAMPLE_CACHE = {}


def _sampled(params):
    """(volume, bounding-box volume) for a feature list, sampled ONCE per distinct input.

    The build asks for this twice - once through composed_metrics for the numeric
    check, once through composed_report for the log line - and 400k samples is not
    free. Caching also guarantees the two answers are the same number rather than
    two draws that differ in the third digit and make the log look inconsistent.
    """
    key = json.dumps(params, sort_keys=True, default=str)
    if key not in _SAMPLE_CACHE:
        bad = []
        features = parse_features(params.get("features"), bad)
        if bad:
            raise RecipeError("cannot measure this part: %s" % "; ".join(bad))
        bbox = bounding_box(features)
        span = 1.0
        for i in range(3):
            span *= (bbox[1][i] - bbox[0][i])
        _SAMPLE_CACHE[key] = (sample_volume(features, bbox, SAMPLES), span)
    return _SAMPLE_CACHE[key]


def composed_report(params):
    """volume, its standard error and the sample count - for the run log.

    Reported rather than hidden: it is the difference between "verified against a
    formula" and "verified against a sample", and the user is entitled to see which
    one they got.
    """
    vol, span = _sampled(params)
    p = (vol / span) if span > 0 else 0.0
    sigma = span * math.sqrt(max(p * (1.0 - p), 1e-12) / SAMPLES)
    return {"volume": vol, "sigma": sigma, "samples": SAMPLES,
            "relative_sigma": (sigma / vol) if vol > 0 else 0.0}


def composed_cylindrical_faces(params):
    """Not derivable for an arbitrary feature list - reported, never asserted."""
    return None


# -----------------------------------------------------------------------------
# the recipe is registered from here, not from nx_recipes
#
# nx_recipes imports this module (for this line) and this module imports nx_recipes
# (for the outline helpers). That cycle is safe in BOTH orders only while neither
# module reads a name from the other at import time beyond what is defined above
# the import statement - so the register call must stay HERE, at the bottom, after
# every name it passes has been defined. Putting it at the bottom of nx_recipes
# instead reads COMPOSED off a half-built module when this file is imported first.
# -----------------------------------------------------------------------------
nx_recipes.register(COMPOSED,
                    ("features",),
                    validate_composed,
                    composed_metrics,
                    composed_cylindrical_faces,
                    aliases=("compose",),
                    tolerance=SAMPLING_TOLERANCE)
