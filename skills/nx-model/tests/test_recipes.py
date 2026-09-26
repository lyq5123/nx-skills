# =============================================================================
#  Unit tests for the part recipes and the registry.
#
#  Needs NO NX and no NX runtime: nx_common and nx_recipes are stdlib-only and
#  importable by plain Python. This is where the validation rules and the
#  analytic volume formulas get checked quickly, without paying for a journal
#  run (~30 s each).
#
#      python nx-model/tests/test_recipes.py
#      python nx-model/tests/run_tests.py T8
# =============================================================================
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
SPECS = os.path.join(HERE, "specs")

sys.path.insert(0, SCRIPTS)
import nx_common as nxc
import nx_recipes as nxr

# Analytic reference values, taken from the geometry and cross-checked against
# what NX measures. They are NOT copied from whatever the code currently
# returns - that circularity is exactly what these tests defend against.
DEFAULT_PARAMS = dict(nxc.DEFAULT_PLATE["params"])


def spec_from_fixture(fixture, **overrides):
    with open(os.path.join(SPECS, fixture), "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    spec["params"].update(overrides)
    return spec


class RegistryTests(unittest.TestCase):
    def test_mounting_plate_is_registered(self):
        self.assertIn("mounting_plate", nxr.known_parts())
        self.assertTrue(nxr.has_recipe("mounting_plate"))
        self.assertFalse(nxr.has_recipe("no_such_part"))

    def test_recipe_exposes_its_parameters(self):
        self.assertEqual(nxr.param_keys("mounting_plate"), nxc.PARAM_KEYS)

    def test_missing_part_defaults_to_the_plate(self):
        self.assertEqual(nxc.part_type_of({}), "mounting_plate")
        self.assertEqual(nxc.part_type_of({"part": "mounting_plate"}), "mounting_plate")


class MetricTests(unittest.TestCase):
    def test_default_plate_volume_and_faces(self):
        vol, faces = nxc.part_metrics({"params": dict(DEFAULT_PARAMS)})
        self.assertAlmostEqual(vol, 87562.93877, places=3)
        self.assertEqual(faces, 11)

    def test_default_plate_with_r8_fillet(self):
        spec = {"params": dict(DEFAULT_PARAMS, fillet_r=8.0)}
        vol, faces = nxc.part_metrics(spec)
        self.assertAlmostEqual(vol, 87013.558, places=3)
        self.assertEqual(faces, 15)

    def test_plate_ok_matches_independently_computed_values(self):
        spec = spec_from_fixture("plate_ok.json")
        vol, faces = nxc.part_metrics(spec)
        self.assertAlmostEqual(vol, 221207.47023063523, places=3)
        self.assertEqual(faces, 15)

    def test_volume_is_linear_in_thickness(self):
        thin = {"params": dict(DEFAULT_PARAMS, plate_t=5.0)}
        thick = {"params": dict(DEFAULT_PARAMS, plate_t=10.0)}
        lv, _ = nxc.part_metrics(thin)
        hv, _ = nxc.part_metrics(thick)

        # cross-section computed here from scratch, so a wrong constant in the
        # recipe cannot quietly agree with itself
        p = DEFAULT_PARAMS
        area = (p["plate_w"] * p["plate_h"]
                - 4 * math.pi * (p["hole_d"] / 2.0) ** 2
                - math.pi * (p["bore_d"] / 2.0) ** 2)
        self.assertAlmostEqual(hv, area * 10.0, places=3)
        self.assertAlmostEqual(lv, area * 5.0, places=3)

    def test_cylindrical_face_counts(self):
        self.assertEqual(nxc.cylindrical_faces({"params": dict(DEFAULT_PARAMS)}), 5)
        self.assertEqual(
            nxc.cylindrical_faces({"params": dict(DEFAULT_PARAMS, fillet_r=8.0)}), 9)
        self.assertEqual(nxc.cylindrical_faces(spec_from_fixture("plate_ok.json")), 9)
        self.assertEqual(
            nxc.cylindrical_faces(
                {"params": dict(DEFAULT_PARAMS, hole_d=0.0, bore_d=0.0)}), 0)


class ValidationTests(unittest.TestCase):
    def test_valid_specs_pass(self):
        for params in (DEFAULT_PARAMS,
                       dict(DEFAULT_PARAMS, fillet_r=3.0),
                       # R8 on the default plate is legal, and this entry is the
                       # regression guard for a rule that once refused it - see
                       # test_fillet_that_only_looks_colliding_is_accepted
                       dict(DEFAULT_PARAMS, fillet_r=8.0),
                       spec_from_fixture("plate_ok.json")["params"]):
            self.assertEqual(nxc.validate_part({"params": params}), [],
                             "unexpectedly rejected: %r" % (params,))

    def test_fillet_that_only_looks_colliding_is_accepted(self):
        """The fillet ARC spans 90 degrees facing the corner; a circle-vs-circle
        distance test ignores that and rejects legal parts.

        R8 fillet with holes inset 12: the two CIRCLES do overlap
        (|8-3.3| <= 5.657 <= 8+3.3), but the arc is 12.649 away from the hole
        centre while the hole radius is only 3.3. NX builds it and the analytic
        volume matches the measurement to 0.0000, so it must be accepted.
        """
        params = dict(DEFAULT_PARAMS, fillet_r=8.0)
        self.assertEqual(nxc.validate_part({"params": params}), [],
                         "a legal fillet/hole combination was rejected again")
        # and the value that combination produces is the documented one
        vol, faces = nxc.part_metrics({"params": params})
        self.assertAlmostEqual(vol, 87013.558, places=3)
        self.assertEqual(faces, 15)

    def test_fillet_that_really_collides_is_rejected(self):
        """A hole close enough to the corner does reach the fillet region."""
        params = dict(DEFAULT_PARAMS, hole_inset=6.0, hole_d=9.0, fillet_r=14.0)
        problems = nxc.validate_part({"params": params})
        self.assertTrue(any("collides with the hole" in p for p in problems),
                        "a genuinely colliding fillet was accepted: %r" % (problems,))

    def test_every_bad_fixture_is_rejected(self):
        for fixture in sorted(os.listdir(SPECS)):
            if not fixture.startswith("bad_"):
                continue
            with open(os.path.join(SPECS, fixture), "r", encoding="utf-8") as fh:
                spec = json.load(fh)
            problems = nxc.validate_part(spec)
            self.assertTrue(problems, "%s was accepted" % fixture)
            for line in problems:
                self.assertIsInstance(line, str)
                self.assertTrue(line.strip())

    def test_zero_features_are_legal(self):
        problems = nxc.validate_part(
            {"params": dict(DEFAULT_PARAMS, hole_d=0.0, bore_d=0.0, fillet_r=0.0)})
        self.assertEqual(problems, [])

    def test_missing_parameters_are_named(self):
        problems = nxc.validate_part({"params": {"plate_w": 120.0}})
        joined = " | ".join(problems)
        for key in ("plate_h", "plate_t", "hole_d", "bore_d"):
            self.assertIn(key, joined)

    def test_non_numeric_parameter_is_rejected(self):
        problems = nxc.validate_part({"params": dict(DEFAULT_PARAMS, plate_w="wide")})
        self.assertTrue(any("must be a number" in p for p in problems))


class BadSpecShapeTests(unittest.TestCase):
    """Spec-level problems must come back as words, never as a traceback."""

    def test_unknown_part_type(self):
        problems = nxc.validate_part({"part": "widget", "params": dict(DEFAULT_PARAMS)})
        self.assertEqual(len(problems), 1)
        self.assertIn("unknown part type", problems[0])
        self.assertIn("mounting_plate", problems[0])

    def test_params_wrong_type(self):
        problems = nxc.validate_part({"params": [1, 2, 3]})
        self.assertEqual(len(problems), 1)
        self.assertIn("must be an object", problems[0])

    def test_params_missing_entirely(self):
        problems = nxc.validate_part({})
        self.assertTrue(any("missing parameter" in p for p in problems))


class BackwardCompatibilityTests(unittest.TestCase):
    """The old plate-specific names must keep behaving identically."""

    def test_aliases_agree_with_the_recipe(self):
        params = spec_from_fixture("plate_ok.json")["params"]
        spec = {"params": params}
        self.assertEqual(nxc.plate_metrics(params), nxc.part_metrics(spec))
        self.assertEqual(nxc.validate_plate(params), nxc.validate_part(spec))

    def test_alias_names_still_importable(self):
        import nx_common
        self.assertTrue(callable(nx_common.validate_plate))
        self.assertTrue(callable(nx_common.plate_metrics))


class FlangeRecipeTests(unittest.TestCase):
    """OD160 / ID60 / t20 / BCD120 / 6x D14 / C2 - measured on NX as
    325108.763 mm^3, 12 faces, 8 cylindrical faces."""

    FLANGE = dict(od=160.0, id=60.0, thk=20.0, bcd=120.0, n_bolts=6,
                  bolt_d=14.0, chamfer=2.0)

    def test_metrics_match_the_measured_part(self):
        spec = {"part": "circular_flange", "params": self.FLANGE}
        vol, faces = nxc.part_metrics(spec)
        self.assertAlmostEqual(vol, 325108.763, places=3)
        self.assertEqual(faces, 12)
        self.assertEqual(nxc.cylindrical_faces(spec), 8)

    def test_fixture_matches_independently_computed_values(self):
        spec = spec_from_fixture("flange_ok.json")
        vol, faces = nxc.part_metrics(spec)
        #  pi*100^2*25 - pi*40^2*25 - 8*pi*6^2*25 - 2*pi*3^2*(100 - 1)
        self.assertAlmostEqual(vol, 631516.672039, places=3)
        self.assertEqual(faces, 14)
        self.assertEqual(nxc.cylindrical_faces(spec), 10)

    def test_valid_flange_passes(self):
        self.assertEqual(nxc.validate_part({"part": "circular_flange",
                                            "params": self.FLANGE}), [])

    def test_flange_conflicts_are_rejected(self):
        cases = [
            (dict(self.FLANGE, bcd=180.0), "outer edge"),
            (dict(self.FLANGE, chamfer=12.0), "too deep"),
            (dict(self.FLANGE, id=90.0), "no wall"),
            (dict(self.FLANGE, n_bolts=12, bolt_d=35.0), "merge"),
        ]
        for params, needle in cases:
            problems = nxc.validate_part({"part": "circular_flange", "params": params})
            self.assertTrue(any(needle in p for p in problems),
                            "%s not caught: %r" % (needle, problems))

    def test_alias_resolves(self):
        self.assertTrue(nxr.has_recipe("flange"))
        self.assertEqual(nxc.part_type_of({"part": "flange"}), "circular_flange")


class BracketRecipeTests(unittest.TestCase):
    """80/12/10/60 wide 40 with two D6 holes - measured on NX as
    55338.053 mm^3, 10 faces, 2 cylindrical faces."""

    BRACKET = dict(base_l=80.0, base_t=12.0, wall_t=10.0, total_h=60.0,
                   width=40.0, hole_d=6.0, hole_inset_x=20.0)

    def test_metrics_match_the_measured_part(self):
        spec = {"part": "l_bracket", "params": self.BRACKET}
        vol, faces = nxc.part_metrics(spec)
        self.assertAlmostEqual(vol, 55338.053, places=3)
        self.assertEqual(faces, 10)
        self.assertEqual(nxc.cylindrical_faces(spec), 2)

    def test_fixture_matches_independently_computed_values(self):
        spec = spec_from_fixture("bracket_ok.json")
        vol, faces = nxc.part_metrics(spec)
        #  (120*15 + 12*(90-15))*50 - 2*pi*4.5^2*50
        self.assertAlmostEqual(vol, 128638.274876, places=3)
        self.assertEqual(faces, 10)

    def test_valid_bracket_passes(self):
        self.assertEqual(nxc.validate_part({"part": "l_bracket",
                                            "params": self.BRACKET}), [])

    def test_bracket_conflicts_are_rejected(self):
        cases = [
            (dict(self.BRACKET, hole_inset_x=78.0), "wall"),
            (dict(self.BRACKET, hole_d=20.0), "break through"),
            (dict(self.BRACKET, base_t=70.0), "no vertical leg"),
        ]
        for params, needle in cases:
            problems = nxc.validate_part({"part": "l_bracket", "params": params})
            self.assertTrue(any(needle in p for p in problems),
                            "%s not caught: %r" % (needle, problems))

    def test_zero_holes_is_legal(self):
        params = dict(self.BRACKET, hole_d=0.0)
        self.assertEqual(nxc.validate_part({"part": "l_bracket", "params": params}), [])
        spec = {"part": "l_bracket", "params": params}
        self.assertEqual(nxc.cylindrical_faces(spec), 0)
        self.assertEqual(nxc.part_metrics(spec)[1], 8)     # 6 sides + 2 ends


class ProfileRecipeTests(unittest.TestCase):
    """The generic extruded-profile recipe: any straight-sided part.

    Its strongest test is the cross-check below - the named recipes must reproduce
    exactly when their outline is written as a polygon, or one of the two paths is
    wrong.
    """

    BRACKET_AS_PROFILE = dict(
        points=[[0, 0], [80, 0], [80, 12], [10, 12], [10, 60], [0, 60]],
        thickness=40.0,
        holes=[[20, 6, 6.0], [60, 6, 6.0]],
    )
    PLATE_AS_PROFILE = dict(
        points=[[0, 0], [120, 0], [120, 80], [0, 80]],
        thickness=10.0,
        holes=[[12, 12, 6.6], [108, 12, 6.6], [108, 68, 6.6], [12, 68, 6.6],
               [60, 40, 30.0]],
    )

    def test_generic_matches_the_named_bracket_recipe(self):
        gv, gf = nxc.part_metrics({"part": "extruded_profile",
                                  "params": self.BRACKET_AS_PROFILE})
        nv, nf = nxc.part_metrics({"part": "l_bracket", "params": {
            "base_l": 80.0, "base_t": 12.0, "wall_t": 10.0, "total_h": 60.0,
            "width": 40.0, "hole_d": 6.0, "hole_inset_x": 20.0}})
        self.assertAlmostEqual(gv, nv, places=6)
        self.assertEqual(gf, nf)
        self.assertAlmostEqual(gv, 55338.053, places=3)      # the NX measurement

    def test_generic_matches_the_named_plate_recipe(self):
        gv, gf = nxc.part_metrics({"part": "extruded_profile",
                                  "params": self.PLATE_AS_PROFILE})
        nv, nf = nxc.part_metrics({"part": "mounting_plate", "params": self.DEFAULT_PLATE})
        self.assertAlmostEqual(gv, nv, places=6)
        self.assertEqual(gf, nf)
        self.assertAlmostEqual(gv, 87562.93877, places=3)    # the NX measurement

    DEFAULT_PLATE = dict(nxc.DEFAULT_PLATE["params"])

    def test_fixture_matches_an_independent_shoelace(self):
        spec = spec_from_fixture("profile_ok.json")
        vol, faces = nxc.part_metrics(spec)
        # the outline's shoelace area is 11200 mm^2
        area = 11200.0
        self.assertAlmostEqual(vol, area * 6.0 - 2 * math.pi * 6.0 ** 2 * 6.0, places=6)
        self.assertEqual(faces, 10)
        self.assertEqual(nxc.cylindrical_faces(spec), 2)

    def test_concave_outline_is_accepted(self):
        # the default L outline is concave; its centroid-based seed must still work
        self.assertEqual(nxc.validate_part({"part": "extruded_profile",
                                            "params": self.BRACKET_AS_PROFILE}), [])

    def test_no_holes_is_legal(self):
        params = dict(self.BRACKET_AS_PROFILE, holes=[])
        self.assertEqual(nxc.validate_part({"part": "extruded_profile",
                                            "params": params}), [])
        vol, faces = nxc.part_metrics({"part": "extruded_profile", "params": params})
        self.assertEqual(faces, 8)                            # 6 sides + 2 ends
        self.assertAlmostEqual(vol, 1440.0 * 40.0, places=6)

    def test_bad_outlines_and_holes_are_rejected(self):
        base = dict(self.BRACKET_AS_PROFILE)
        cases = [
            (dict(base, points=[[0, 0], [10, 0], [20, 0]]), "no area"),
            (dict(base, points=[[0, 0], [10, 10]]), "at least 3"),
            (dict(base, points=[[0, 0], [0, 0], [10, 0], [10, 10]]), "zero-length"),
            (dict(base, thickness=0.0), "must be > 0"),
            (dict(base, points="circle"), "must be a list"),
            (dict(base, holes=[[500, 500, 10.0]]), "outside the outline"),
            (dict(base, holes=[[5, 5, 20.0]]), "crosses the outline"),
            (dict(base, holes=[[20, 6, 6.0], [22, 6, 6.0]]), "overlap"),
            (dict(base, holes=[["20", 6, 6.0]]), "must be numbers"),
        ]
        for params, needle in cases:
            problems = nxc.validate_part({"part": "extruded_profile", "params": params})
            self.assertTrue(any(needle in p for p in problems),
                            "%s not caught: %r" % (needle, problems))

    def test_alias_resolves(self):
        self.assertEqual(nxc.part_type_of({"part": "profile"}), "extruded_profile")


class RegistryCoverageTests(unittest.TestCase):
    def test_all_shapes_are_registered(self):
        self.assertEqual(nxr.known_parts(),
                         ["circular_flange", "extruded_profile", "l_bracket",
                          "mounting_plate"])

    def test_every_recipe_exposes_params_and_rules(self):
        for name in nxr.known_parts():
            self.assertTrue(nxr.param_keys(name), "%s has no param_keys" % name)
            # a recipe with no validation would accept anything
            problems = nxr.validate(name, {})
            self.assertTrue(problems, "%s accepted an empty parameter set" % name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
