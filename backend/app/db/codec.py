"""JSON (de)serialisation of domain values for storage. The one place that knows the format."""

from dataclasses import asdict
from typing import Any

from app.domain.flow import (
    Add,
    BringBack,
    FlowState,
    OfferRow,
    Op,
    Pin,
    Remove,
    RemovedBy,
    RowStatus,
    SetShare,
    TogglePin,
)

_OP_KINDS: dict[str, type] = {
    "remove": Remove,
    "bring_back": BringBack,
    "add": Add,
    "set_share": SetShare,
    "toggle_pin": TogglePin,
}
_KIND_OF = {cls: kind for kind, cls in _OP_KINDS.items()}


def state_to_json(state: FlowState) -> dict[str, Any]:
    return {"rows": [asdict(r) for r in state.rows], "next_pin_seq": state.next_pin_seq}


def _row(data: dict[str, Any]) -> OfferRow:
    pin = data.get("pin")
    removed_by = data.get("removed_by")
    return OfferRow(
        offer_id=data["offer_id"],
        status=RowStatus(data["status"]),
        share=data["share"],
        kt_state=data["kt_state"],
        pin=Pin(**pin) if pin else None,
        removed_by=RemovedBy(removed_by) if removed_by else None,
        archived=data["archived"],
    )


def state_from_json(data: dict[str, Any]) -> FlowState:
    return FlowState(rows=tuple(_row(r) for r in data["rows"]),
                     next_pin_seq=data["next_pin_seq"])


def op_to_json(op: Op) -> dict[str, Any]:
    return {"kind": _KIND_OF[type(op)], **asdict(op)}


def op_from_json(data: dict[str, Any]) -> Op:
    fields = dict(data)
    kind = fields.pop("kind")
    if kind not in _OP_KINDS:
        raise ValueError(f"unknown op kind {kind!r}")
    return _OP_KINDS[kind](**fields)


def ops_to_json(ops: list[Op]) -> list[dict[str, Any]]:
    return [op_to_json(op) for op in ops]


def ops_from_json(data: list[dict[str, Any]]) -> list[Op]:
    return [op_from_json(d) for d in data]
