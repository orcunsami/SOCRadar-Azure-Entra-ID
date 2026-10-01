"""Repo hygiene guard: tracked files must stay anonymous and English.

Three leak classes get past a secret scan and a language scan alike:
internal identifiers, captured credential values and non-English prose.
Each got into this repository once; this test is what keeps them out.

Forbidden literals are written in split form so this file never matches
itself.
"""
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Internal numeric identifiers (digit/alnum-bounded so 1440, GUID hex runs
# and version strings stay legal). These are real platform company ids.
_INTERNAL_IDS = re.compile(
    r"(?<![0-9a-zA-Z])(3" "30|1" "32)(?![0-9a-zA-Z])"
)

# Strings that identify us, a person, or a captured feed record.
_FORBIDDEN = [
    "green" "animals" "bank",          # domain from a captured feed sample
    "Emma " "Taylor",                  # display name from a captured record
    "SOCRadarCyber" "IntelligenceIn",  # our own tenant name
    "test" "radar",                    # our test account naming
    "b0afca" "82",                     # our test App Registration id (prefix)
    "01a149" "09",                     # our tenant id (prefix)
    # Credential values that once sat in captured responses here. A schema
    # kept one alive as an "example" after the captures were scrubbed, which
    # the password-field rule cannot see -- so the values themselves are
    # banned, wherever they appear.
    "Vusu" "326486",
    "Juhasz" "csalad",
    "marmtra" "766",
    "Martrta" "3.",
    "Wagu" "246469",
    "Hucu" "975301",
    "Lq!Xgsff" "3424Z",
    "k9Q!" "b3X",
    "G7eLx@#" "4iY6B",
]

# Turkish diacritics: tracked content must be English.
_NON_ENGLISH = re.compile("[çğıöşü"
                          "ÇĞİÖŞÜ]")

# A password field in a tracked JSON capture must hold a placeholder, a
# masked value or an ARM expression -- never a real-looking credential.
_JSON_PASSWORD = re.compile(r'"password"\s*:\s*"(?!Example-Pass)'
                            r'(?![^"]*\*)(?!\[)[^"]+"')

# A password assigned a quoted literal (shell/python), or given as the default of an
# environment lookup. Test credentials come from the environment, never the repo.
_LITERAL_PASSWORD = re.compile(
    r"""^\s*[A-Z_]*(PASSWORD|PASSWD|_PW)\s*=\s*['"][^'"$]+['"]"""
    r"""|(PASSWORD|_PW)['"]?\s*,\s*['"][^'"]+['"]\s*\)""", re.I)

_SELF = Path(__file__).name

_TEXT_SUFFIXES = (".py", ".md", ".json", ".sh", ".yml", ".yaml",
                  ".config", ".example", ".txt", ".bicep")


def _tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True)
    for rel in out.stdout.splitlines():
        p = REPO_ROOT / rel
        if p.name == _SELF or not p.is_file():
            continue
        if p.suffix in _TEXT_SUFFIXES or p.name.endswith(".example"):
            yield rel, p


class RepoIsAnonymous(unittest.TestCase):

    def _sweep(self, check):
        hits = []
        for rel, p in _tracked_files():
            text = p.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                found = check(line)
                if found:
                    hits.append(f"{rel}:{i}: {found}")
        return hits

    def test_no_internal_company_ids(self):
        hits = self._sweep(
            lambda ln: _INTERNAL_IDS.search(ln) and _INTERNAL_IDS.search(ln).group(0))
        self.assertEqual(hits, [], "internal company id in tracked file")

    def test_no_identifying_strings(self):
        def check(line):
            low = line.lower()
            for lit in _FORBIDDEN:
                if lit.lower() in low:
                    return lit
            return None
        self.assertEqual(self._sweep(check), [],
                         "identifying string in tracked file")

    def test_tracked_files_are_english(self):
        hits = self._sweep(
            lambda ln: _NON_ENGLISH.search(ln) and _NON_ENGLISH.search(ln).group(0))
        self.assertEqual(hits, [], "non-English text in tracked file")

    def test_no_literal_passwords_in_scripts(self):
        hits = self._sweep(
            lambda ln: _LITERAL_PASSWORD.search(ln) and "literal password")
        self.assertEqual(hits, [], "password literal in a tracked file")

    def test_no_credential_values_in_json_captures(self):
        hits = []
        for rel, p in _tracked_files():
            if p.suffix != ".json":
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                m = _JSON_PASSWORD.search(line)
                if m:
                    hits.append(f"{rel}:{i}")
        self.assertEqual(hits, [], "real-looking password value in a tracked JSON")

    def test_ordinary_numbers_stay_legal(self):
        # The id pattern must not fire on innocent numbers or hex runs.
        for ok in ("1440 minutes", "port 8330", "13200 records",
                   "a1330f", "v1.3.30", "2026-01-32"):
            self.assertIsNone(_INTERNAL_IDS.search(ok), ok)
        self.assertIsNotNone(_INTERNAL_IDS.search('"company_id": "3' '30"'))

    def test_guard_reads_the_repository_it_protects(self):
        # Couples the guard to the tree: if ls-files breaks or the layout
        # moves, this fails loudly instead of sweeping nothing.
        files = list(_tracked_files())
        self.assertGreater(len(files), 40)
        self.assertTrue(any(rel.endswith("azuredeploy.json") for rel, _ in files))


if __name__ == "__main__":
    unittest.main()
