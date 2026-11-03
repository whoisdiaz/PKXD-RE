"""Recovered ToxicBird framing and the protobuf subset used by account/profile messages."""
import struct

MAX_FRAME = 256 * 1024
I32 = struct.Struct(">i")
PING, PONG, CONNECT, RECONNECT, EVENT, JOIN, LEAVE, ROOM_EVENT = range(1, 9)


class ProtocolError(ValueError):
    pass


def exact(sock, size):
    result = bytearray()
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise EOFError
        result.extend(chunk)
    return bytes(result)


def receive(sock):
    size = I32.unpack(exact(sock, 4))[0]
    if not 1 <= size <= MAX_FRAME:
        raise ProtocolError("Invalid frame length")
    return exact(sock, size)


def frame(payload):
    if not 1 <= len(payload) <= MAX_FRAME:
        raise ProtocolError("Invalid frame length")
    return I32.pack(len(payload)) + payload


def event(name, payload=b"", *, room=False):
    name = name.encode("ascii")
    if not 1 <= len(name) <= 255:
        raise ProtocolError("Invalid event name length")
    return bytes((ROOM_EVENT if room else EVENT, len(name))) + name + payload


def parse_event(packet):
    if len(packet) < 2 or not 1 <= packet[1] <= len(packet) - 2:
        raise ProtocolError("Invalid event envelope")
    end = 2 + packet[1]
    try:
        return packet[2:end].decode("ascii"), packet[end:]
    except UnicodeDecodeError as error:
        raise ProtocolError("Non-ASCII event name") from error


def varint(value):
    if not 0 <= value < 1 << 64:
        raise ProtocolError("Varint is outside uint64")
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _read_varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ProtocolError("Truncated varint")
        part = data[offset]
        offset += 1
        if shift == 63 and part > 1:
            raise ProtocolError("Varint overflow")
        value |= (part & 127) << shift
        if part < 128:
            return value, offset
    raise ProtocolError("Invalid varint")


def number(field, value):
    return varint(field << 3) + varint(int(value)) if value else b""


def string(field, value):
    encoded = value.encode("utf-8")
    return varint(field << 3 | 2) + varint(len(encoded)) + encoded if encoded else b""


def blob(field, value):
    """Encode a present submessage/bytes field, including an empty message."""
    return varint(field << 3 | 2) + varint(len(value)) + value


class Proto:
    def __init__(self, data):
        self.fields = {}
        self.repeated = {}
        offset = 0
        while offset < len(data):
            tag, offset = _read_varint(data, offset)
            field, wire = tag >> 3, tag & 7
            if not 1 <= field < 1 << 29:
                raise ProtocolError("Invalid protobuf field")
            if wire == 0:
                value, offset = _read_varint(data, offset)
            elif wire in (1, 2, 5):
                if wire == 2:
                    size, offset = _read_varint(data, offset)
                else:
                    size = 8 if wire == 1 else 4
                if size > len(data) - offset:
                    raise ProtocolError("Truncated protobuf value")
                value, offset = data[offset:offset + size], offset + size
            else:
                raise ProtocolError("Unsupported protobuf wire type")
            self.fields[field] = (wire, value)
            self.repeated.setdefault(field, []).append((wire, value))

    def integer(self, field, default=0):
        wire, value = self.fields.get(field, (0, default))
        if wire != 0:
            raise ProtocolError("Expected protobuf integer")
        return value

    def int32(self, field, default=0):
        value = self.integer(field, default) & 0xffffffff
        return value - (1 << 32) if value & 0x80000000 else value

    def text(self, field, default=""):
        wire, value = self.fields.get(field, (2, default.encode()))
        if wire != 2:
            raise ProtocolError("Expected protobuf string")
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProtocolError("Invalid protobuf UTF-8") from error

    def message(self, field):
        wire, value = self.fields.get(field, (2, b""))
        if wire != 2:
            raise ProtocolError("Expected protobuf submessage")
        return Proto(value)

    def integers(self, field, limit=32):
        result = []
        for wire, value in self.repeated.get(field, []):
            if wire == 0:
                result.append(value)
            elif wire == 2:
                offset = 0
                while offset < len(value):
                    item, offset = _read_varint(value, offset)
                    result.append(item)
                    if len(result) > limit:
                        raise ProtocolError("Too many repeated integers")
            else:
                raise ProtocolError("Expected repeated protobuf integer")
            if len(result) > limit:
                raise ProtocolError("Too many repeated integers")
        return result

    def texts(self, field, limit=64):
        values = self.repeated.get(field, [])
        if len(values) > limit:
            raise ProtocolError("Too many repeated strings")
        result = []
        for wire, value in values:
            if wire != 2:
                raise ProtocolError("Expected repeated protobuf string")
            try:
                result.append(value.decode("utf-8"))
            except UnicodeDecodeError as error:
                raise ProtocolError("Invalid protobuf UTF-8") from error
        return result


def variable(player_id, key, typed_value):
    encoded = key.encode("ascii")
    return I32.pack(player_id) + I32.pack(len(encoded)) + encoded + typed_value


def client_variable_update(key, typed_value):
    """Client -> server omits player ID; the authenticated connection owns it."""
    encoded = key.encode("ascii")
    return I32.pack(len(encoded)) + encoded + typed_value


def parse_client_variable_update(data):
    if len(data) < 6:
        raise ProtocolError("Truncated client variable update")
    size = I32.unpack_from(data)[0]
    if not 1 <= size <= 64 or 4 + size >= len(data):
        raise ProtocolError("Invalid client variable key length")
    try:
        key = data[4:4 + size].decode("ascii")
    except UnicodeDecodeError as error:
        raise ProtocolError("Invalid client variable key") from error
    if any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise ProtocolError("Invalid client variable key")
    return key, data[4 + size:]


def parse_variable(data):
    if len(data) < 10:
        raise ProtocolError("Truncated user variable")
    player_id, size = struct.unpack_from(">ii", data)
    if not 1 <= size <= 64 or 8 + size >= len(data):
        raise ProtocolError("Invalid user variable key length")
    try:
        key = data[8:8 + size].decode("ascii")
    except UnicodeDecodeError as error:
        raise ProtocolError("Invalid user variable key") from error
    return player_id, key, data[8 + size:]
