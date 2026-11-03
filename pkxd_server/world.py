"""State of one local, single-player world room (ToxicBird 0.2.49).

The Unity scene selects its own spawn transform. Client movement is raw binary;
the server's remote-player snapshots use a different, compressed format.
Room state is transient and must never be written into account cosmetics.
"""
from dataclasses import dataclass, field
import logging
import math
import struct

from . import wire
from .animation import valid_animation

LOG = logging.getLogger(__name__)
POSITION = struct.Struct(">BBffff")  # teleported, sequence, x, y, z, rotation
LAYER = struct.Struct(">iBffff")    # layer, sequence, x, y, z, rotation
REQUESTS = frozenset(("C", "PL", "slot_interaction"))
BOOL_KEYS = frozenset(("e", "g", "h", "hrsl", "mg", "eb"))
INITIAL_VARIABLES = {
    "A": b"\x02\x00\x00\x00\x00",  # World network layer = 0.
    "I": b"\x04\x00",                  # Visible local player.
    "r": b"\x01",                      # Outside another player's house.
}


def slot_ids(values):
    # Repeated int32 must preserve zero and negative IDs (Unity instance IDs).
    return wire.blob(2, b"".join(wire.varint(key & ((1 << 64) - 1)) for key in values)) if values else b""


@dataclass
class LocalWorldSession:
    user_id: str
    transport_id: int
    layer: int = 0
    position: tuple | None = None
    sequence: int = 0
    teleported: bool = False
    movement_packets: int = 0
    animation_updates: int = 0
    variables: dict = field(default_factory=lambda: dict(INITIAL_VARIABLES))
    slots: dict = field(default_factory=dict)

    def set_runtime_variable(self, key, value):
        """True for an accepted, non-persistent world variable; False otherwise."""
        if key == "aaa" and valid_animation(value):
            self.variables[key] = value
            self.animation_updates += 1
            return True
        if key in BOOL_KEYS and value in (b"\x04\x00", b"\x04\x01"):
            self.variables[key] = value
            return True
        # No holdable items are granted by the current local inventory policy.
        if key == "he" and value == b"\x02\x00\x00\x00\x00":
            self.variables[key] = value
            return True
        return False

    def handle(self, name, payload):
        if name in ("C", "PL"):
            self.move(name, payload)
            # Client writes and remote-player snapshots have different layouts.
            # This isolated room has no other players to notify.
            return []
        if name == "slot_interaction":
            return self.slot_request(payload)
        return None

    def move(self, name, payload):
        codec = POSITION if name == "C" else LAYER
        if len(payload) != codec.size:
            raise wire.ProtocolError("Invalid world movement length")
        first, sequence, *position = codec.unpack(payload)
        if not all(math.isfinite(value) for value in position):
            raise wire.ProtocolError("Invalid world movement coordinates")
        if name == "C" and first not in (0, 1):
            raise wire.ProtocolError("Invalid teleport flag")
        if name == "PL" and first < 0:
            raise wire.ProtocolError("Invalid world layer")
        # TCP preserves order. The byte sequence may wrap from 255 to 0.
        if name == "PL":
            self.layer = first
            self.variables["A"] = b"\x02" + wire.I32.pack(first)
            LOG.info("TCP world layer updated layer=%d", first)
        else:
            self.teleported = bool(first)
        self.position, self.sequence = tuple(position), sequence
        self.movement_packets += 1
        if self.movement_packets == 1:
            LOG.info("TCP world position received; local avatar is sending state")

    def slot_request(self, payload):
        request = wire.Proto(payload)
        event_id, slot_id = request.integer(1), request.int32(2)
        # GetCache and CleanUserSlots carry the requesting UUID in field 3.
        # Occupy also carries a separate owner UUID in field 4.
        if request.text(3) not in ("", self.user_id) or request.text(4) not in ("", self.user_id):
            raise wire.ProtocolError("Invalid local slot owner")
        if event_id == 2:
            response = slot_ids(sorted(self.slots))
            response += b"".join(wire.string(3, self.slots[key]) for key in sorted(self.slots))
            LOG.info("TCP world interaction cache sent count=%d", len(self.slots))
            return [("n", response)]
        if event_id == 3:
            removed = sorted(self.slots)
            self.slots.clear()
            LOG.info("TCP world interaction slots cleared count=%d", len(removed))
            return [("n", wire.number(1, 2) + slot_ids(removed))] if removed else []
        if event_id not in (0, 1):
            return None
        if event_id == 1:
            self.slots.pop(slot_id, None)
            return [("n", wire.number(1, 2) + slot_ids([slot_id]))]
        if slot_id not in self.slots and len(self.slots) >= 256:
            raise wire.ProtocolError("Too many local interaction slots")
        self.slots[slot_id] = self.user_id
        # Occupation result (event 3) and cache update (event 1) are distinct.
        return [("n", wire.number(1, 3) + wire.number(2, True) + wire.string(3, self.user_id)),
                ("n", wire.number(1, 1) + wire.number(2, slot_id & ((1 << 64) - 1)) + wire.string(3, self.user_id))]
