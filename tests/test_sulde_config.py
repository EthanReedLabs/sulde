from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from sulde_config import (  # noqa: E402
    ConfigError,
    ConfigLayer,
    ConfigLayerKind,
    resolve_config,
)


def layer(name: str, kind: ConfigLayerKind, **values: object) -> ConfigLayer:
    return ConfigLayer.build(name=name, kind=kind, values=values)


class SuldeConfigTests(unittest.TestCase):
    def test_ordinary_precedence_preserves_source(self) -> None:
        snapshot = resolve_config(
            (
                layer("defaults", ConfigLayerKind.PACKAGED, **{"ui.mode": "safe"}),
                layer("workspace", ConfigLayerKind.WORKSPACE, **{"ui.mode": "strict"}),
            )
        )

        self.assertEqual(snapshot.effective["ui.mode"], "strict")
        field = next(field for field in snapshot.fields if field.key == "ui.mode")
        self.assertEqual(field.source_layer, "workspace")

    def test_permission_layers_intersect_and_never_broaden(self) -> None:
        snapshot = resolve_config(
            (
                layer(
                    "defaults",
                    ConfigLayerKind.PACKAGED,
                    **{"permissions.paths": ["src", "tests"]},
                ),
                layer(
                    "task",
                    ConfigLayerKind.TASK,
                    **{"permissions.paths": ["src", "tests", "secrets"]},
                ),
                layer(
                    "managed",
                    ConfigLayerKind.MANAGED,
                    **{"permissions.paths": ["tests"]},
                ),
            )
        )

        self.assertEqual(snapshot.effective["permissions.paths"], ["tests"])
        field = next(
            field for field in snapshot.fields if field.key == "permissions.paths"
        )
        self.assertEqual(field.source_layer, "defaults")
        self.assertEqual(field.constrained_by, ("managed",))

    def test_managed_limit_can_only_tighten(self) -> None:
        snapshot = resolve_config(
            (
                layer("task", ConfigLayerKind.TASK, **{"limits.events": 500}),
                layer("managed", ConfigLayerKind.MANAGED, **{"limits.events": 100}),
            )
        )
        self.assertEqual(snapshot.effective["limits.events"], 100)
        field = snapshot.fields[0]
        self.assertEqual(field.source_layer, "task")
        self.assertEqual(field.constrained_by, ("managed",))

    def test_managed_layer_cannot_override_ordinary_configuration(self) -> None:
        with self.assertRaisesRegex(ConfigError, "managed constraints"):
            layer("managed", ConfigLayerKind.MANAGED, **{"ui.mode": "unsafe"})

    def test_snapshot_is_order_independent_and_content_addressed(self) -> None:
        packaged = layer("defaults", ConfigLayerKind.PACKAGED, **{"ui.mode": "safe"})
        task = layer("task", ConfigLayerKind.TASK, **{"limits.events": 20})
        first = resolve_config((packaged, task))
        second = resolve_config((task, packaged))
        self.assertEqual(first, second)
        self.assertRegex(first.snapshot_sha256, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
