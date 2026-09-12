"""Exact capability-to-effect routing with an explicit legacy fallback seam."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Iterable


_CAPABILITY_RE = re.compile(
    r"^(?:tool|skill):[a-z0-9][a-z0-9._-]{0,127}$|"
    r"^mcp:[a-z0-9][a-z0-9._-]{0,127}:[a-z0-9][a-z0-9._-]{0,127}$"
)
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class EffectRouterError(ValueError):
    """A capability registry is ambiguous or invalid."""


class EffectClass(str, Enum):
    READ = "read"
    LOCAL_WRITE = "local_write"
    EXTERNAL_WRITE = "external_write"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


class AuthorityRequirement(str, Enum):
    NONE = "none"
    INTENT = "intent"
    HUMAN = "human"
    DENY = "deny"


class AllowedParallelism(str, Enum):
    PARALLEL = "parallel"
    SERIAL_RESOURCE = "serial_resource"
    SERIAL_WORKSPACE = "serial_workspace"


class RollbackKind(str, Enum):
    NONE = "none"
    REVERSIBLE = "reversible"
    COMPENSATABLE = "compensatable"


class TimeoutPolicy(str, Enum):
    NO_EFFECT = "no_effect"
    VERIFY_THEN_UNKNOWN = "verify_then_unknown"
    UNKNOWN = "unknown"


def canonical_capability(value: str) -> str:
    if type(value) is not str:
        raise EffectRouterError("capability name must be a string")
    canonical = value.strip().lower()
    if canonical != value.lower() or _CAPABILITY_RE.fullmatch(canonical) is None:
        raise EffectRouterError("capability name is not canonical")
    return canonical


@dataclass(frozen=True)
class ArgumentField:
    name: str
    required: bool = False
    sensitive: bool = False

    def __post_init__(self) -> None:
        if type(self.name) is not str or _FIELD_RE.fullmatch(self.name) is None:
            raise EffectRouterError("argument field name is invalid")
        if type(self.required) is not bool or type(self.sensitive) is not bool:
            raise EffectRouterError("argument field flags must be booleans")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "required": self.required,
            "sensitive": self.sensitive,
        }


@dataclass(frozen=True)
class CapabilitySpec:
    canonical_name: str
    aliases: tuple[str, ...]
    argument_schema: tuple[ArgumentField, ...]
    effect_class: EffectClass
    authority: AuthorityRequirement
    parallelism: AllowedParallelism
    verifier_capabilities: tuple[str, ...]
    rollback: RollbackKind
    timeout_policy: TimeoutPolicy

    def __post_init__(self) -> None:
        canonical = canonical_capability(self.canonical_name)
        if canonical != self.canonical_name:
            raise EffectRouterError("canonical capability must be lowercase")
        if type(self.aliases) is not tuple or type(self.argument_schema) is not tuple:
            raise EffectRouterError("capability spec collections must be tuples")
        if type(self.verifier_capabilities) is not tuple:
            raise EffectRouterError("verifier capability collection must be a tuple")
        names = [canonical_capability(alias) for alias in self.aliases]
        if len(set(names)) != len(names) or self.canonical_name in names:
            raise EffectRouterError("capability aliases are duplicated")
        fields = [field.name for field in self.argument_schema]
        if len(set(fields)) != len(fields):
            raise EffectRouterError("argument schema fields are duplicated")
        for verifier in self.verifier_capabilities:
            canonical_capability(verifier)
        if type(self.effect_class) is not EffectClass:
            raise EffectRouterError("effect_class must be typed")
        if type(self.authority) is not AuthorityRequirement:
            raise EffectRouterError("authority must be typed")
        if type(self.parallelism) is not AllowedParallelism:
            raise EffectRouterError("parallelism must be typed")
        if type(self.rollback) is not RollbackKind:
            raise EffectRouterError("rollback must be typed")
        if type(self.timeout_policy) is not TimeoutPolicy:
            raise EffectRouterError("timeout_policy must be typed")
        if self.effect_class is EffectClass.READ and (
            self.authority is not AuthorityRequirement.NONE
            or self.timeout_policy is not TimeoutPolicy.NO_EFFECT
        ):
            raise EffectRouterError("read capabilities cannot require write authority")
        if self.effect_class is EffectClass.DESTRUCTIVE and self.authority not in {
            AuthorityRequirement.HUMAN,
            AuthorityRequirement.DENY,
        }:
            raise EffectRouterError("destructive capabilities require human or deny")

    @property
    def sensitive_fields(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.argument_schema if field.sensitive)

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "argument_schema": [field.to_dict() for field in self.argument_schema],
            "effect_class": self.effect_class.value,
            "authority": self.authority.value,
            "parallelism": self.parallelism.value,
            "verifier_capabilities": list(self.verifier_capabilities),
            "rollback": self.rollback.value,
            "timeout_policy": self.timeout_policy.value,
        }


@dataclass(frozen=True)
class RoutedEffect:
    requested_capability: str
    effect_class: EffectClass
    source: str
    spec: CapabilitySpec | None


class EffectRouter:
    """Immutable exact-name registry; verb inference remains an explicit fallback."""

    def __init__(self, specs: Iterable[CapabilitySpec]) -> None:
        registry: dict[str, CapabilitySpec] = {}
        canonical_specs: dict[str, CapabilitySpec] = {}
        for spec in specs:
            if type(spec) is not CapabilitySpec:
                raise EffectRouterError("router accepts only CapabilitySpec values")
            if spec.canonical_name in canonical_specs:
                raise EffectRouterError("duplicate canonical capability")
            canonical_specs[spec.canonical_name] = spec
            for name in (spec.canonical_name, *spec.aliases):
                if name in registry:
                    raise EffectRouterError(f"capability alias collision: {name}")
                registry[name] = spec
        self._registry = MappingProxyType(registry)
        self._specs = tuple(canonical_specs[name] for name in sorted(canonical_specs))

    @property
    def specs(self) -> tuple[CapabilitySpec, ...]:
        return self._specs

    @property
    def manifest(self) -> tuple[dict[str, object], ...]:
        return tuple(spec.to_dict() for spec in self._specs)

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @property
    def verifier_manifest_sha256(self) -> str:
        manifest = [
            {
                "capability": spec.canonical_name,
                "verifiers": list(spec.verifier_capabilities),
            }
            for spec in self._specs
            if spec.verifier_capabilities
        ]
        return hashlib.sha256(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def resolve(self, capability: str) -> CapabilitySpec | None:
        try:
            name = canonical_capability(capability)
        except EffectRouterError:
            return None
        return self._registry.get(name)

    def route(
        self,
        capability: str,
        *,
        legacy_effect: str | None = None,
    ) -> RoutedEffect:
        requested = canonical_capability(capability)
        spec = self._registry.get(requested)
        if spec is not None:
            return RoutedEffect(requested, spec.effect_class, "registry", spec)
        if legacy_effect is not None:
            try:
                effect = EffectClass(legacy_effect)
            except (TypeError, ValueError) as error:
                raise EffectRouterError("legacy effect is invalid") from error
            return RoutedEffect(requested, effect, "legacy_fallback", None)
        return RoutedEffect(requested, EffectClass.UNKNOWN, "unregistered", None)

    def verifier_match(self, write_capability: str, read_capability: str) -> bool | None:
        write = self.resolve(write_capability)
        if write is None:
            return None
        try:
            candidate = canonical_capability(read_capability)
        except EffectRouterError:
            return False
        return candidate in write.verifier_capabilities


def _spec(
    canonical_name: str,
    *,
    aliases: tuple[str, ...] = (),
    effect: EffectClass,
    authority: AuthorityRequirement,
    parallelism: AllowedParallelism,
    verifiers: tuple[str, ...] = (),
    rollback: RollbackKind = RollbackKind.NONE,
    timeout: TimeoutPolicy,
    arguments: tuple[ArgumentField, ...] = (),
) -> CapabilitySpec:
    return CapabilitySpec(
        canonical_name=canonical_name,
        aliases=aliases,
        argument_schema=arguments,
        effect_class=effect,
        authority=authority,
        parallelism=parallelism,
        verifier_capabilities=verifiers,
        rollback=rollback,
        timeout_policy=timeout,
    )


_DEFAULT_SPECS = (
    _spec(
        "tool:read",
        aliases=(
            "tool:glob", "tool:grep", "tool:find", "tool:view_image",
            "tool:search", "tool:webrun", "tool:web.run", "tool:web__run",
        ),
        effect=EffectClass.READ,
        authority=AuthorityRequirement.NONE,
        parallelism=AllowedParallelism.PARALLEL,
        timeout=TimeoutPolicy.NO_EFFECT,
    ),
    _spec(
        "tool:write",
        aliases=("tool:edit", "tool:multiedit", "tool:file_change"),
        effect=EffectClass.LOCAL_WRITE,
        authority=AuthorityRequirement.INTENT,
        parallelism=AllowedParallelism.SERIAL_RESOURCE,
        rollback=RollbackKind.REVERSIBLE,
        timeout=TimeoutPolicy.VERIFY_THEN_UNKNOWN,
    ),
    _spec(
        "tool:apply_patch",
        effect=EffectClass.LOCAL_WRITE,
        authority=AuthorityRequirement.INTENT,
        parallelism=AllowedParallelism.SERIAL_RESOURCE,
        rollback=RollbackKind.REVERSIBLE,
        timeout=TimeoutPolicy.VERIFY_THEN_UNKNOWN,
        arguments=(ArgumentField("patch", required=True, sensitive=True),),
    ),
    _spec(
        "mcp:figma:download_assets",
        aliases=(
            "mcp:figma:get_design_context", "mcp:figma:get_metadata",
            "mcp:figma:get_screenshot", "mcp:figma:get_variable_defs",
            "mcp:figma:get_code_connect_map",
        ),
        effect=EffectClass.READ,
        authority=AuthorityRequirement.NONE,
        parallelism=AllowedParallelism.PARALLEL,
        timeout=TimeoutPolicy.NO_EFFECT,
    ),
    _spec(
        "mcp:figma:use_figma",
        aliases=("mcp:figma:create_new_file", "mcp:figma:generate_diagram"),
        effect=EffectClass.EXTERNAL_WRITE,
        authority=AuthorityRequirement.INTENT,
        parallelism=AllowedParallelism.SERIAL_RESOURCE,
        rollback=RollbackKind.COMPENSATABLE,
        timeout=TimeoutPolicy.VERIFY_THEN_UNKNOWN,
    ),
    _spec(
        "mcp:sulde_kb:memory_search",
        aliases=(
            "mcp:sulde-kb:memory_search", "mcp:sulde_kb:memory_graph",
            "mcp:sulde-kb:memory_graph", "mcp:sulde_kb:memory_get",
            "mcp:sulde-kb:memory_get", "mcp:sulde_kb:kb_status",
            "mcp:sulde-kb:kb_status",
        ),
        effect=EffectClass.READ,
        authority=AuthorityRequirement.NONE,
        parallelism=AllowedParallelism.PARALLEL,
        timeout=TimeoutPolicy.NO_EFFECT,
    ),
    _spec(
        "mcp:sulde_kb:memory_annotate",
        aliases=("mcp:sulde-kb:memory_annotate",),
        # The ordinary capability writes a shared persistent store.  Only the
        # separately sealed, schema-bounded continuation profile may narrow a
        # concrete invocation to a host-local write.
        effect=EffectClass.EXTERNAL_WRITE,
        authority=AuthorityRequirement.INTENT,
        parallelism=AllowedParallelism.SERIAL_WORKSPACE,
        verifiers=(
            "mcp:sulde_kb:memory_search", "mcp:sulde-kb:memory_search",
            "mcp:sulde_kb:memory_graph", "mcp:sulde-kb:memory_graph",
            "mcp:sulde_kb:memory_get", "mcp:sulde-kb:memory_get",
        ),
        rollback=RollbackKind.COMPENSATABLE,
        timeout=TimeoutPolicy.VERIFY_THEN_UNKNOWN,
        arguments=(ArgumentField("payload", required=True, sensitive=True),),
    ),
)


DEFAULT_EFFECT_ROUTER = EffectRouter(_DEFAULT_SPECS)
