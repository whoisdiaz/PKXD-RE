"""Read-only startup contracts recovered from the supplied 1.38.4 native code.

Store trees describe the currently empty local catalog. They do not grant items,
provide the original production catalog, or implement purchases.
"""
import logging
import time

from . import wire

LOG = logging.getLogger(__name__)

# StoreTreeConstants, TypeDefIndex 5096. Versions belong to individual stores.
STORE_IDS = (
    "avatar-store-0_2_49", "houses-store-0_2_05", "home-store-0_2_49",
    "pets-store-0_1_56", "pets-inventory-0_2_47", "eggs-store-0_1_86",
    "services-store-0_1_56", "social-network-store-0_2_49", "lootbox-store-0_1_57",
    "gesture-store-0_2_47", "holdables-store-0_2_44", "vehicles-store-0_2_43",
    "batteries-store-0_2_21", "presents-store-0_1_89", "vehicle-parts-store-0_1_95",
    "ugc-activities-store-0_2_24", "ugc-builder-in-game-store-0_2_48", "outfit-store-0_2_49",
)
PET_STORE_ID = "eggs-store-0_1_86"
CATALOG_VERSION = "local-bootstrap-1"
REQUESTS = frozenset(("time", "store_tree", "pet_store_tree", "friends", "pet",
                      "npc/fetch-owned", "game_variable", "Analytics/sessionId", "Analytics/deviceId",
                      "hair_style", "lb", "init_day_night", "init_pos", "fetch_events"))


def empty_tree(store_id):
    # A present StoreTreeData object is required even when there are no products.
    # Omitting it causes OnStoreTreeServerEvent to dereference a null StoreTree.
    return (wire.string(1, store_id) + wire.string(2, CATALOG_VERSION)
            + wire.string(3, "pk-xd"))


def store_response(store_id, *, pet=False):
    known = store_id == PET_STORE_ID if pet else store_id in STORE_IDS
    message = wire.number(1, known)
    if not known:
        message += wire.string(2, "Unknown local store ID.")
    # GetPetStoreTreeResponse has EventId at 3 and StoreTree at 4.
    # GetStoreTreeResponse has StoreTree at 3 and no EventId field.
    message += wire.blob(4 if pet else 3, empty_tree(store_id))
    return message, known


class StartupServices:
    def handle(self, name, payload, *, user_id, transport_id):
        """Return [(response event name, protobuf bytes)] or None if unsupported.

        Call only after successful game login and room join. An empty list is a
        one-way request; a list containing b'' is an actual empty protobuf reply.
        """
        if name not in REQUESTS:
            return None
        if name in ("Analytics/sessionId", "Analytics/deviceId"):
            # Client sends raw IDs here, not protobuf. No telemetry is forwarded
            # or retained by this local server, and the client expects no reply.
            if len(payload) > 128:
                raise wire.ProtocolError("Invalid analytics ID length")
            return []

        request = wire.Proto(payload)
        event_id = request.integer(1)
        if name == "time" and event_id == 0:
            # CurrentTimeResponse.ctor calls DateTimeOffset.FromUnixTimeSeconds.
            LOG.info("TCP server time sent (Unix seconds)")
            return [("time", wire.number(2, int(time.time())))]
        if name == "hair_style" and event_id == 0:
            LOG.info("TCP initial hair style inventory sent count=0")
            return [("get_hair_styles", wire.number(1, True))]
        if name == "lb" and event_id == 0:
            # LootBoxInfoResponseMessage.Successful is field 3, not field 1.
            LOG.info("TCP initial loot box catalog sent count=0")
            return [("lb", wire.number(3, True))]
        if name == "init_day_night" and not request.fields:
            # DayNightStateResponse: day=false (default), SkipInterpolation=2.
            LOG.info("TCP initial day/night state sent night=false")
            return [("G", wire.number(2, True))]
        if name == "init_pos" and not request.fields:
            # OnPlayerPositionUpdate inflates an RFC1951 stream then loops over
            # remote states. There are no other players in the isolated room.
            LOG.info("TCP initial remote positions sent count=0")
            return [("C", b"\x03\x00")]
        if name == "fetch_events" and not request.fields:
            # This fan-out request has no dedicated acknowledgement in the
            # client. No active quest/world events are configured locally.
            LOG.info("TCP active world events: none configured")
            return []
        if name in ("store_tree", "pet_store_tree"):
            if name == "store_tree" and event_id == 1:
                ids = request.texts(2)
                known = all(store_id in STORE_IDS for store_id in ids)
                response = wire.number(1, known)
                if not known:
                    response += wire.string(2, "Unknown local store ID.")
                LOG.info("TCP store ID check sent count=%d successful=%s", len(ids), known)
                return [("L2", response)]
            if event_id == 0:
                store_id = request.text(2)
                if not 1 <= len(store_id) <= 96:
                    raise wire.ProtocolError("Invalid store ID length")
                response, known = store_response(store_id, pet=name == "pet_store_tree")
                # Only known fixed identifiers enter the log, never arbitrary input.
                LOG.info("TCP store tree sent id=%s items=0 successful=%s",
                         store_id if known else "unknown", known)
                return [("PST" if name == "pet_store_tree" else "L", response)]
        elif name == "friends" and event_id == 0:
            # FriendInformationResponse: Successful=1, three empty friend lists.
            LOG.info("TCP initial friends list sent count=0")
            return [("get_friends_result", wire.number(1, True))]
        elif name == "npc/fetch-owned":
            # FetchAllOwnedNpcRequest has no fields; do not reinterpret an event ID.
            if request.fields:
                raise wire.ProtocolError("Invalid owned NPC request")
            LOG.info("TCP initial owned NPC list sent count=0")
            return [("npc/fetch-owned", b"")]
        elif name == "game_variable" and event_id == 3:
            # Owner=-1 is encoded as a ten-byte protobuf varint by C# int32.
            if request.int32(2) not in (-1, 0, transport_id):
                raise wire.ProtocolError("Unsupported variable cache owner")
            LOG.info("TCP initial world variable cache sent count=0")
            return [("q", b"")]
        elif name == "pet":
            # There are no pet-creation/purchase operations in this local stage.
            if event_id == 0:  # List -> GetPetsResponse: event=8, successful=2.
                request.text(2)  # Optional StoreTreeVersion.
                reply = wire.number(1, 8) + wire.number(2, True)
            elif event_id == 6:  # GetCache -> GetPetsCacheResponse.
                reply = wire.number(1, 7)
            elif event_id == 16:  # GetPetNeedsRequest -> PetNeedDataResponse.
                if request.text(2) not in ("", user_id):
                    LOG.info("TCP unsupported remote pet needs lookup")
                    return None
                reply = wire.number(1, 21)
            elif event_id == 19:  # Get details for the owned pets (empty).
                reply = wire.number(1, 24)
            elif event_id == 24:  # Get details for the owned eggs (empty).
                reply = wire.number(1, 32)
            elif event_id == 28:  # GetAllRemotePetsRequest -> response event 36.
                ids = request.texts(2)
                if any(value != user_id for value in ids):
                    LOG.info("TCP unsupported remote pet lookup")
                    return None
                reply = wire.number(1, 36)
            else:
                LOG.info("TCP unsupported pet operation id=%d", event_id)
                return None
            LOG.info("TCP initial pet list/cache sent count=0 requestId=%d", event_id)
            return [("pet", reply)]
        LOG.info("TCP unsupported startup operation name=%s id=%d", name, event_id)
        return None
