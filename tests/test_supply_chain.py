import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.supply_chain import (
    augment_cyclonedx,
    trace_variant_supply_chain,
    verify_gh_attestations,
    verify_submission,
)


COMMIT = "a" * 40


def submission():
    return {
        "image": "registry.invalid/genomics-variant-pipeline:v0.1.0",
        "image_digest": "sha256:" + "b" * 64,
        "pipeline_version": "v0.1.0",
        "provenance": {
            "repository": "samueltauil/genomics-variant-analytics",
            "commit": COMMIT,
            "workflow": ".github/workflows/pipeline-container.yml",
        },
        "sbom": [
            {"name": "aligner", "version": "synthetic-aligner-1.0.0"},
            {"name": "variant-caller", "version": "synthetic-variant-caller-1.0.0"},
            {"name": "utility", "version": "python-3.12"},
        ],
        "dependencies": [{"name": "pipeline-definition", "commit": COMMIT}],
    }


def verified_chain():
    image_name = "registry.invalid/genomics-variant-pipeline"
    digest = "b" * 64
    return {
        "variant": {
            "CHROM": "chr17",
            "POS": 43071077,
            "REF": "A",
            "ALT": "G",
            "source_file_uri": "abfss://synthetic/vcf/SYN-RUN-001.vcf",
            "pipeline_version": "v0.2.1-pipeline",
        },
        "image": f"{image_name}:v0.2.1-pipeline",
        "release": {
            "verificationResult": {
                "statement": {
                    "subject": [
                        {
                            "uri": (
                                "pkg:github/samueltauil/"
                                "genomics-variant-analytics@v0.2.1-pipeline"
                            ),
                            "digest": {"sha1": COMMIT},
                        }
                    ]
                }
            }
        },
        "provenance": [
            {
                "verificationResult": {
                    "signature": {
                        "certificate": {
                            "sourceRepositoryDigest": COMMIT,
                            "sourceRepositoryRef": "refs/tags/v0.2.1-pipeline",
                        }
                    },
                    "statement": {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [
                            {"name": image_name, "digest": {"sha256": digest}}
                        ],
                    },
                }
            }
        ],
        "sbom": [
            {
                "verificationResult": {
                    "statement": {
                        "predicateType": "https://cyclonedx.org/bom",
                        "subject": [
                            {"name": image_name, "digest": {"sha256": digest}}
                        ],
                        "predicate": {
                            "components": [
                                {
                                    "name": "aligner",
                                    "version": "synthetic-aligner-1.0.0",
                                },
                                {
                                    "name": "variant-caller",
                                    "version": "synthetic-variant-caller-1.0.0",
                                },
                            ]
                        },
                    }
                }
            }
        ],
    }


class SupplyChainTests(unittest.TestCase):
    def test_toolchain_components_are_added_to_cyclonedx(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sbom_path = root / "sbom.cdx.json"
            toolchain_path = root / "toolchain.json"
            sbom_path.write_text(
                json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.6",
                        "components": [
                            {"type": "library", "name": "python", "version": "3.12"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            toolchain_path.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "aligner",
                                "version": "synthetic-aligner-1.0.0",
                                "source_commit": "synthetic-placeholder",
                            },
                            {
                                "name": "variant-caller",
                                "version": "synthetic-variant-caller-1.0.0",
                                "source_commit": "synthetic-placeholder",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            augment_cyclonedx(sbom_path, toolchain_path)
            components = json.loads(sbom_path.read_text(encoding="utf-8"))["components"]
            versions = {component["name"]: component["version"] for component in components}
            self.assertEqual(versions["aligner"], "synthetic-aligner-1.0.0")
            self.assertEqual(
                versions["variant-caller"], "synthetic-variant-caller-1.0.0"
            )

    def test_invalid_toolchain_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sbom_path = root / "sbom.cdx.json"
            toolchain_path = root / "toolchain.json"
            sbom_path.write_text(
                json.dumps({"bomFormat": "CycloneDX", "components": []}),
                encoding="utf-8",
            )
            toolchain_path.write_text(
                json.dumps({"components": [{"name": "aligner", "version": "1"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly"):
                augment_cyclonedx(sbom_path, toolchain_path)

    def test_attested_submission_is_accepted_without_allocating(self):
        verified = verify_submission(submission())
        self.assertEqual(verified["pipeline_version"], "v0.1.0")

    def test_unattested_or_incomplete_submission_is_rejected(self):
        for mutation, expected in (
            ({"image_digest": "not-a-digest"}, "image_digest"),
            ({"sbom": [{"name": "utility", "version": "1"}]}, "missing required"),
            ({"dependencies": [{"name": "untracked", "commit": "short"}]}, "Untracked"),
        ):
            payload = submission()
            payload.update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ValueError, expected):
                    verify_submission(payload)

    def test_registry_attestations_are_both_verified(self):
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, "", "")

        verify_gh_attestations(
            "registry.invalid/image@sha256:" + "b" * 64,
            "samueltauil/genomics-variant-analytics",
            "pipeline.yml",
            runner=runner,
        )
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("--predicate-type" in call for call in calls))
        self.assertTrue(all("--bundle-from-oci" in call for call in calls))

    def test_registry_failure_is_rejected(self):
        def runner(arguments, **kwargs):
            return subprocess.CompletedProcess(arguments, 1, "", "unattested")

        with self.assertRaisesRegex(ValueError, "Attestation verification failed"):
            verify_gh_attestations("registry.invalid/image", "owner/repo", runner=runner)

    def test_variant_resolves_through_release_and_signed_image(self):
        chain = verified_chain()
        result = trace_variant_supply_chain(
            chain["variant"],
            chain["image"],
            chain["release"],
            chain["provenance"],
            chain["sbom"],
        )
        self.assertEqual(result["pipeline_version"], "v0.2.1-pipeline")
        self.assertEqual(result["release_commit"], COMMIT)
        self.assertEqual(
            result["toolchain"],
            {
                "aligner": "synthetic-aligner-1.0.0",
                "variant-caller": "synthetic-variant-caller-1.0.0",
            },
        )

    def test_variant_trace_rejects_a_cross_release_image(self):
        chain = verified_chain()
        chain["provenance"][0]["verificationResult"]["signature"]["certificate"][
            "sourceRepositoryRef"
        ] = "refs/tags/v0.2.0-pipeline"
        with self.assertRaisesRegex(ValueError, "source ref"):
            trace_variant_supply_chain(
                chain["variant"],
                chain["image"],
                chain["release"],
                chain["provenance"],
                chain["sbom"],
            )


if __name__ == "__main__":
    unittest.main()
