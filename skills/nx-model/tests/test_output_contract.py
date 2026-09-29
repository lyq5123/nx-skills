# =============================================================================
#  Unit tests for the OUTPUT CONTRACT: what a run leaves on disk, and what it
#  exits with. No NX needed - nx_common is stdlib-only and importable.
#
#      python nx-model/tests/test_output_contract.py
#
#  Why this file exists separately from test_recipes.py: those tests are about
#  geometry, these are about the one thing the caller can actually read. A journal
#  run's exit code carries no detail (run_journal.exe turns any sys.exit(n) into 1),
#  so `result.json` IS the verdict. A run that leaves the PREVIOUS run's
#  result.json in place while the geometry quietly failed is the exact failure this
#  skill is built to prevent - so it gets its own tests.
# =============================================================================
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import nx_common as nxc


class _Boom(object):
    """Stand-in for an os call that the OS refuses.

    Used to simulate the conditions that actually happen: the file is held open by
    the user's NX session, the directory is read-only, or a fail-closed sandbox
    refuses the operation.
    """

    def __init__(self, exc):
        self.exc = exc

    def __call__(self, *a, **kw):
        raise self.exc


class ResultFileContractTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nxcontract_")
        self.path = os.path.join(self.dir, "part.result.json")

    def _stale(self):
        """A previous run's file, claiming success - the thing that must not win."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"status": "ok", "STALE": True, "volume": 111111.0}, fh)
        return self.path

    def test_a_successful_write_replaces_the_previous_file(self):
        self._stale()
        self.assertTrue(nxc.write_result(self.path, {"status": "ok", "volume": 222222.0}))
        with open(self.path, "r", encoding="utf-8") as fh:
            got = json.load(fh)
        self.assertNotIn("STALE", got)
        self.assertEqual(got["volume"], 222222.0)
        self.assertTrue(got.get("finished_at"))
        # no half-written temp left lying around
        self.assertEqual([f for f in os.listdir(self.dir) if f.endswith(".tmp")], [])

    def test_a_write_that_cannot_land_must_not_exit_zero(self):
        """The P0: an unwritable result file used to pass as a good run.

        Nothing here names the os call that fails. The destination is made a
        DIRECTORY, so every way of putting a file there fails - open, remove,
        rename or replace - whatever the implementation happens to use. What is
        asserted is the contract: if the result does not land, the process must not
        exit 0, because result.json is the caller's only verdict.
        """
        target = os.path.join(self.dir, "unwritable.result.json")
        os.mkdir(target)                      # any attempt to write *that path* fails

        with redirect_stdout(io.StringIO()) as buf:
            with self.assertRaises(SystemExit) as caught:
                nxc.finish(nxc.Log(None), target, {"part": "x"}, time.time())

        self.assertNotEqual(caught.exception.code, 0,
                            "a result file that could not be written exited 0 - the "
                            "caller is left reading an older file and calling it green")
        self.assertIn("result file", buf.getvalue())

    def test_a_failed_write_does_not_leave_the_old_payload_looking_current(self):
        """The other half of the P0: which payload is on disk afterwards.

        This one does name os.remove/os.replace, and deliberately: the claim is
        "whichever call you use to dispose of the old file, if it is refused the
        old payload must not survive as if it were this run's". A reimplementation
        that writes through some third path would need this test updated - which is
        a fair thing to notice in review, and better than having no test at all.
        """
        self._stale()
        before = os.path.getmtime(self.path)

        saved = (os.remove, os.replace)
        os.remove = _Boom(PermissionError(13, "Access is denied", self.path))
        os.replace = _Boom(PermissionError(13, "Access is denied", self.path))
        try:
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    nxc.finish(nxc.Log(None), self.path, {"part": "x"}, time.time())
        finally:
            os.remove, os.replace = saved

        self.assertNotEqual(caught.exception.code, 0)
        with open(self.path, "r", encoding="utf-8") as fh:
            stale = json.load(fh)
        self.assertTrue(stale.get("STALE"),
                        "the previous payload was replaced even though the write failed?")
        self.assertEqual(os.path.getmtime(self.path), before)

    def test_a_write_that_cannot_land_reports_where_the_payload_went(self):
        """Losing the payload silently is almost as bad as losing the verdict."""
        self._stale()
        saved = os.replace
        os.replace = _Boom(OSError(28, "No space left on device"))
        try:
            with redirect_stdout(io.StringIO()) as buf:
                ok = nxc.write_result(self.path, {"part": "x"})
        finally:
            os.replace = saved
        self.assertFalse(ok)
        text = buf.getvalue()
        self.assertIn(".tmp", text,
                      "the warning does not say where the new payload was left: %r" % text)

    def test_finish_exits_nonzero_when_the_geometry_logged_an_error(self):
        """The behaviour that already worked - keep it from regressing."""
        log = nxc.Log(None)
        log.err("volume does not match")
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                nxc.finish(log, self.path, {"part": "x"}, time.time())
        self.assertNotEqual(caught.exception.code, 0)
        with open(self.path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(len(payload["errors"]), 1)

    def test_finish_records_a_clean_run_as_ok(self):
        log = nxc.Log(None)
        with redirect_stdout(io.StringIO()):
            payload = nxc.finish(log, self.path, {"part": "x"}, time.time())
        self.assertEqual(payload["status"], "ok")
        with open(self.path, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["status"], "ok")

    def tearDown(self):
        for f in os.listdir(self.dir):
            p = os.path.join(self.dir, f)
            try:
                if os.path.isdir(p):
                    os.rmdir(p)
                else:
                    os.remove(p)
            except OSError:
                pass
        os.rmdir(self.dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
