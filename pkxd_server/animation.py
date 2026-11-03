"""Validation of the native `aaa` ByteListVariable (PlayerAnimationData)."""
import math
import struct

from . import wire

MAX_ANIMATION_BYTES = 4096


def valid_animation(value):
    # CommonTransformations.ToXDPlayerAnimationData dereferences all five
    # AnimationData objects. Present empty messages are valid; absent ones aren't.
    if not 1 < len(value) <= MAX_ANIMATION_BYTES + 1 or value[0] != 5:
        return False
    try:
        message = wire.Proto(value[1:])
        for field in range(1, 6):
            entries = message.repeated.get(field, [])
            if not entries:
                return False
            for kind, data in entries:
                if kind != 2:
                    return False
                state = wire.Proto(data)
                for key in (1, 2):  # signed Animator state hashes, protobuf int32.
                    if any(kind != 0 for kind, _ in state.repeated.get(key, [])):
                        return False
                for key in (3, 4):  # float32 progress and transition duration.
                    if any(kind != 5 or not math.isfinite(struct.unpack("<f", data)[0])
                           for kind, data in state.repeated.get(key, [])):
                        return False
        if any(kind != 0 or data not in (0, 1) for kind, data in message.repeated.get(6, [])):
            return False
        if any(kind != 0 for kind, _ in message.repeated.get(7, [])):
            return False
    except (wire.ProtocolError, struct.error):
        return False
    return True
