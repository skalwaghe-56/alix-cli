import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

from alix.models import Alias

HISTORY_FILE = Path.home() / ".alix" / "history.json"
MAX_HISTORY = 20


class HistoryManager:
    """Safe history manager for undo/redo of alias operations."""

    def __init__(self, path: Path = HISTORY_FILE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.undo: List[Dict[str, Any]] = []
        self.redo: List[Dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.undo = []
            self.redo = []
            return
        try:
            with open(self.path, "r") as fh:
                data = json.load(fh)
                self.undo = data.get("undo", []) or []
                self.redo = data.get("redo", []) or []
        except json.JSONDecodeError as e:
            # corrupted history file -> reset to empty stacks
            logging.warning(f"Corrupted history file, resetting: {e}")
            self.undo = []
            self.redo = []
        except OSError as e:
            logging.warning(f"Failed to load history file: {e}")
            self.undo = []
            self.redo = []

    def save(self) -> None:
        payload = {"undo": self.undo[-MAX_HISTORY:], "redo": self.redo[-MAX_HISTORY:]}
        try:
            with open(self.path, "w") as fh:
                json.dump(payload, fh, indent=2)
        except OSError as e:
            logging.warning(f"Failed to save history: {e}")
            pass

    def push(self, op: Dict[str, Any]) -> None:
        """Push new operation onto undo stack and clear redo."""
        if "type" not in op or "aliases" not in op:
            raise ValueError(f"Invalid operation: {op}")
        known_types = {
            "add", "remove", "edit", "import", "rename",
            "group_add", "group_remove", "group_delete",
            "tag_add", "tag_remove", "tag_rename", "tag_delete",
            "group_import", "remove_group"
        }
        if op["type"] not in known_types:
            raise ValueError(f"Unknown operation type: {op['type']}")
        if not isinstance(op["aliases"], list):
            raise ValueError(f"aliases must be a list: {op}")
        op = dict(op)
        op.setdefault("timestamp", datetime.now().isoformat())
        self.undo.append(op)
        # Trim undo to MAX_HISTORY
        if len(self.undo) > MAX_HISTORY:
            self.undo = self.undo[-MAX_HISTORY:]
        # Clear redo (new branch)
        self.redo = []
        self.save()

    def _format_message(self, action: str, op_type: str, count: int, total: int, skipped: int = 0) -> str:
        """Format user-friendly messages with emojis and proper grammar."""
        if skipped > 0:
            if action in ["Undid", "Redid"]:
                return f"{action} {op_type} ({count} of {total} aliases {'restored' if 'remove' in op_type else 'processed'}, {skipped} skipped)"
            else:
                return f"{action} {op_type} ({count} of {total} aliases {'restored' if 'remove' in op_type else 'processed'}, {skipped} skipped)"

        if count != total:
            return f"{action} {op_type} ({count} of {total} aliases {'restored' if 'remove' in op_type else 'processed'})"

        # Handle pluralization
        alias_word = "aliases" if count != 1 else "alias"
        if op_type == "remove_group":
            return f"{action} {op_type} ({count} {alias_word} restored)"
        elif op_type in ["add", "import"]:
            return f"{action} {op_type} ({count} {alias_word} {'added' if action == 'Redid' else 'removed'})"
        elif op_type == "edit":
            return f"{action} {op_type} ({count} {alias_word} {'updated' if action == 'Redid' else 'restored'})"
        elif op_type in ["group_add", "group_remove", "tag_add", "tag_remove", "tag_rename", "tag_delete", "group_import"]:
            return f"{action} {op_type} ({count} {alias_word} {'processed' if action == 'Redid' else 'processed'})"
        elif op_type == "rename":
            return f"{action} {op_type} ({count} {alias_word} {'renamed' if action == 'Redid' else 'renamed back'})"
        elif op_type == "group_delete":
            return f"{action} {op_type} ({count} {alias_word} {'reassigned' if action == 'Redid' else 'reassigned'})"
        else:
            return f"{action} {op_type} ({count} {alias_word} {'removed' if action == 'Redid' else 'restored'})"

    def _execute_undo_operation(self, storage, op: Dict[str, Any]) -> Tuple[str, int, int]:
        """Execute undo operation and return (message, performed_count, skipped_count)."""
        return self._execute_operation(storage, op, 'undo')

    def _execute_redo_operation(self, storage, op: Dict[str, Any]) -> Tuple[str, int, int]:
        """Execute redo operation and return (message, performed_count, skipped_count)."""
        return self._execute_operation(storage, op, 'redo')

    def _execute_operation(self, storage, op: Dict[str, Any], direction: str) -> Tuple[str, int, int]:
        """Execute undo or redo operation and return (message, performed_count, skipped_count)."""
        op_type = op.get("type")
        aliases = op.get("aliases", [])
        performed = 0
        skipped = 0

        if op_type == "add":
            if direction == 'undo':
                # inverse: remove by name
                p, s = self._for_each_name(aliases, lambda name: storage.remove(name, record_history=False))
            else:  # redo
                p, s = self._for_each_alias(aliases, lambda alias: storage.add(alias, record_history=False))
            performed += p
            skipped += s

        elif op_type in ("remove", "remove_group"):
            if direction == 'undo':
                # inverse: re-add aliases
                p, s = self._for_each_alias(aliases, lambda alias: storage.add(alias, record_history=False))
            else:  # redo
                p, s = self._for_each_name(aliases, lambda name: storage.remove(name, record_history=False))
            performed += p
            skipped += s

        elif op_type == "edit":
            # inverse: restore original aliases for undo, apply new for redo
            if direction == 'undo':
                original_aliases = op.get("aliases", [])
                p, s = self._for_each_alias(
                    original_aliases,
                    lambda alias: (storage.remove(alias.name, record_history=False), storage.add(alias, record_history=False))[1]
                )
            else:  # redo
                new_aliases = op.get("new_aliases", [])
                p, s = self._for_each_alias(
                    new_aliases,
                    lambda alias: (storage.remove(alias.name, record_history=False), storage.add(alias, record_history=False))[1]
                )
            performed += p
            skipped += s

        elif op_type == "import":
            if direction == 'undo':
                # inverse: remove all imported aliases
                p, s = self._for_each_name(aliases, lambda name: storage.remove(name, record_history=False))
            else:  # redo
                # redo: re-import all aliases
                p, s = self._for_each_alias(aliases, lambda alias: storage.add(alias, record_history=False))
            performed += p
            skipped += s

        elif op_type == "rename":
            if direction == 'undo':
                # inverse: rename back to old name
                old_name = op.get("old_name")
                new_name = op.get("new_name")
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: (storage.remove(new_name, record_history=False), setattr(alias, 'name', old_name), storage.add(alias, record_history=False), True)[-1]
                )
            else:  # redo
                # redo: rename to new name again
                old_name = op.get("old_name")
                new_name = op.get("new_name")
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: (storage.remove(old_name, record_history=False), setattr(alias, 'name', new_name), storage.add(alias, record_history=False), True)[-1]
                )
            performed += p
            skipped += s

        elif op_type == "group_add":
            if direction == 'undo':
                # inverse: remove alias from group
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: self._set_group(storage, alias, None)
                )
                storage.save()
            else:  # redo
                # redo: add alias back to group
                group_name = op.get("group_name")
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: self._set_group(storage, alias, group_name)
                )
                storage.save()
            performed += p
            skipped += s

        elif op_type == "group_remove":
            if direction == 'undo':
                # inverse: add alias back to group
                group_name = op.get("group_name")
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: self._set_group(storage, alias, group_name)
                )
                storage.save()
            else:  # redo
                # redo: remove alias from group again
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: self._set_group(storage, alias, None)
                )
                storage.save()
            performed += p
            skipped += s

        elif op_type == "group_delete":
            if direction == 'undo':
                # inverse: restore group assignments
                group_name = op.get("group_name")
                restore_group = group_name
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: self._set_group(storage, alias, restore_group)
                )
                storage.save()
            else:  # redo
                # redo: delete group again (restore original group assignments)
                reassign_to = op.get("reassign_to")
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: self._set_group(storage, alias, reassign_to)
                )
                storage.save()
            performed += p
            skipped += s

        elif op_type == "tag_add":
            if direction == 'undo':
                # inverse: remove added tags
                added_tags = op.get("added_tags", [])
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: (self._remove_tags(alias, added_tags), storage.aliases.__setitem__(alias.name, alias), True)[-1]
                )
                storage.save()
            else:  # redo
                # redo: add tags back
                added_tags = op.get("added_tags", [])
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: (self._add_tags(alias, added_tags), storage.aliases.__setitem__(alias.name, alias), True)[-1]
                )
                storage.save()
            performed += p
            skipped += s

        elif op_type == "tag_remove":
            if direction == 'undo':
                # inverse: restore removed tags
                removed_tags = op.get("removed_tags", [])
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: (self._add_tags(alias, removed_tags), storage.aliases.__setitem__(alias.name, alias), True)[-1]
                )
                storage.save()
            else:  # redo
                # redo: remove tags again
                removed_tags = op.get("removed_tags", [])
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: (self._remove_tags(alias, removed_tags), storage.aliases.__setitem__(alias.name, alias), True)[-1]
                )
                storage.save()
            performed += p
            skipped += s

        elif op_type == "tag_rename":
            if direction == 'undo':
                # inverse: rename back to old tag
                old_tag = op.get("old_tag")
                new_tag = op.get("new_tag")
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: new_tag in alias.tags and (setattr(alias, 'tags', [old_tag if tag == new_tag else tag for tag in alias.tags]), storage.aliases.__setitem__(alias.name, alias), True)[-1]
                )
                storage.save()
            else:  # redo
                # redo: rename to new tag again
                old_tag = op.get("old_tag")
                new_tag = op.get("new_tag")
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: old_tag in alias.tags and (setattr(alias, 'tags', [new_tag if tag == old_tag else tag for tag in alias.tags]), storage.aliases.__setitem__(alias.name, alias), True)[-1]
                )
                storage.save()
            performed += p
            skipped += s

        elif op_type == "tag_delete":
            if direction == 'undo':
                # inverse: restore deleted tag
                deleted_tag = op.get("deleted_tag")
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: (self._add_tags(alias, [deleted_tag]), storage.aliases.__setitem__(alias.name, alias), True)[-1]
                )
                storage.save()
            else:  # redo
                # redo: delete tag again
                deleted_tag = op.get("deleted_tag")
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: (self._remove_tags(alias, [deleted_tag]), storage.aliases.__setitem__(alias.name, alias), True)[-1]
                )
                storage.save()
            performed += p
            skipped += s

        elif op_type == "group_import":
            if direction == 'undo':
                # inverse: remove imported aliases from group
                group_name = op.get("group_name")
                storage.create_backup()
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: self._set_group(storage, alias, None) if alias.group == group_name else True
                )
                storage.save()
            else:  # redo
                # redo: restore aliases to imported group
                group_name = op.get("group_name")
                p, s = self._for_each_alias(
                    aliases,
                    lambda alias: self._set_group(storage, alias, group_name)
                )
                storage.save()
            performed += p
            skipped += s

        action = "Undid" if direction == 'undo' else "Redid"
        return self._format_message(action, op_type, performed, len(aliases), skipped), performed, skipped

    def list_undo(self) -> List[Dict[str, Any]]:
        return list(self.undo)

    def list_redo(self) -> List[Dict[str, Any]]:
        return list(self.redo)

    def _load_alias(self, data: Dict[str, Any]) -> Alias:
        try:
            return Alias.from_dict(data)
        except Exception:
            # If invalid alias data, raise so caller can skip
            raise

    def _for_each_alias(self, aliases, fn):
        performed = 0
        skipped = 0
        for a in aliases:
            try:
                alias_obj = self._load_alias(a)
                if fn(alias_obj):
                    performed += 1
            except Exception:
                skipped += 1
        return performed, skipped

    def _for_each_name(self, aliases, fn):
        performed = 0
        skipped = 0
        for a in aliases:
            name = a.get("name")
            if not name:
                skipped += 1
                continue
            try:
                if fn(name):
                    performed += 1
            except Exception:
                skipped += 1
        return performed, skipped

    def _set_group(self, storage, alias, group):
        alias.group = group
        storage.aliases[alias.name] = alias
        return True

    def _add_tags(self, alias, tags):
        for tag in tags:
            if tag not in alias.tags:
                alias.tags.append(tag)
        return True

    def _remove_tags(self, alias, tags):
        for tag in tags:
            if tag in alias.tags:
                alias.tags.remove(tag)
        return True

    def perform_undo(self, storage) -> str:
        """Undo last op. storage must implement add(alias, record_history=False) and remove(name, record_history=False)."""
        if not self.undo:
            return "⚠️  Nothing to undo – history is empty."

        op = self.undo.pop()
        message, performed, skipped = self._execute_undo_operation(storage, op)

        # Add to redo stack and trim
        self.redo.append(op)
        if len(self.redo) > MAX_HISTORY:
            self.redo = self.redo[-MAX_HISTORY:]
        self.save()

        return f"✅ {message}"

    def perform_redo(self, storage) -> str:
        """Redo last undone op. storage must implement add(alias, record_history=False) and remove(name, record_history=False)."""
        if not self.redo:
            return "⚠️  Nothing to redo – already at the latest state."

        op = self.redo.pop()
        message, performed, skipped = self._execute_redo_operation(storage, op)

        # Add to undo stack and trim
        self.undo.append(op)
        if len(self.undo) > MAX_HISTORY:
            self.undo = self.undo[-MAX_HISTORY:]
        self.save()

        return f"🔁 {message}"

    def perform_undo_by_id(self, storage, operation_id: int) -> str:
        """Undo a specific operation by its index (1-based, most recent first)."""
        if operation_id < 1 or operation_id > len(self.undo):
            return f"❌ Invalid operation ID: {operation_id}. Valid range: 1-{len(self.undo)}"

        # Get the operation (undo list is in chronological order, most recent last)
        # So index 1 is the most recent (last item), index len(undo) is the oldest (first item)
        op_index = len(self.undo) - operation_id
        op = self.undo[op_index]

        # Remove the operation from undo stack
        del self.undo[op_index]

        # Execute the undo operation
        message, performed, skipped = self._execute_undo_operation(storage, op)

        # Add to redo stack and trim
        self.redo.append(op)
        if len(self.redo) > MAX_HISTORY:
            self.redo = self.redo[-MAX_HISTORY:]
        self.save()

        return f"✅ {message}"

    def perform_redo_by_id(self, storage, operation_id: int) -> str:
        """Redo a specific operation by its index (1-based, most recent first)."""
        if operation_id < 1 or operation_id > len(self.redo):
            return f"❌ Invalid operation ID: {operation_id}. Valid range: 1-{len(self.redo)}"

        # Get the operation (redo list is in chronological order, most recent last)
        op_index = len(self.redo) - operation_id
        op = self.redo[op_index]

        # Remove the operation from redo stack
        del self.redo[op_index]

        # Execute the redo operation
        message, performed, skipped = self._execute_redo_operation(storage, op)

        # Add to undo stack and trim
        self.undo.append(op)
        if len(self.undo) > MAX_HISTORY:
            self.undo = self.undo[-MAX_HISTORY:]
        self.save()

        return f"🔁 {message}"
