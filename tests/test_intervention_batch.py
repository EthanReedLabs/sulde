from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
import sys

sys.path.insert(0, str(SCRIPT_DIR))

from intervention import (  # noqa: E402
    InterventionError,
    begin_attempt,
    canonical_resource_key,
    dispatch_attempt_batch,
    effect_operation_fingerprint,
    event_store_path,
    git_ref_verification_digest,
    load_projection,
    mark_attempt_result,
    mark_attempt_unknown,
    prepare_attempt_batch,
    replay,
    resolve_attempt_target,
    summary,
)


class InterventionBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "kb"
        self.contract = self.home / "intent" / "workspaces" / "one.active.json"
        self.contract.parent.mkdir(parents=True)
        self.contract.write_text("{}\n", encoding="utf-8")
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        self.local_file = self.workspace / "artifact.txt"
        self.local_file.write_text("before\n", encoding="utf-8")
        self.arguments_digest = hashlib.sha256(b"one exact host call").hexdigest()
        self.environment = mock.patch.dict(
            os.environ,
            {
                "SULDE_KB_HOME": str(self.home),
                "SULDE_NOTIFY": "off",
                "SULDE_GUARDIAN_STREAM_OWNER": "0",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def resource(
        self,
        target: str,
        *,
        kind: str,
        identity: object | None = None,
        resource_base: Path | None = None,
        resource_context: dict[str, str] | None = None,
        verification_kind: str = "existence",
        verification_sha256: str = "",
        arguments_digest: str | None = None,
    ) -> dict:
        key = canonical_resource_key(
            target if identity is None else identity,
            kind=kind,
            base=resource_base,
        )
        selected_digest = arguments_digest or self.arguments_digest
        return {
            "target": target,
            "resource_key": key,
            "resource_base": resource_base,
            "resource_context": resource_context,
            "operation_arguments_digest": selected_digest,
            "operation_fingerprint": effect_operation_fingerprint(
                provider="codex",
                capability="tool:typed_batch_write",
                target=target,
                resource_key=key,
                effect="external_write",
                arguments_digest=selected_digest,
            ),
            "verification_kind": verification_kind,
            "verification_sha256": verification_sha256,
        }

    def mixed_resources(self) -> list[dict]:
        remote = "https://example.com/repository.git"
        ref = "refs/heads/main"
        oid = "a" * 40
        return [
            self.resource(
                "artifact.txt",
                kind="path",
                resource_base=self.workspace,
            ),
            self.resource("HTTPS://Example.COM:443/a/../doc", kind="uri"),
            self.resource(
                "document-one",
                kind="mcp",
                identity=("docs", "document", "document-one"),
                resource_context={
                    "server": "docs",
                    "resource_kind": "document",
                    "identifier": "document-one",
                },
            ),
            self.resource(
                "git push origin main",
                kind="git",
                identity={"remote": remote, "ref": ref},
                resource_context={"remote": remote, "ref": ref, "oid": oid},
                verification_kind="relation",
                verification_sha256=git_ref_verification_digest(
                    remote=remote,
                    ref=ref,
                    oid=oid,
                ),
            ),
            self.resource(
                "provider-specific-object",
                kind="opaque",
                resource_context={
                    "schema": "exact",
                    "value": "provider-specific-object",
                },
            ),
        ]

    def prepare(
        self,
        resources: list[dict] | None = None,
        *,
        call_id: str = "host-call-one",
        idempotency_key: str = "batch-one",
    ) -> dict:
        return prepare_attempt_batch(
            self.contract,
            intent_id="intent-one",
            intent_revision=7,
            fingerprint="f" * 64,
            source_event_id="event-batch-one",
            capability="tool:typed_batch_write",
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            task_id="task-one",
            call_id=call_id,
            idempotency_key=idempotency_key,
            operation_arguments_digest=self.arguments_digest,
            resources=resources if resources is not None else self.mixed_resources(),
        )

    def dispatch(self, prepared: dict, **overrides: str) -> dict:
        return dispatch_attempt_batch(
            self.contract,
            call_id=overrides.get("call_id", prepared["call_id"]),
            idempotency_key=overrides.get(
                "idempotency_key", prepared["idempotency_key"]
            ),
            prepared_event_id=overrides.get(
                "prepared_event_id", prepared["prepared_event_id"]
            ),
        )

    def rows(self) -> list[dict]:
        store = event_store_path(self.contract)
        if not store.is_file():
            return []
        return [
            json.loads(line)
            for line in store.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_mixed_batch_is_prepared_then_dispatched_as_two_atomic_events(self) -> None:
        prepared = self.prepare()
        projection = load_projection(self.contract)

        self.assertEqual(prepared["state"], "prepared")
        self.assertEqual(len(prepared["resources"]), 5)
        self.assertEqual(projection["attempts"], {})
        self.assertEqual(summary(self.contract)["attempts"], 0)
        self.assertEqual([row["type"] for row in self.rows()], ["effect.batch_prepared"])

        dispatched = self.dispatch(prepared)
        projection = load_projection(self.contract)
        attempts = [projection["attempts"][value] for value in dispatched["attempt_ids"]]

        self.assertEqual(dispatched["state"], "dispatched")
        self.assertEqual(len(attempts), 5)
        self.assertEqual({row["state"] for row in attempts}, {"dispatched"})
        self.assertTrue(all(row["batch_id"] == prepared["batch_id"] for row in attempts))
        self.assertEqual(
            [row["type"] for row in self.rows()],
            ["effect.batch_prepared", "effect.batch_dispatched"],
        )
        self.assertEqual(summary(self.contract)["attempts_by_state"], {"dispatched": 5})

    def test_invalid_middle_context_leaves_no_prepared_prefix(self) -> None:
        resources = self.mixed_resources()
        resources[2]["resource_context"] = {
            "server": "other",
            "resource_kind": "document",
            "identifier": "document-one",
        }

        with self.assertRaisesRegex(InterventionError, "context|resource key"):
            self.prepare(resources)

        self.assertEqual(self.rows(), [])

    def test_duplicate_canonical_key_including_alias_is_rejected_atomically(self) -> None:
        first = self.resource("HTTPS://EXAMPLE.COM:443/document", kind="uri")
        alias = self.resource("https://example.com/document", kind="uri")

        with self.assertRaisesRegex(InterventionError, "duplicate|alias"):
            self.prepare([first, alias])

        self.assertEqual(self.rows(), [])

    def test_operation_fingerprint_and_arguments_digest_are_rederived(self) -> None:
        resources = self.mixed_resources()
        resources[3]["operation_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(InterventionError, "operation fingerprint"):
            self.prepare(resources)
        self.assertEqual(self.rows(), [])

        resources = self.mixed_resources()
        resources[1]["operation_arguments_digest"] = "bad"
        with self.assertRaisesRegex(InterventionError, "arguments digest"):
            self.prepare(resources)
        self.assertEqual(self.rows(), [])

    def test_dispatch_requires_exact_call_idempotency_and_prepare_cas(self) -> None:
        prepared = self.prepare([self.mixed_resources()[1]])
        for field, value in (
            ("call_id", "other-call"),
            ("idempotency_key", "other-key"),
            ("prepared_event_id", "0" * 64),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(InterventionError, "CAS|batch|prepared"):
                    self.dispatch(prepared, **{field: value})
                self.assertEqual(load_projection(self.contract)["attempts"], {})
                self.assertEqual(len(self.rows()), 1)

    def test_concurrent_dispatch_consumes_prepare_once(self) -> None:
        prepared = self.prepare([self.mixed_resources()[1]])
        barrier = threading.Barrier(3)
        results: list[dict] = []
        errors: list[BaseException] = []
        launch_count = 0
        launch_lock = threading.Lock()

        def consume() -> None:
            nonlocal launch_count
            barrier.wait()
            try:
                result = self.dispatch(prepared)
                results.append(result)
                if result["claimed"]:
                    with launch_lock:
                        launch_count += 1
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(sorted(result["claimed"] for result in results), [False, True])
        self.assertEqual(launch_count, 1)
        self.assertEqual(results[0]["dispatched_event_id"], results[1]["dispatched_event_id"])
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(len(load_projection(self.contract)["attempts"]), 1)

    def test_repair1_dispatched_row_is_not_replay_execution_permission(self) -> None:
        prepared = self.prepare([self.mixed_resources()[1]])
        launch_count = 0

        for _ in range(2):
            result = self.dispatch(prepared)
            if result["claimed"]:
                launch_count += 1

        self.assertEqual(launch_count, 1)
        self.assertTrue(self.dispatch(prepared)["claimed"] is False)
        self.assertEqual(len(self.rows()), 2)

    def test_prepare_fsync_crash_replay_does_not_append_second_authority(self) -> None:
        with mock.patch("intervention.os.fsync", side_effect=OSError("crash after write")):
            with self.assertRaisesRegex(OSError, "crash after write"):
                self.prepare([self.mixed_resources()[1]])

        replayed = load_projection(self.contract)
        self.assertEqual(len(replayed["batches"]), 1)
        self.assertEqual(replayed["attempts"], {})
        prepared = self.prepare([self.mixed_resources()[1]])
        self.assertEqual(prepared["state"], "prepared")
        self.assertEqual(len(self.rows()), 1)

    def test_dispatch_fsync_crash_replay_does_not_authorize_twice(self) -> None:
        prepared = self.prepare([self.mixed_resources()[1]])
        with mock.patch("intervention.os.fsync", side_effect=OSError("crash after write")):
            with self.assertRaisesRegex(OSError, "crash after write"):
                self.dispatch(prepared)

        replayed = load_projection(self.contract)
        self.assertEqual(replayed["batches"][prepared["batch_id"]]["state"], "dispatched")
        self.assertEqual(len(replayed["attempts"]), 1)
        dispatched = self.dispatch(prepared)
        self.assertEqual(dispatched["state"], "dispatched")
        self.assertTrue(dispatched["claimed"] is False)
        self.assertEqual(len(self.rows()), 2)

    def test_replay_prefix_ending_at_prepare_never_exposes_partial_dispatch(self) -> None:
        prepared = self.prepare([self.mixed_resources()[1], self.mixed_resources()[2]])
        self.dispatch(prepared)
        rows = self.rows()

        replayed = replay(self.contract, rows[:1])
        self.assertEqual(replayed["batches"][prepared["batch_id"]]["state"], "prepared")
        self.assertEqual(replayed["attempts"], {})

        repeated = self.dispatch(prepared)
        self.assertEqual(repeated["state"], "dispatched")
        self.assertTrue(repeated["claimed"] is False)
        self.assertEqual(len(load_projection(self.contract)["attempts"]), 2)
        self.assertEqual(len(self.rows()), 2)

    def test_same_call_new_idempotency_key_points_to_original_batch(self) -> None:
        resource = self.mixed_resources()[1]
        original = self.prepare([resource], idempotency_key="batch-one")
        self.assertTrue(self.dispatch(original)["claimed"] is True)
        repeated = self.prepare([resource], idempotency_key="batch-two")

        self.assertEqual(repeated["batch_id"], original["batch_id"])
        self.assertEqual(repeated["idempotency_key"], "batch-one")
        self.assertEqual(repeated["state"], "dispatched")
        self.assertTrue(self.dispatch(repeated)["claimed"] is False)
        self.assertEqual(len(self.rows()), 2)
        projection = load_projection(self.contract)
        self.assertEqual(len(projection["batch_calls"]), 1)
        self.assertEqual(set(projection["batch_calls"].values()), {original["batch_id"]})

    def test_same_call_different_semantics_fails_before_second_prepare(self) -> None:
        original = self.prepare(
            [self.mixed_resources()[1]], idempotency_key="batch-one"
        )
        before = list(self.rows())

        with self.assertRaisesRegex(InterventionError, "call|semantics"):
            self.prepare(
                [self.mixed_resources()[2]], idempotency_key="batch-two"
            )

        self.assertEqual(self.rows(), before)
        projection = load_projection(self.contract)
        self.assertEqual(list(projection["batches"]), [original["batch_id"]])

    def test_call_id_requires_one_nonempty_exact_string(self) -> None:
        resource = self.mixed_resources()[1]
        for value in (None, "", "   ", 7):
            with self.subTest(value=value):
                with self.assertRaisesRegex(InterventionError, "call id"):
                    self.prepare(
                        [resource],
                        call_id=value,  # type: ignore[arg-type]
                        idempotency_key=f"batch-{value!r}",
                    )
                self.assertEqual(self.rows(), [])

    def test_concurrent_same_call_prepare_has_one_batch_identity(self) -> None:
        resource = self.mixed_resources()[1]
        barrier = threading.Barrier(3)
        results: list[dict] = []
        errors: list[BaseException] = []

        def prepare(key: str) -> None:
            barrier.wait()
            try:
                results.append(self.prepare([resource], idempotency_key=key))
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        threads = [
            threading.Thread(target=prepare, args=("batch-one",)),
            threading.Thread(target=prepare, args=("batch-two",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len({result["batch_id"] for result in results}), 1)
        self.assertEqual(len(self.rows()), 1)
        projection = load_projection(self.contract)
        self.assertEqual(len(projection["batches"]), 1)
        self.assertEqual(len(projection["batch_calls"]), 1)

    def test_concurrent_same_call_different_semantics_fails_one_closed(self) -> None:
        resources = [self.mixed_resources()[1], self.mixed_resources()[2]]
        barrier = threading.Barrier(3)
        results: list[dict] = []
        errors: list[BaseException] = []

        def prepare(ordinal: int) -> None:
            barrier.wait()
            try:
                results.append(
                    self.prepare(
                        [resources[ordinal]],
                        idempotency_key=f"batch-{ordinal}",
                    )
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        threads = [threading.Thread(target=prepare, args=(value,)) for value in (0, 1)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertRegex(str(errors[0]), "call|semantics")
        self.assertEqual(len(self.rows()), 1)
        projection = load_projection(self.contract)
        self.assertEqual(len(projection["batches"]), 1)
        self.assertEqual(len(projection["batch_calls"]), 1)

    def test_torn_dispatch_row_fails_closed_without_partial_projection(self) -> None:
        prepared = self.prepare([self.mixed_resources()[1], self.mixed_resources()[2]])
        self.dispatch(prepared)
        store = event_store_path(self.contract)
        lines = store.read_bytes().splitlines(keepends=True)
        store.write_bytes(lines[0] + lines[1][: len(lines[1]) // 2])

        with self.assertRaisesRegex(InterventionError, "invalid intervention JSONL"):
            load_projection(self.contract)
        with self.assertRaisesRegex(InterventionError, "invalid intervention JSONL"):
            self.dispatch(prepared)

    def test_prepared_member_is_not_an_attempt_or_settlement_target(self) -> None:
        prepared = self.prepare([self.mixed_resources()[1]])
        attempt_id = prepared["attempt_ids"][0]
        with self.assertRaisesRegex(InterventionError, "unknown effect attempt"):
            mark_attempt_result(self.contract, attempt_id, success=True)
        self.assertEqual(summary(self.contract)["attempts"], 0)

    def test_prepared_is_not_debt_but_dispatch_rechecks_new_debt(self) -> None:
        resource = self.mixed_resources()[1]
        prepared = self.prepare([resource])
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=7,
            fingerprint="9" * 64,
            source_event_id="single-between-phases",
            capability="tool:typed_batch_write",
            target=resource["target"],
            resource_key=resource["resource_key"],
            effect="external_write",
            provider="codex",
            session_id="thread-two",
            idempotency_key="single-between-phases",
            operation_arguments_digest=resource["operation_arguments_digest"],
            verification_kind="existence",
        )
        self.assertEqual(attempt["state"], "dispatched")

        with self.assertRaisesRegex(InterventionError, "blocker|debt"):
            self.dispatch(prepared)

        replayed = load_projection(self.contract)
        self.assertEqual(replayed["batches"][prepared["batch_id"]]["state"], "prepared")
        self.assertEqual(len(self.rows()), 2)

    def test_existing_debt_blocks_whole_batch_before_prepare(self) -> None:
        resource = self.mixed_resources()[1]
        begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=7,
            fingerprint="1" * 64,
            source_event_id="old-event",
            capability="tool:typed_batch_write",
            target=resource["target"],
            resource_key=resource["resource_key"],
            effect="external_write",
            provider="codex",
            session_id="old-thread",
            idempotency_key="old-single",
            operation_arguments_digest=resource["operation_arguments_digest"],
            verification_kind="existence",
        )
        before = len(self.rows())

        with self.assertRaisesRegex(InterventionError, "blocker|debt"):
            self.prepare([resource])

        self.assertEqual(len(self.rows()), before)
        self.assertEqual(load_projection(self.contract)["batches"], {})

    def test_historical_alias_expands_batch_blocker_only(self) -> None:
        old = self.resource("https://example.com/old", kind="uri")
        new = self.resource("https://example.com/new", kind="uri")
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=7,
            fingerprint="2" * 64,
            source_event_id="alias-event",
            capability="tool:typed_batch_write",
            target=old["target"],
            resource_key=old["resource_key"],
            effect="external_write",
            provider="codex",
            session_id="old-thread",
            idempotency_key="alias-single",
            operation_arguments_digest=old["operation_arguments_digest"],
            verification_kind="existence",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="host outcome lost")
        rebound = resolve_attempt_target(
            self.contract,
            attempt["attempt_id"],
            target=new["target"],
            resource_key=new["resource_key"],
            operation_fingerprint=new["operation_fingerprint"],
            operation_arguments_digest=new["operation_arguments_digest"],
            verification_kind="existence",
            expected_target_sha256=attempt["target_sha256"],
            expected_resource_sha256=attempt["resource_sha256"],
            expected_operation_fingerprint=attempt["operation_fingerprint"],
        )
        self.assertEqual(len(rebound["identity_history"]), 1)

        with self.assertRaisesRegex(InterventionError, "blocker|debt"):
            self.prepare([old])

        self.assertEqual(summary(self.contract)["attempts"], 1)

    def test_batch_and_single_attempt_cannot_share_call_idempotency(self) -> None:
        resource = self.mixed_resources()[1]
        begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=7,
            fingerprint="3" * 64,
            source_event_id="single-event",
            capability="tool:typed_batch_write",
            target="https://example.com/unrelated",
            resource_key=canonical_resource_key(
                "https://example.com/unrelated", kind="uri"
            ),
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="shared-idempotency",
            operation_arguments_digest=self.arguments_digest,
            verification_kind="existence",
        )
        with self.assertRaisesRegex(InterventionError, "idempotency"):
            self.prepare([resource], idempotency_key="shared-idempotency")

        other_contract = self.contract.with_name("two.active.json")
        other_contract.write_text("{}\n", encoding="utf-8")
        prepared = prepare_attempt_batch(
            other_contract,
            intent_id="intent-one",
            intent_revision=7,
            fingerprint="f" * 64,
            source_event_id="batch-event",
            capability="tool:typed_batch_write",
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            call_id="call-two",
            idempotency_key="shared-idempotency",
            operation_arguments_digest=self.arguments_digest,
            resources=[resource],
        )
        self.assertEqual(prepared["state"], "prepared")
        with self.assertRaisesRegex(InterventionError, "idempotency"):
            begin_attempt(
                other_contract,
                intent_id="intent-one",
                intent_revision=7,
                fingerprint="4" * 64,
                source_event_id="single-after-batch",
                capability="tool:typed_batch_write",
                target="https://example.com/another",
                resource_key=canonical_resource_key(
                    "https://example.com/another", kind="uri"
                ),
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="shared-idempotency",
                operation_arguments_digest=self.arguments_digest,
                verification_kind="existence",
            )


if __name__ == "__main__":
    unittest.main()
