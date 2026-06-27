#!/usr/bin/env python3
"""Operator script for shared-book storage cutover and rollback.

This script reads and modifies the aggregate settings that control the
cutover state machine:

    legacy -> shadow mode -> read-only preview -> full dual-write -> legacy-off

Commands:
    status                  Show current cutover contract and settings.
    shadow                  Enable shared-book writes, keep API on legacy reads.
    preview [book_ids...]   Enable shared reads for specific books (or all if none listed).
    full                    Enable shared reads globally while keeping dual-write.
    legacy-off              Stop legacy writes; shared storage becomes write source of truth.
    rollback                Revert to legacy mode (only safe before legacy-off).

Run from repo root:
    python backend/scripts/operate_shared_book_cutover.py status
    python backend/scripts/operate_shared_book_cutover.py shadow
    python backend/scripts/operate_shared_book_cutover.py preview book-1 book-2
    python backend/scripts/operate_shared_book_cutover.py full
    python backend/scripts/operate_shared_book_cutover.py legacy-off
    python backend/scripts/operate_shared_book_cutover.py rollback
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DB_PATH
from app.services.aggregate_settings import (
    AggregateSettingsRepository,
    shared_book_storage_contract,
)
from app.storage.db import initialize_database


ROLLBACK_TRIGGERS = [
    "critical data loss or corruption detected",
    "AI costs exceed budget unexpectedly",
    "scheduler deadlock or lock storm",
    "source-map refresh causing widespread failures",
    "shared-book files corrupted and unrepairable",
]


def _load_repository() -> AggregateSettingsRepository:
    initialize_database(DB_PATH)
    return AggregateSettingsRepository()


def _current_settings() -> dict:
    return _load_repository().content_workflow()


def _save_settings(settings: dict) -> None:
    _load_repository().save_settings({"contentWorkflow": settings})


def _print_contract(contract: dict) -> None:
    print(json.dumps(contract, ensure_ascii=False, indent=2))


def cmd_status() -> int:
    settings = _current_settings()
    contract = shared_book_storage_contract(settings)
    print("# Current shared-book cutover contract")
    _print_contract(contract)
    print("\n# Raw settings")
    print(f"  useSharedBookStorage: {settings.get('useSharedBookStorage', False)}")
    print(f"  sharedBookStorageReadMode: {settings.get('sharedBookStorageReadMode', 'legacy')}")
    print(f"  sharedBookStorageDualWrite: {settings.get('sharedBookStorageDualWrite', False)}")
    print(f"  sharedBookCutoverBookIds: {settings.get('sharedBookCutoverBookIds', [])}")
    print("\n# Rollback triggers")
    for trigger in ROLLBACK_TRIGGERS:
        print(f"  - {trigger}")
    return 0


def cmd_shadow() -> int:
    settings = _current_settings()
    contract = shared_book_storage_contract(settings)
    if contract["useSharedBookStorage"] and contract["readMode"] == "dual_verify" and contract["dualWrite"]:
        print("Already in shadow mode.")
        return 0
    settings["useSharedBookStorage"] = True
    settings["sharedBookStorageReadMode"] = "dual_verify"
    settings["sharedBookStorageDualWrite"] = True
    settings.setdefault("sharedBookCutoverBookIds", [])
    _save_settings(settings)
    print("Switched to shadow mode: shared-book writes enabled, API reads legacy + compares both paths.")
    print("Run 'status' for full contract details.")
    return 0


def cmd_preview(book_ids: list[str]) -> int:
    settings = _current_settings()
    contract = shared_book_storage_contract(settings)
    if not contract["useSharedBookStorage"]:
        print("ERROR: must enter shadow mode before preview.")
        return 1
    if not contract["dualWrite"]:
        print("ERROR: cannot preview after legacy-off; rollback first if needed.")
        return 1
    settings["sharedBookStorageReadMode"] = "shared"
    settings["sharedBookCutoverBookIds"] = list(book_ids) if book_ids else []
    _save_settings(settings)
    if book_ids:
        print(f"Switched to read-only preview for books: {book_ids}")
    else:
        print("Switched to read-only preview for all books.")
    print("Run 'status' for full contract details.")
    return 0


def cmd_full() -> int:
    settings = _current_settings()
    contract = shared_book_storage_contract(settings)
    if not contract["useSharedBookStorage"]:
        print("ERROR: must enter shadow or preview mode before full dual-write.")
        return 1
    if not contract["dualWrite"]:
        print("ERROR: cannot enable full shared reads after legacy-off; rollback first if needed.")
        return 1
    settings["sharedBookStorageReadMode"] = "shared"
    settings["sharedBookCutoverBookIds"] = []
    _save_settings(settings)
    print("Switched to full dual-write: all eligible books read from shared storage; legacy still written.")
    print("Run 'status' for full contract details.")
    return 0


def cmd_legacy_off() -> int:
    settings = _current_settings()
    contract = shared_book_storage_contract(settings)
    if not contract["useSharedBookStorage"]:
        print("ERROR: must enable shared storage before legacy-off.")
        return 1
    if contract["readMode"] != "shared":
        print("ERROR: must be in shared read mode before legacy-off.")
        return 1
    confirm = input("This disables legacy writes and is the point of no guaranteed rollback. Type 'legacy-off' to confirm: ")
    if confirm.strip() != "legacy-off":
        print("Aborted.")
        return 1
    settings["sharedBookStorageDualWrite"] = False
    _save_settings(settings)
    print("Legacy writes disabled. Shared storage is now the write source of truth.")
    print("Run 'status' for full contract details.")
    return 0


def cmd_rollback() -> int:
    settings = _current_settings()
    contract = shared_book_storage_contract(settings)
    if not contract["rollbackToLegacyAvailable"]:
        print("ERROR: rollback to legacy is no longer guaranteed after legacy-off.")
        print("       Investigate shared-book files manually before attempting forced rollback.")
        return 1
    settings["useSharedBookStorage"] = False
    settings["sharedBookStorageReadMode"] = "legacy"
    settings["sharedBookStorageDualWrite"] = False
    settings["sharedBookCutoverBookIds"] = []
    _save_settings(settings)
    print("Rolled back to legacy mode. API reads legacy data; shared-book writes stopped.")
    print("Run 'status' for full contract details.")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    command = sys.argv[1].lower().replace("_", "-")
    args = sys.argv[2:]

    handlers = {
        "status": cmd_status,
        "shadow": cmd_shadow,
        "preview": lambda: cmd_preview(args),
        "full": cmd_full,
        "legacy-off": cmd_legacy_off,
        "rollback": cmd_rollback,
    }

    handler = handlers.get(command)
    if handler is None:
        print(f"Unknown command: {command}")
        print(__doc__)
        return 2

    return handler()


if __name__ == "__main__":
    sys.exit(main())
