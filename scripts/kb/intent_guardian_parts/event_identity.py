"""Host-call identity shared by ordinary and composed event projections."""
import hashlib


def bind_host_call_identity(event):
    if not event.get("call_id"):
        return
    event["event_identity_schema"] = "sulde-host-call-event-v2"
    source = "\0".join(str(event.get(key) or "") for key in (
        "kind", "server", "action", "target", "arguments_digest", "provider", "session_id", "call_id"))
    event["event_id"] = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
