"""The package cannot arrive through a redirecting URL any more.

Azure rejects the CREATE of a Linux consumption Function App whose
WEBSITE_RUN_FROM_PACKAGE points at a URL that redirects. A GitHub release
download URL always redirects (302 to objects.githubusercontent.com), so the
one-click deploy failed at the Function App with BadRequest 51024 and left the
storage account, the identity and the App Service Plan behind.

Measured 7 Sep 2026 on an isolated rig: the same release URL was accepted at
15:01 and rejected at 15:10, same subscription, same region. Nothing in this
repository changed in between, so a green deployment from the day before proved
nothing about the day after.

The app is now created with WEBSITE_RUN_FROM_PACKAGE='1' and the zip is pushed
by the triggerFirstRun deploymentScript, which is the shape the platform's own
error message suggests.

The check that is easiest to lose is forceUpdateTag: without it a redeploy PUTs
the site with the full appSettings list, resetting the setting from the blob URL
config-zip wrote back to '1', while the script -- unchanged -- does not re-run.
The deployment reports Succeeded and the app has no code.

Reads files only: no app import, no Azure stub, no network.
"""

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "production" / "azuredeploy.json"
BICEP = REPO / "production" / "azuredeploy.bicep"


def _resources(doc):
    """languageVersion 2.0 keys resources by symbolic name rather than listing them."""
    res = doc.get("resources")
    return list(res.values()) if isinstance(res, dict) else list(res or [])


class PackagePush(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(TEMPLATE.read_text())
        self.resources = _resources(self.doc)
        self.params = self.doc.get("parameters", {})
        # Calibration: every assertion below reads as a pass if the shape is not
        # what this test assumes, and an empty search looks exactly like success.
        self.assertTrue(
            any(r.get("type") == "Microsoft.Web/sites" for r in self.resources),
            "no Microsoft.Web/sites in azuredeploy.json - these checks would all pass "
            "without testing anything",
        )
        self.scripts = [
            r for r in self.resources
            if r.get("type") == "Microsoft.Resources/deploymentScripts"
            and "PACKAGE_URL" in json.dumps(r.get("properties", {}))
        ]

    def test_every_deployment_script_keeps_its_failed_log_for_a_day(self):
        """Two settings, one promise. `cleanupPreference` says WHEN the container
        and its log are deleted, `retentionInterval` says HOW LONG AFTER. With
        OnSuccess alone and PT1H a failed customer deployment loses its evidence
        in an hour -- measured on run 3c6f: endTime 18:42:05, expirationTime
        19:42:05. The ceiling is documented as 26 hours, and Azure normalises
        PT26H to P1DT2H (measured live 7 Sep on rg-feeds-paths-b17d).

        This covers EVERY deploymentScript, not just the package push: the FIC
        script had no cleanupPreference at all, so its log was deleted the moment
        it failed -- and that is the step a customer without App Registration
        rights hits first.
        """
        all_scripts = [r for r in self.resources
                       if r.get("type") == "Microsoft.Resources/deploymentScripts"]
        self.assertTrue(all_scripts, "no deploymentScript in the template")
        for r in all_scripts:
            props = r.get("properties", {})
            name = r.get("name", "?")
            self.assertEqual(
                props.get("cleanupPreference"), "OnSuccess",
                "%s: cleanupPreference is %r - the default deletes the container and its "
                "log the moment a customer's deployment fails"
                % (name, props.get("cleanupPreference")),
            )
            ri = str(props.get("retentionInterval") or "")
            m = re.match(r"^P(?:(\d+)D)?(?:T(\d+)H)?$", ri)
            hours = (int(m.group(1) or 0) * 24 + int(m.group(2) or 0)) if m else 0
            self.assertGreaterEqual(
                hours, 26,
                "%s: retentionInterval is %r - the failed run's container, storage and "
                "script resource are deleted together when it expires" % (name, ri),
            )

    def test_run_from_package_is_one_not_a_url(self):
        for site in [r for r in self.resources if r.get("type") == "Microsoft.Web/sites"]:
            settings = {a.get("name"): a.get("value") for a in
                        ((site.get("properties") or {}).get("siteConfig") or {})
                        .get("appSettings", [])}
            value = settings.get("WEBSITE_RUN_FROM_PACKAGE")
            self.assertEqual(
                value, "1",
                "WEBSITE_RUN_FROM_PACKAGE is %r. A URL that redirects is rejected at "
                "create with BadRequest 51024, and the release URL always redirects."
                % (value,),
            )

    def test_the_package_is_pushed(self):
        self.assertEqual(len(self.scripts), 1,
                         "expected exactly one package-push deploymentScript, found %d - "
                         "with '1' and no push the app deploys green and empty"
                         % len(self.scripts))
        body = (self.scripts[0].get("properties") or {}).get("scriptContent") or ""
        self.assertIn("az storage blob upload", body, "the script does not stage the package")
        self.assertIn("PACKAGE_URL", body, "the script does not download the package")
        # A 404 or an HTML error page is still a file; pushing one indexes nothing.
        self.assertIn("zipfile.ZipFile", body,
                      "the downloaded package is not verified as a readable zip")
        # Running is not health. The count is the only signal that the code loaded.
        self.assertIn("length(value)", body,
                      "the script does not read the function count back")
        self.assertIn("exit 1", body,
                      "the script does not fail when nothing was indexed")

    def test_the_verdict_is_two_readings_not_the_exit_code(self):
        """ARM reported 1 function on an app whose host answered 503 with the
        pointer left at "1". The count alone is not proof; both readings decide,
        and the pointer value (a SAS token) is never echoed."""
        body = (self.scripts[0].get("properties") or {}).get("scriptContent") or ""
        self.assertIn("the readings decide", body,
                      "the script trusts config-zip's exit code")
        self.assertIn("staged()", body,
                      "nothing checks that the pointer became a blob under "
                      "function-releases - a package staged elsewhere is lost "
                      "on the next restart")
        self.assertIn("function-releases", body,
                      "the pointer reading does not look for the blob container")
        self.assertEqual(body.count("$(pointer)"), 1,
                         "the pointer value belongs only in `case`; it carries a "
                         "SAS token")
        self.assertIn('case "$(pointer)" in', body,
                      "the pointer value is not read into `case`")
        self.assertIn("for attempt in", body,
                      "a single push is a coin flip against a provisioning app")
        self.assertIn("for wait in $(seq 1 8)", body,
                      "the settings read is not retried, so a role assignment "
                      "that is still propagating reads as a missing connection")
        # Measured on a TAXII run: the pointer was written, no restart followed
        # and the function never appeared -- it indexed one minute after an
        # explicit restart. Writing the pointer does not reload the host.
        self.assertIn("functionapp restart", body,
                      "the script writes the package pointer and only waits")

    def test_every_variable_the_script_reads_is_declared(self):
        """An undeclared variable is the empty string in bash, so `curl -L ""`
        returns HTTP 000 and the failure blames the package URL, not the template."""
        props = self.scripts[0].get("properties") or {}
        declared = {e.get("name") for e in (props.get("environmentVariables") or [])}
        used = set(re.findall(r"\$([A-Z][A-Z0-9_]*)", props.get("scriptContent") or ""))
        # Names the script assigns itself (BLOB, CONN, SA, SAS) are not the
        # template's job to declare.
        used -= set(re.findall(r"(?:^|[\s;&|{(])([A-Z][A-Z0-9_]*)=", props.get("scriptContent") or ""))
        self.assertFalse(sorted(used - declared),
                         "the script reads %s but the template does not declare them"
                         % sorted(used - declared))

    def test_a_redeploy_pushes_again(self):
        props = self.scripts[0].get("properties") or {}
        tag = props.get("forceUpdateTag")
        self.assertTrue(tag,
                        "no forceUpdateTag: a redeploy resets WEBSITE_RUN_FROM_PACKAGE "
                        "back to '1' and the push does not re-run - Succeeded, no code")
        ref = re.match(r"^\[parameters\('([^']+)'\)\]$", str(tag))
        self.assertIsNotNone(ref, "forceUpdateTag is %r - it has to reference a "
                                  "parameter whose default changes per deployment" % (tag,))
        self.assertEqual(
            self.params.get(ref.group(1), {}).get("defaultValue"), "[utcNow()]",
            "%s does not default to utcNow(), so the tag never changes and the push is "
            "skipped on every redeploy" % ref.group(1),
        )

    def test_the_package_source_is_still_wired(self):
        self.assertIn("PackageUri", self.params,
                      "PackageUri is gone but the script still needs a source")
        self.assertIn("parameters('PackageUri')", TEMPLATE.read_text(),
                      "PackageUri is declared and never referenced - the package would "
                      "come from nowhere")

    def test_the_pusher_can_reach_the_app(self):
        """The script reads and writes app settings through ARM, so the Website
        Contributor assignment has to be in place before the script runs."""
        deps = json.dumps(self.scripts[0].get("dependsOn") or [])
        self.assertIn("WebsiteContributor", deps,
                      "the push does not wait for the Website Contributor assignment")

    def test_the_source_and_the_built_template_agree(self):
        """The deploy button serves azuredeploy.json while anyone editing edits the
        bicep. These two drifted once already -- the committed JSON and a fresh build
        differed in 66 lines -- so the part that matters here is pinned explicitly."""
        src = BICEP.read_text()
        self.assertIn("forceUpdateTag: _packagePushTimestamp", src,
                      "azuredeploy.bicep has no forceUpdateTag on the push")
        self.assertIn("az storage blob upload", src, "azuredeploy.bicep does not stage the package")
        self.assertNotIn(
            "value: 'https://github.com/orcunsami/SOCRadar-Azure-Entra-ID/releases",
            src.replace("param PackageUri string = 'https://github.com/orcunsami/"
                        "SOCRadar-Azure-Entra-ID/releases/download/v1.0.0/FunctionApp.zip'",
                        ""),
            "azuredeploy.bicep still hands a release URL to an app setting",
        )


if __name__ == "__main__":
    unittest.main()
