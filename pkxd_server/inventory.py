"""Authenticated local backpack favorites, including the initial empty query."""
import logging

from . import wire
from .accounts import AccountError

LOG = logging.getLogger(__name__)


def favorites_response(favorites):
    # FavoriteBackpackItemResponse.ResultOneofCase.Success must be present.
    # A fresh account requires the bytes 08 02 12 00, not just EventId=2.
    success = b"".join(wire.number(1, item_id) for item_id in favorites)
    return wire.number(1, 2) + wire.blob(2, success)


class InventoryServices:
    def __init__(self, store):
        self.store = store

    def backpack(self, payload, *, player_id):
        request = wire.Proto(payload)
        event_id = request.integer(1)
        if event_id != 2:
            LOG.info("TCP unsupported backpack operation id=%d", event_id)
            return None
        added, removed = request.integers(2, limit=256), request.integers(3, limit=256)
        try:
            favorites = self.store.update_favorites(player_id, added, removed)
        except AccountError as error:
            # Failure is a different oneof submessage, with ErrorMessage=1.
            LOG.info("TCP backpack favorites rejected reason=%s", error.code)
            return wire.number(1, 2) + wire.blob(3, wire.string(1, str(error)))
        LOG.info("TCP backpack favorites sent count=%d", len(favorites))
        return favorites_response(favorites)
