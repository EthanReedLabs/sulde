from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from sulde_effects import (  # noqa: E402
    DEFAULT_EFFECT_ROUTER,
    AllowedParallelism,
    AuthorityRequirement,
    CapabilitySpec,
    EffectClass,
    EffectRouter,
    EffectRouterError,
    RollbackKind,
    TimeoutPolicy,
)
from intervention import verifier_matches  # noqa: E402


class EffectRouterTests(unittest.TestCase):
    def test_manifests_are_stable_and_separate_verifier_policy(self) -> None:
        rebuilt = EffectRouter(reversed(DEFAULT_EFFECT_ROUTER.specs))
        self.assertEqual(
            rebuilt.manifest_sha256,
            DEFAULT_EFFECT_ROUTER.manifest_sha256,
        )
        self.assertEqual(
            rebuilt.verifier_manifest_sha256,
            DEFAULT_EFFECT_ROUTER.verifier_manifest_sha256,
        )
        self.assertNotEqual(
            rebuilt.manifest_sha256,
            rebuilt.verifier_manifest_sha256,
        )

    def test_registered_capability_wins_over_legacy_effect(self) -> None:
        routed = DEFAULT_EFFECT_ROUTER.route(
            "mcp:figma:download_assets",
            legacy_effect="external_write",
        )

        self.assertEqual(routed.effect_class, EffectClass.READ)
        self.assertEqual(routed.source, "registry")
        self.assertIsNotNone(routed.spec)

    def test_unregistered_capability_has_explicit_legacy_seam(self) -> None:
        routed = DEFAULT_EFFECT_ROUTER.route(
            "mcp:legacy:update_document",
            legacy_effect="external_write",
        )

        self.assertEqual(routed.effect_class, EffectClass.EXTERNAL_WRITE)
        self.assertEqual(routed.source, "legacy_fallback")
        self.assertIsNone(routed.spec)

    def test_unregistered_without_fallback_is_unknown(self) -> None:
        routed = DEFAULT_EFFECT_ROUTER.route("tool:unregistered")

        self.assertEqual(routed.effect_class, EffectClass.UNKNOWN)
        self.assertEqual(routed.source, "unregistered")

    def test_registered_verifier_is_exact_and_alias_aware(self) -> None:
        annotation = DEFAULT_EFFECT_ROUTER.route(
            "mcp:sulde_kb:memory_annotate",
            legacy_effect="local_write",
        )
        self.assertEqual(annotation.effect_class, EffectClass.EXTERNAL_WRITE)
        self.assertTrue(
            DEFAULT_EFFECT_ROUTER.verifier_match(
                "mcp:sulde-kb:memory_annotate",
                "mcp:sulde_kb:memory_search",
            )
        )
        self.assertFalse(
            DEFAULT_EFFECT_ROUTER.verifier_match(
                "mcp:sulde-kb:memory_annotate",
                "mcp:sulde_kb:search_memory",
            )
        )
        self.assertIsNone(
            DEFAULT_EFFECT_ROUTER.verifier_match(
                "mcp:legacy:update_document",
                "mcp:legacy:get_document",
            )
        )

    def test_intervention_uses_exact_registry_before_legacy_heuristic(self) -> None:
        self.assertTrue(
            verifier_matches(
                "mcp:sulde_kb:memory_annotate",
                "mcp:sulde_kb:memory_search",
            )
        )
        self.assertFalse(
            verifier_matches(
                "mcp:sulde_kb:memory_annotate",
                "mcp:sulde_kb:search_memory",
            )
        )
        self.assertTrue(
            verifier_matches(
                "mcp:legacy:update_document",
                "mcp:legacy:get_document",
            )
        )

    def test_alias_collision_is_rejected(self) -> None:
        common = dict(
            aliases=(),
            argument_schema=(),
            effect_class=EffectClass.LOCAL_WRITE,
            authority=AuthorityRequirement.INTENT,
            parallelism=AllowedParallelism.SERIAL_RESOURCE,
            verifier_capabilities=(),
            rollback=RollbackKind.REVERSIBLE,
            timeout_policy=TimeoutPolicy.VERIFY_THEN_UNKNOWN,
        )
        first = CapabilitySpec(canonical_name="tool:first", **common)
        second = CapabilitySpec(
            canonical_name="tool:second",
            **{**common, "aliases": ("tool:first",)},
        )

        with self.assertRaisesRegex(EffectRouterError, "collision"):
            EffectRouter((first, second))

    def test_read_capability_cannot_require_write_authority(self) -> None:
        with self.assertRaisesRegex(EffectRouterError, "read capabilities"):
            CapabilitySpec(
                canonical_name="tool:bad_read",
                aliases=(),
                argument_schema=(),
                effect_class=EffectClass.READ,
                authority=AuthorityRequirement.INTENT,
                parallelism=AllowedParallelism.PARALLEL,
                verifier_capabilities=(),
                rollback=RollbackKind.NONE,
                timeout_policy=TimeoutPolicy.NO_EFFECT,
            )


if __name__ == "__main__":
    unittest.main()
