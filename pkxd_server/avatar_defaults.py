"""AvatarUtils defaults from the supplied 1.38.4 binary, not a production grant.

AvatarUtils..cctor RVA 0x2EC9CD4 maps these ItemSlot positions. Base body parts
13/15 are AvatarUtils.UpperBodyPartBase/LowerBodyPartBase constants.
The local starter policy owns one of each default item; it is not a recovered
new-account inventory from the official backend.
"""
SEED_VERSION = "native-avatar-defaults-v1"
DEFAULT_ITEMS_BY_SLOT = {
    4: 4636,  # AnimSet
    5: 16,    # Head
    6: 5,     # HeadFace
    7: 13,    # UpperBody base part
    8: 272,   # UpperBodyMaterial
    9: 15,    # LowerBody base part
    10: 273,  # LowerBodyMaterial
    11: 17,   # RightHand
    12: 17,   # LeftHand (same paired item)
    13: 59,   # RightFoot
    14: 59,   # LeftFoot (same paired item)
}
DEFAULT_EQUIPPED_ITEMS = tuple(DEFAULT_ITEMS_BY_SLOT.get(slot, 0) for slot in range(18))
STARTER_ITEM_IDS = tuple(sorted(set(DEFAULT_ITEMS_BY_SLOT.values())))
