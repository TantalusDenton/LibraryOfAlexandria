"""Local infrastructure assertions; Azure-side validation still requires subscription access."""

import json
import unittest

from templates import foundation, names, runtime


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.names = names("0123456789")

    def test_foundation_keeps_database_private_and_credentials_in_key_vault(self):
        doc = foundation(self.names, "eastus2", "owner@example.org")
        json.loads(json.dumps(doc))
        resources = doc["resources"]
        postgres = next(
            r
            for r in resources
            if r["type"] == "Microsoft.DBforPostgreSQL/flexibleServers"
        )
        self.assertEqual(
            postgres["properties"]["network"]["publicNetworkAccess"], "Disabled"
        )
        self.assertEqual(postgres["properties"]["backup"]["backupRetentionDays"], 7)
        self.assertTrue(
            all(p["type"] == "securestring" for p in doc["parameters"].values())
        )
        storage = next(
            r for r in resources if r["type"] == "Microsoft.Storage/storageAccounts"
        )
        self.assertFalse(storage["properties"]["allowSharedKeyAccess"])
        self.assertFalse(storage["properties"]["allowBlobPublicAccess"])

    def test_application_scales_to_zero_and_workers_are_bounded(self):
        doc = runtime(self.names, "eastus2", "owner@example.org", "release-123")
        resources = doc["resources"]
        app = next(r for r in resources if r["type"] == "Microsoft.App/containerApps")
        self.assertEqual(app["properties"]["template"]["scale"]["minReplicas"], 0)
        self.assertEqual(app["properties"]["template"]["scale"]["maxReplicas"], 2)
        self.assertEqual(len(app["properties"]["template"]["containers"]), 2)
        self.assertFalse(app["properties"]["configuration"]["ingress"]["allowInsecure"])
        api = app["properties"]["template"]["containers"][0]
        values = {e["name"]: e.get("value") for e in api["env"]}
        self.assertEqual(values["AI_MODE"], "offline")
        self.assertEqual(values["REGISTRATION_ENABLED"], "false")
        worker = next(r for r in resources if r["name"] == self.names["worker"])
        self.assertEqual(
            worker["properties"]["configuration"]["eventTriggerConfig"]["scale"][
                "maxExecutions"
            ],
            2,
        )
        self.assertEqual(worker["properties"]["configuration"]["replicaRetryLimit"], 0)

    def test_migrations_and_account_bootstrap_are_a_separate_manual_job(self):
        doc = runtime(
            self.names, "eastus2", "owner@example.org", "release-123", "migration"
        )
        self.assertEqual(len(doc["resources"]), 1)
        job = doc["resources"][0]
        self.assertEqual(job["properties"]["configuration"]["triggerType"], "Manual")
        command = job["properties"]["template"]["containers"][0]["args"][0]
        self.assertIn("alembic upgrade head &&", command)
        self.assertIn("app.azure_bootstrap", command)

    def test_rollout_pins_the_current_session_key_version(self):
        version = "https://vault.vault.azure.net/secrets/session-key/current-version"
        doc = runtime(
            self.names,
            "westus2",
            "owner@example.org",
            "release-123",
            session_key_url=version,
        )
        for resource in doc["resources"]:
            secret = next(
                s
                for s in resource["properties"]["configuration"]["secrets"]
                if s["name"] == "session-key"
            )
            self.assertEqual(secret["keyVaultUrl"], version)
        app = next(
            r for r in doc["resources"] if r["type"] == "Microsoft.App/containerApps"
        )
        rotated = runtime(
            self.names,
            "westus2",
            "owner@example.org",
            "release-123",
            session_key_url=version + "-next",
        )
        next_app = next(
            r
            for r in rotated["resources"]
            if r["type"] == "Microsoft.App/containerApps"
        )
        self.assertNotEqual(
            app["properties"]["template"]["revisionSuffix"],
            next_app["properties"]["template"]["revisionSuffix"],
        )


if __name__ == "__main__":
    unittest.main()
