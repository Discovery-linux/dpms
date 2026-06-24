from .dpms_callbacks import (
    PKG_INSTALL, PKG_REMOVE, PKG_UPGRADE,
    PKG_DOWNGRADE, PKG_REINSTALL,
)

PKG_DOWNGRADED = 11
PKG_OBSOLETE = 12
PKG_OBSOLETED = 13
PKG_UPGRADED = 14
PKG_REINSTALLED = 15

PKG_ERASE = PKG_REMOVE

PKG_CLEANUP = 101
PKG_VERIFY = 102
PKG_SCRIPTLET = 103

TRANS_PREPARATION = 201
TRANS_POST = 202

FORWARD_ACTIONS = [
    PKG_INSTALL, PKG_DOWNGRADE, PKG_OBSOLETE,
    PKG_UPGRADE, PKG_REINSTALL,
]

BACKWARD_ACTIONS = [
    PKG_DOWNGRADED, PKG_OBSOLETED, PKG_UPGRADED,
    PKG_REMOVE,
]

# TODO: merge this with the callbacks module maybe
ACTIONS = {
    PKG_DOWNGRADE: "Downgrading",
    PKG_DOWNGRADED: "Cleanup",
    PKG_INSTALL: "Installing",
    PKG_OBSOLETE: "Obsoleting",
    PKG_OBSOLETED: "Obsoleting",
    PKG_REINSTALL: "Reinstalling",
    PKG_REINSTALLED: "Cleanup",
    PKG_REMOVE: "Erasing",
    PKG_UPGRADE: "Upgrading",
    PKG_UPGRADED: "Cleanup",
    PKG_CLEANUP: "Cleanup",
    PKG_VERIFY: "Verifying",
    PKG_SCRIPTLET: "Running scriptlet",
    TRANS_PREPARATION: "Preparing",
    TRANS_POST: "Post-processing",
}

FILE_ACTIONS = {
    PKG_DOWNGRADE: "Downgrade",
    PKG_DOWNGRADED: "Downgraded",
    PKG_INSTALL: "Installed",
    PKG_OBSOLETE: "Obsolete",
    PKG_OBSOLETED: "Obsoleted",
    PKG_REINSTALL: "Reinstall",
    PKG_REINSTALLED: "Reinstalled",
    PKG_REMOVE: "Erase",
    PKG_UPGRADE: "Upgrade",
    PKG_UPGRADED: "Upgraded",
    PKG_CLEANUP: "Cleanup",
    PKG_VERIFY: "Verified",
    PKG_SCRIPTLET: "Running scriptlet",
    TRANS_PREPARATION: "Preparing",
    TRANS_POST: "Post-processing",
}
