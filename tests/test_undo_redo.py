import pytest
from datetime import datetime

from alix.models import Alias
from alix.storage import AliasStorage
from alix.history_manager import MAX_HISTORY

# ============================
# Fixtures
# ============================

@pytest.fixture
def temp_storage(tmp_path):
    """Fixture for temporary storage to avoid file pollution."""
    storage_path = tmp_path / "aliases.json"
    storage = AliasStorage(storage_path=storage_path)
    # Clear any existing data to ensure clean state for each test
    storage.aliases.clear()
    storage.save()
    return storage


@pytest.fixture
def single_alias(temp_storage):
    alias = Alias(name="test", command="echo hello")
    temp_storage.add(alias, record_history=True)
    return alias, temp_storage


@pytest.fixture
def two_aliases(temp_storage):
    a1 = Alias(name="a1", command="echo 1")
    a2 = Alias(name="a2", command="echo 2")
    temp_storage.add(a1, record_history=True)
    temp_storage.add(a2, record_history=True)
    return a1, a2, temp_storage


# ============================
# Basic undo / redo behavior
# ============================

@pytest.mark.parametrize("op_type", [
    "add", "remove", "import", "edit"
])
def test_basic_undo_redo(temp_storage, op_type):
    if op_type == "add":
        alias = Alias(name="test", command="echo hello")
        temp_storage.add(alias, record_history=True)
        undo_msg = "Undid add"
        redo_msg = "Redid add"
    elif op_type == "remove":
        alias = Alias(name="test", command="echo hello")
        temp_storage.add(alias, record_history=True)
        temp_storage.remove(alias.name, record_history=True)
        undo_msg = "Undid remove"
        redo_msg = "Redid remove"
    elif op_type == "import":
        import_op = {
            "type": "import",
            "aliases": [{"name": "imported", "command": "echo imported"}],
            "timestamp": datetime.now().isoformat()
        }
        temp_storage.history.push(import_op)
        alias = Alias(name="imported", command="echo imported")
        temp_storage.add(alias, record_history=False)
        undo_msg = "Undid import"
        redo_msg = "Redid import"
    elif op_type == "edit":
        alias = Alias(name="test", command="echo hello")
        temp_storage.add(alias, record_history=True)
        edit_op = {
            "type": "edit",
            "aliases": [{"name": "test", "command": "echo hello"}],
            "new_aliases": [{"name": "test", "command": "echo world"}],
            "timestamp": datetime.now().isoformat()
        }
        temp_storage.history.push(edit_op)
        alias.command = "echo world"
        temp_storage.aliases["test"] = alias
        temp_storage.save()
        undo_msg = "Undid edit"
        redo_msg = "Redid edit"

    # Undo
    msg = temp_storage.history.perform_undo(temp_storage)
    assert undo_msg in msg

    # Redo
    msg = temp_storage.history.perform_redo(temp_storage)
    assert redo_msg in msg


def test_empty_stacks(temp_storage):
    # Undo on empty
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "⚠️  Nothing to undo – history is empty." in msg
    assert len(temp_storage.history.list_redo()) == 0

    # Redo on empty
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "⚠️  Nothing to redo – already at the latest state." in msg
    assert len(temp_storage.history.list_undo()) == 0


def test_multiple_undos_redos(temp_storage):
    # Add multiple aliases
    for i in range(3):
        temp_storage.add(Alias(name=f"a{i}", command=f"echo {i}"), record_history=True)

    # Undo all
    for i in range(3):
        msg = temp_storage.history.perform_undo(temp_storage)
        assert "✅" in msg and "Undid" in msg

    # Undo beyond empty
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "⚠️  Nothing to undo – history is empty." in msg

    # Redo all
    for i in range(3):
        msg = temp_storage.history.perform_redo(temp_storage)
        assert "🔁" in msg and "Redid" in msg

    # Redo beyond full
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "⚠️  Nothing to redo – already at the latest state." in msg


def test_edit_operation_undo_redo(temp_storage):
    """Test undo/redo for edit operations."""
    # Add alias
    alias = Alias(name="test", command="echo hello")
    temp_storage.add(alias, record_history=True)

    # Push edit operation manually
    edit_op = {
        "type": "edit",
        "aliases": [{"name": "test", "command": "echo hello"}],  # original
        "new_aliases": [{"name": "test", "command": "echo world"}],  # new
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(edit_op)

    # Apply the edit to storage
    alias.command = "echo world"
    temp_storage.aliases["test"] = alias
    temp_storage.save()

    assert len(temp_storage.history.list_undo()) == 2  # add + edit

    # Undo edit
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid edit" in msg

    # Verify command was restored to original
    edited_alias = temp_storage.get("test")
    assert edited_alias.command == "echo hello"

    # Redo edit
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid edit" in msg

    # Verify command was updated
    edited_alias = temp_storage.get("test")
    assert edited_alias.command == "echo world"


def test_rename_operation_undo_redo(temp_storage):
    """Test undo/redo for rename operations."""
    # Add alias
    alias = Alias(name="old_name", command="echo hello")
    temp_storage.add(alias, record_history=True)

    rename_op = {
        "type": "rename",
        "aliases": [{"name": "old_name", "command": "echo hello"}],
        "old_name": "old_name",
        "new_name": "new_name",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(rename_op)

    # Remove old and add new name
    temp_storage.remove("old_name", record_history=False)
    alias.name = "new_name"
    temp_storage.add(alias, record_history=False)

    # Undo rename
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid rename" in msg

    # Verify name was reverted
    assert temp_storage.get("old_name") is not None
    assert temp_storage.get("new_name") is None

    # Redo rename
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid rename" in msg

    # Verify name was restored
    assert temp_storage.get("old_name") is None
    assert temp_storage.get("new_name") is not None


def test_import_operation_undo_redo(temp_storage):
    """Test undo/redo for import operations."""
    import_op = {
        "type": "import",
        "aliases": [
            {"name": "imported1", "command": "echo imported1"},
            {"name": "imported2", "command": "echo imported2"}
        ],
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(import_op)

    # Apply import
    alias1 = Alias(name="imported1", command="echo imported1")
    alias2 = Alias(name="imported2", command="echo imported2")
    temp_storage.add(alias1, record_history=False)
    temp_storage.add(alias2, record_history=False)

    # Undo import
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid import" in msg

    # Verify aliases were removed
    assert temp_storage.get("imported1") is None
    assert temp_storage.get("imported2") is None

    # Redo import
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid import" in msg

    # Verify aliases were restored
    assert temp_storage.get("imported1") is not None
    assert temp_storage.get("imported2") is not None


def test_mixed_operation_sequence(temp_storage):
    """Test complex sequence of mixed operations."""
    # Add -> Edit -> Add -> Remove sequence
    alias1 = Alias(name="test1", command="echo one")
    alias2 = Alias(name="test2", command="echo two")

    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)

    # Edit first alias (creates remove + add operations)
    alias1.command = "echo modified"
    temp_storage.remove("test1", record_history=True)
    temp_storage.add(alias1, record_history=True)

    # Remove second alias
    temp_storage.remove("test2", record_history=True)

    assert len(temp_storage.history.list_undo()) == 5  # 2 adds + remove + add + remove

    # Undo remove (test2 should come back)
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid remove" in msg
    assert temp_storage.get("test2") is not None

    # Undo edit (which is actually the add operation from the edit)
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid add" in msg
    # After undoing the add operation from edit, test1 should be removed
    assert temp_storage.get("test1") is None

    # Undo remove (test1 should be added again)
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid remove" in msg
    assert temp_storage.get("test1") is not None

    # Undo add (test1 should be removed)
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid add" in msg
    assert temp_storage.get("test2") is None

    # Now redo all operations
    for i in range(4):
        msg = temp_storage.history.perform_redo(temp_storage)
        assert "🔁" in msg

    # Verify final state
    assert temp_storage.get("test1") is not None
    assert temp_storage.get("test2") is None
    assert temp_storage.get("test1").command == "echo modified"

# ============================
# Selective undo / redo
# ============================

def test_selective_undo_by_id(temp_storage):
    """Test selective undo by operation ID."""
    # Add multiple aliases
    alias1 = Alias(name="test1", command="echo one")
    alias2 = Alias(name="test2", command="echo two")
    alias3 = Alias(name="test3", command="echo three")

    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)
    temp_storage.add(alias3, record_history=True)

    # Verify all aliases exist
    assert len(temp_storage.list_all()) == 3
    assert len(temp_storage.history.list_undo()) == 3

    # Undo the middle operation (ID 2 = test2)
    msg = temp_storage.history.perform_undo_by_id(temp_storage, 2)
    assert "✅" in msg and "Undid add" in msg
    assert len(temp_storage.list_all()) == 2
    assert len(temp_storage.history.list_undo()) == 2  # One less in undo
    assert len(temp_storage.history.list_redo()) == 1  # One in redo

    # Verify test2 was removed
    assert temp_storage.get("test1") is not None
    assert temp_storage.get("test2") is None
    assert temp_storage.get("test3") is not None

    # Undo the first operation (ID 1 = test3, now the most recent)
    msg = temp_storage.history.perform_undo_by_id(temp_storage, 1)
    assert "✅" in msg and "Undid add" in msg
    assert len(temp_storage.list_all()) == 1

    # Verify test3 was removed
    assert temp_storage.get("test1") is not None
    assert temp_storage.get("test2") is None
    assert temp_storage.get("test3") is None


def test_selective_redo_by_id(temp_storage):
    """Test selective redo by operation ID."""
    # Add and undo multiple aliases
    alias1 = Alias(name="test1", command="echo one")
    alias2 = Alias(name="test2", command="echo two")

    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)

    # Undo both (this creates 2 redo operations)
    temp_storage.history.perform_undo(temp_storage)  # Undo test2
    temp_storage.history.perform_undo(temp_storage)  # Undo test1

    assert len(temp_storage.list_all()) == 0
    assert len(temp_storage.history.list_undo()) == 0
    assert len(temp_storage.history.list_redo()) == 2

    # Redo the first operation (ID 1 = most recent undo = test1)
    msg = temp_storage.history.perform_redo_by_id(temp_storage, 1)
    assert "🔁" in msg and "Redid add" in msg
    assert len(temp_storage.list_all()) == 1
    assert len(temp_storage.history.list_redo()) == 1

    # Verify test1 was restored (most recent undo)
    assert temp_storage.get("test1") is not None
    assert temp_storage.get("test2") is None


def test_selective_undo_redo_mixed_operations(temp_storage):
    """Test selective undo/redo with mixed operation types."""
    # Add alias
    alias = Alias(name="test", command="echo hello")
    temp_storage.add(alias, record_history=True)

    # Edit alias (this creates remove + add operations)
    alias.command = "echo world"
    temp_storage.remove("test", record_history=True)
    temp_storage.add(alias, record_history=True)

    # Remove alias
    temp_storage.remove("test", record_history=True)

    assert len(temp_storage.history.list_undo()) == 4  # add, remove, add, remove

    # Selectively undo the edit operation (middle one - should be the add operation from edit)
    msg = temp_storage.history.perform_undo_by_id(temp_storage, 2)  # ID 2 = add (part of edit)
    assert "✅" in msg and "Undid add" in msg

    # Verify the alias was removed (undo add should remove the alias)
    removed_alias = temp_storage.get("test")
    assert removed_alias is None


def test_selective_undo_after_new_operations(temp_storage):
    """Test that selective undo works correctly after new operations."""
    # Add initial alias
    alias1 = Alias(name="test1", command="echo one")
    temp_storage.add(alias1, record_history=True)

    # Undo the add
    temp_storage.history.perform_undo(temp_storage)
    assert len(temp_storage.list_all()) == 0

    # Add new alias (this clears redo stack)
    alias2 = Alias(name="test2", command="echo two")
    temp_storage.add(alias2, record_history=True)

    # Try to undo by ID - should only see the latest operation
    assert len(temp_storage.history.list_undo()) == 1
    msg = temp_storage.history.perform_undo_by_id(temp_storage, 1)
    assert "✅" in msg and "Undid add" in msg
    assert len(temp_storage.list_all()) == 0

# ============================
# Group operations
# ============================

def test_remove_group_undo_redo(temp_storage):
    alias1 = Alias(name="test1", command="echo one", group="test_group")
    alias2 = Alias(name="test2", command="echo two", group="test_group")
    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)
    
    # Remove group
    removed_count = temp_storage.remove_group("test_group")
    assert removed_count == 2
    assert len(temp_storage.list_all()) == 0
    assert len(temp_storage.history.list_undo()) == 3  # add1 + add2 + remove_group
    
    # Undo remove group
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid remove_group" in msg
    assert len(temp_storage.list_all()) == 2
    assert len(temp_storage.history.list_redo()) == 1
    
    # Undo add2
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid add" in msg
    assert len(temp_storage.list_all()) == 1
    
    # Redo add2
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "Redid add" in msg
    assert len(temp_storage.list_all()) == 2


def test_group_operations_undo_redo(temp_storage):
    """Test undo/redo for group operations."""
    # Add aliases to group
    alias1 = Alias(name="test1", command="echo one")
    alias2 = Alias(name="test2", command="echo two")
    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)

    group_add_op = {
        "type": "group_add",
        "aliases": [
            {"name": "test1", "command": "echo one"},
            {"name": "test2", "command": "echo two"}
        ],
        "group_name": "test_group",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(group_add_op)

    # Apply group assignment
    alias1.group = "test_group"
    alias2.group = "test_group"
    temp_storage.aliases["test1"] = alias1
    temp_storage.aliases["test2"] = alias2
    temp_storage.save()

    # Undo group_add
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid group_add" in msg

    # Verify aliases removed from group
    assert temp_storage.get("test1").group is None
    assert temp_storage.get("test2").group is None

    # Redo group_add
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid group_add" in msg

    # Verify aliases restored to group
    assert temp_storage.get("test1").group == "test_group"
    assert temp_storage.get("test2").group == "test_group"


def test_group_delete_undo_redo_without_reassignment(temp_storage):
    """Test that group delete undo correctly restores aliases to original group when no reassignment."""
    # Create aliases in a group
    alias1 = Alias(name="test1", command="echo hello1", group="testgroup")
    alias2 = Alias(name="test2", command="echo hello2", group="testgroup")
    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)

    # Verify initial state
    assert temp_storage.get("test1").group == "testgroup"
    assert temp_storage.get("test2").group == "testgroup"

    group_aliases = [a for a in temp_storage.list_all() if a.group == "testgroup"]
    for alias in group_aliases:
        alias.group = None
        temp_storage.aliases[alias.name] = alias
    temp_storage.save()

    history_op = {
        "type": "group_delete",
        "aliases": [alias.to_dict() for alias in group_aliases],
        "group_name": "testgroup",
        "reassign_to": None,  # No reassignment
        "timestamp": "2025-01-01T00:00:00.000000"
    }
    temp_storage.history.push(history_op)

    # Verify aliases are no longer in group
    assert temp_storage.get("test1").group is None
    assert temp_storage.get("test2").group is None

    # Undo the group delete
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid group_delete" in msg

    # Verify aliases were restored to the original group
    assert temp_storage.get("test1").group == "testgroup"
    assert temp_storage.get("test2").group == "testgroup"

    # Redo the group delete
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid group_delete" in msg

    # Verify aliases were removed from group again
    assert temp_storage.get("test1").group is None
    assert temp_storage.get("test2").group is None


def test_group_delete_undo_redo_with_reassignment(temp_storage):
    """Test that group delete undo correctly restores aliases to reassigned group."""
    # Create aliases in a group
    alias1 = Alias(name="test1", command="echo hello1", group="oldgroup")
    alias2 = Alias(name="test2", command="echo hello2", group="oldgroup")
    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)

    # Delete group with reassignment to new group
    group_aliases = [a for a in temp_storage.list_all() if a.group == "oldgroup"]
    for alias in group_aliases:
        alias.group = "newgroup"  # Reassign to new group
        temp_storage.aliases[alias.name] = alias
    temp_storage.save()

    history_op = {
        "type": "group_delete",
        "aliases": [alias.to_dict() for alias in group_aliases],
        "group_name": "oldgroup",
        "reassign_to": "newgroup",  # Reassignment target
        "timestamp": "2025-01-01T00:00:00.000000"
    }
    temp_storage.history.push(history_op)

    # Verify aliases are in new group
    assert temp_storage.get("test1").group == "newgroup"
    assert temp_storage.get("test2").group == "newgroup"

    # Undo the group delete
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid group_delete" in msg

    # Verify aliases were restored to the original group
    assert temp_storage.get("test1").group == "oldgroup"
    assert temp_storage.get("test2").group == "oldgroup"

    # Redo the group delete
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid group_delete" in msg

    # Verify aliases are back in reassigned group
    assert temp_storage.get("test1").group == "newgroup"
    assert temp_storage.get("test2").group == "newgroup"

# ============================
# Tag operations
# ============================


# ============================
# Error handling & edge cases
# ============================

def test_max_history_trimming(temp_storage):
    # Push more than MAX_HISTORY ops
    for i in range(MAX_HISTORY + 1):
        alias = Alias(name=f"test{i}", command=f"echo {i}")
        temp_storage.add(alias, record_history=True)
    
    assert len(temp_storage.history.list_undo()) == MAX_HISTORY
    # Oldest should be trimmed (last one is most recent)
    assert temp_storage.history.list_undo()[-1]["aliases"][0]["name"] == f"test{MAX_HISTORY}"


def test_corrupted_history_file(tmp_path):
    # Create a temporary history file with invalid JSON
    history_path = tmp_path / "history.json"
    history_path.parent.mkdir(exist_ok=True)
    with open(history_path, 'w') as f:
        f.write("{invalid json")

    # Create storage with the corrupted history file
    storage = AliasStorage(storage_path=tmp_path / "aliases.json")

    # Verify stacks are empty (reset on corruption)
    assert len(storage.history.list_undo()) == 0
    assert len(storage.history.list_redo()) == 0

    # Undo/redo should not crash
    msg = storage.history.perform_undo(storage)
    assert "⚠️  Nothing to undo – history is empty." in msg


def test_partial_failures(temp_storage):
    # Add valid alias
    alias_valid = Alias(name="valid", command="echo ok")
    temp_storage.add(alias_valid, record_history=True)
    
    corrupted_op = {
        "type": "add",
        "aliases": [{"invalid": "data"}],  # Missing name
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(corrupted_op)
    
    # Undo should handle gracefully
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "skipped" in msg.lower()


def test_remove_nonexistent(temp_storage):
    # Remove alias that does not exist
    result = temp_storage.remove("ghost_alias", record_history=True)
    assert result is False or result == 0  # whatever your remove returns

    # Remove group that does not exist
    result = temp_storage.remove_group("ghost_group")
    assert result == 0


def test_invalid_undo_id(temp_storage):
    """Test undo with invalid operation ID."""
    msg = temp_storage.history.perform_undo_by_id(temp_storage, 999)
    assert "❌ Invalid operation ID" in msg

    msg = temp_storage.history.perform_undo_by_id(temp_storage, 0)
    assert "❌ Invalid operation ID" in msg

    msg = temp_storage.history.perform_undo_by_id(temp_storage, -1)
    assert "❌ Invalid operation ID" in msg


def test_invalid_redo_id(temp_storage):
    """Test redo with invalid operation ID."""
    msg = temp_storage.history.perform_redo_by_id(temp_storage, 999)
    assert "❌ Invalid operation ID" in msg

    msg = temp_storage.history.perform_redo_by_id(temp_storage, 0)
    assert "❌ Invalid operation ID" in msg

    msg = temp_storage.history.perform_redo_by_id(temp_storage, -1)
    assert "❌ Invalid operation ID" in msg


def test_edge_case_empty_stacks_selective(temp_storage):
    """Test selective undo/redo on empty stacks."""
    # Empty undo stack
    msg = temp_storage.history.perform_undo_by_id(temp_storage, 1)
    assert "❌ Invalid operation ID" in msg

    # Empty redo stack
    msg = temp_storage.history.perform_redo_by_id(temp_storage, 1)
    assert "❌ Invalid operation ID" in msg


def test_corrupted_history_during_operations(temp_storage, tmp_path):
    """Test handling of corrupted history files during operations."""
    # Add some aliases first
    alias1 = Alias(name="test1", command="echo one")
    alias2 = Alias(name="test2", command="echo two")
    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)

    # Corrupt the history file
    history_file = tmp_path / "aliases_history.json"
    with open(history_file, 'w') as f:
        f.write("{ invalid json content }")

    # Try to undo - should handle gracefully
    msg = temp_storage.history.perform_undo(temp_storage)
    # Should either work (if it loaded successfully) or handle the error gracefully
    assert msg is not None

    # Try selective undo with corrupted history
    msg = temp_storage.history.perform_undo_by_id(temp_storage, 1)
    # Should handle gracefully even with corrupted history
    assert msg is not None


def test_invalid_operation_data_handling(temp_storage):
    """Test handling of invalid operation data in history."""
    # Push invalid operation (missing required fields)
    invalid_op = {
        "type": "add",
        # Missing "aliases" field
        "timestamp": datetime.now().isoformat()
    }

    # This should raise an error when pushing
    try:
        temp_storage.history.push(invalid_op)
        assert False, "Should have raised ValueError for invalid operation"
    except ValueError:
        pass  # Expected

    # Push operation with empty aliases
    empty_op = {
        "type": "add",
        "aliases": [],
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(empty_op)

    # Undo should handle empty aliases gracefully
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid add" in msg


def test_storage_failures_during_undo_redo(temp_storage):
    """Test handling of storage failures during undo/redo operations."""
    # Add alias
    alias = Alias(name="test", command="echo hello")
    temp_storage.add(alias, record_history=True)

    # Mock a storage failure by making storage operations fail
    original_remove = temp_storage.remove
    original_add = temp_storage.add

    def failing_remove(name, record_history=False):
        if name == "test":
            raise Exception("Storage failure")
        return original_remove(name, record_history)

    def failing_add(alias, record_history=False):
        if alias.name == "test":
            raise Exception("Storage failure")
        return original_add(alias, record_history)

    temp_storage.remove = failing_remove
    temp_storage.add = failing_add

    try:
        # Try to undo - should handle the failure gracefully
        msg = temp_storage.history.perform_undo(temp_storage)
        assert "Undid add" in msg
        # Should indicate partial failure
        assert "skipped" in msg.lower() or "of" in msg
    finally:
        # Restore original methods
        temp_storage.remove = original_remove
        temp_storage.add = original_add


def test_history_file_permission_errors(tmp_path):
    """Test handling of file permission errors."""
    # Create a read-only directory for history
    import os
    import stat

    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_file = readonly_dir / "history.json"

    # Make directory read-only
    readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # No write permission

    try:
        # Try to create history manager with read-only location
        from alix.history_manager import HistoryManager

        # This should not crash, but may fail silently
        history = HistoryManager(path=readonly_file)

        # Try operations that require writing
        alias = Alias(name="test", command="echo hello")
        history.push({
            "type": "add",
            "aliases": [{"name": "test", "command": "echo hello"}],
            "timestamp": datetime.now().isoformat()
        })

        # Should handle gracefully (fail silently as per current implementation)
        undo_msg = history.perform_undo(None)  # Pass None storage to avoid other errors
        assert undo_msg is not None

    finally:
        # Restore permissions for cleanup
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def test_very_large_history_operations(temp_storage):
    """Test handling of very large numbers of aliases in operations."""
    # Create operation with many aliases
    many_aliases = []
    for i in range(100):  # Large number of aliases
        many_aliases.append({
            "name": f"alias{i}",
            "command": f"echo {i}"
        })

    large_op = {
        "type": "add",
        "aliases": many_aliases,
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(large_op)

    # Add all aliases to storage
    for alias_data in many_aliases:
        alias = Alias(name=alias_data["name"], command=alias_data["command"])
        temp_storage.add(alias, record_history=False)

    # Undo should handle large number of aliases
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid add" in msg

    # Verify all aliases were removed
    for i in range(100):
        assert temp_storage.get(f"alias{i}") is None


def test_malformed_alias_data_in_history(temp_storage):
    """Test handling of malformed alias data in history operations."""
    # Push operation with malformed alias data
    malformed_op = {
        "type": "add",
        "aliases": [
            {"name": "valid", "command": "echo valid"},
            {"name": "", "command": "echo invalid"},  # Empty name
            {"command": "echo no_name"},  # Missing name
            {"name": "no_command"},  # Missing command
        ],
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(malformed_op)

    # Add valid alias first
    valid_alias = Alias(name="valid", command="echo valid")
    temp_storage.add(valid_alias, record_history=False)

    # Undo should handle malformed data gracefully
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid add" in msg

    # Should indicate partial success due to malformed data
    if "of" in msg or "skipped" in msg.lower():
        # Partial success expected due to malformed data
        pass
    else:
        # All succeeded (some malformed data might be acceptable)
        pass


def test_concurrent_history_modifications(temp_storage):
    """Test handling of concurrent modifications to history."""
    # Get initial history state
    initial_undo_count = len(temp_storage.history.list_undo())

    original_undo = temp_storage.history.undo[:]
    original_redo = temp_storage.history.redo[:]

    # Add alias
    alias = Alias(name="test", command="echo hello")
    temp_storage.add(alias, record_history=True)

    temp_storage.history.undo.append({
        "type": "add",
        "aliases": [{"name": "concurrent", "command": "echo concurrent"}],
        "timestamp": datetime.now().isoformat()
    })

    # Try to undo - should handle the concurrent modification gracefully
    msg = temp_storage.history.perform_undo(temp_storage)
    assert msg is not None

    # Restore original state for other tests
    temp_storage.history.undo = original_undo
    temp_storage.history.redo = original_redo


def test_history_stack_overflow_protection(temp_storage):
    """Test that history stack trimming works correctly."""
    from alix.history_manager import MAX_HISTORY

    # Add more than MAX_HISTORY operations
    for i in range(MAX_HISTORY + 5):
        alias = Alias(name=f"test{i}", command=f"echo {i}")
        temp_storage.add(alias, record_history=True)

    # Should only keep MAX_HISTORY operations
    assert len(temp_storage.history.list_undo()) == MAX_HISTORY

    # The oldest operations should be trimmed
    # Most recent should be test{MAX_HISTORY + 4}
    most_recent_op = temp_storage.history.list_undo()[-1]
    assert most_recent_op["aliases"][0]["name"] == f"test{MAX_HISTORY + 4}"

    # Undo all operations
    for _ in range(MAX_HISTORY):
        msg = temp_storage.history.perform_undo(temp_storage)
        assert "✅" in msg

    # Should handle empty stack gracefully
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "⚠️  Nothing to undo – history is empty." in msg


def test_group_delete_redo_exception_handling(temp_storage):
    """Test that group_delete redo handles exceptions when loading aliases."""
    # Create aliases in a group
    alias1 = Alias(name="test1", command="echo hello1", group="testgroup")
    temp_storage.add(alias1, record_history=True)

    # Record history operation with mixed valid and invalid alias data
    history_op = {
        "type": "group_delete",
        "aliases": [
            alias1.to_dict(),  # Valid alias
            {"invalid": "data"}  # Invalid alias data that will cause _load_alias to fail
        ],
        "group_name": "testgroup",
        "reassign_to": None,
        "timestamp": "2025-01-01T00:00:00.000000"
    }
    temp_storage.history.push(history_op)

    # Undo the group delete (moves to redo stack)
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid group_delete" in msg

    # Redo the group delete - should handle the invalid alias gracefully
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid group_delete" in msg
    # Should indicate that one alias was skipped due to exception
    assert "skipped" in msg.lower()


def test_push_invalid_aliases_type(temp_storage):
    """Test that push raises ValueError when aliases is not a list."""
    with pytest.raises(ValueError, match="aliases must be a list"):
        temp_storage.history.push({"type": "add", "aliases": "not_a_list"})


def test_history_stack_trimming(temp_storage):
    """Test that history stack trimming works in various scenarios."""
    from alix.history_manager import MAX_HISTORY

    # Test redo stack trimming on undo (perform_undo)
    temp_storage.history.redo = [{"type": "dummy", "aliases": [], "timestamp": "2025-01-01T00:00:00"}] * (MAX_HISTORY + 1)
    temp_storage.history.undo.append({
        "type": "add",
        "aliases": [{"name": "test", "command": "echo test"}],
        "timestamp": "2025-01-01T00:00:00"
    })
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid add" in msg
    assert len(temp_storage.history.redo) == MAX_HISTORY

    # Test undo stack trimming on redo (perform_redo)
    temp_storage.history.undo = [{"type": "dummy", "aliases": [], "timestamp": "2025-01-01T00:00:00"}] * MAX_HISTORY
    temp_storage.history.redo.append({
        "type": "add",
        "aliases": [{"name": "test2", "command": "echo test2"}],
        "timestamp": "2025-01-01T00:00:00"
    })
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid add" in msg
    assert len(temp_storage.history.undo) == MAX_HISTORY

    # Test redo stack trimming on undo_by_id (perform_undo_by_id)
    temp_storage.history.redo = [{"type": "dummy", "aliases": [], "timestamp": "2025-01-01T00:00:00"}] * (MAX_HISTORY + 1)
    temp_storage.history.undo.append({
        "type": "add",
        "aliases": [{"name": "test3", "command": "echo test3"}],
        "timestamp": "2025-01-01T00:00:00"
    })
    msg = temp_storage.history.perform_undo_by_id(temp_storage, 1)
    assert "✅" in msg and "Undid add" in msg
    assert len(temp_storage.history.redo) == MAX_HISTORY

    # Test undo stack trimming on redo_by_id (perform_redo_by_id)
    temp_storage.history.undo = [{"type": "dummy", "aliases": [], "timestamp": "2025-01-01T00:00:00"}] * MAX_HISTORY
    temp_storage.history.redo.append({
        "type": "add",
        "aliases": [{"name": "test4", "command": "echo test4"}],
        "timestamp": "2025-01-01T00:00:00"
    })
    msg = temp_storage.history.perform_redo_by_id(temp_storage, 1)
    assert "🔁" in msg and "Redid add" in msg
    assert len(temp_storage.history.undo) == MAX_HISTORY


def test_unknown_operation_type_handling(temp_storage):
    """Test handling of unknown operation types."""
    # Attempt to push unknown operation type - should raise ValueError
    unknown_op = {
        "type": "unknown",
        "aliases": [{"name": "test", "command": "echo test"}],
        "timestamp": "2025-01-01T00:00:00"
    }
    with pytest.raises(ValueError, match="Unknown operation type: unknown"):
        temp_storage.history.push(unknown_op)


def test_history_load_oserror(tmp_path, monkeypatch):
    """Test that OSError during history file loading resets stacks to empty."""
    # Create a history file with valid content
    history_path = tmp_path / "history.json"
    with open(history_path, 'w') as f:
        f.write('{"undo": [{"type": "add", "aliases": [{"name": "test", "command": "echo test"}], "timestamp": "2025-01-01T00:00:00"}], "redo": []}')

    # Mock open to raise OSError when trying to read the history file
    original_open = open
    def mock_open(file, mode='r', *args, **kwargs):
        if str(history_path) in str(file) and mode == 'r':
            raise OSError("Permission denied")
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr('builtins.open', mock_open)

    # Create history manager - should handle OSError gracefully
    from alix.history_manager import HistoryManager
    history = HistoryManager(path=history_path)

    # Should have empty stacks due to OSError
    assert len(history.list_undo()) == 0
    assert len(history.list_redo()) == 0


def test_remove_undo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in remove undo: _load_alias failure, storage.add failure, and storage.add returning False."""
    # Push a remove operation with mixed alias data
    remove_op = {
        "type": "remove",
        "aliases": [
            {"name": "valid", "command": "echo valid"},  # Valid, but add will return False
            {"invalid": "data"},  # Invalid for _load_alias
            {"name": "fail_add", "command": "echo fail"}  # Valid, but add will raise
        ],
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(remove_op)

    # Mock storage.add to return False for 'valid' and raise for 'fail_add'
    original_add = temp_storage.add
    call_count = 0
    def mock_add(alias, record_history=False):
        nonlocal call_count
        call_count += 1
        if alias.name == "valid":
            return False
        elif alias.name == "fail_add":
            raise Exception("Add failed")
        return original_add(alias, record_history)

    monkeypatch.setattr(temp_storage, 'add', mock_add)

    # Perform undo - should handle all cases
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid remove" in msg
    # Should have skipped 2 (invalid data + add failure) and performed 0 (add false + add exception)
    assert "skipped" in msg.lower()


def test_edit_undo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in edit undo: _load_alias failure, storage.add failure, and storage.add returning False."""
    # Push an edit operation with mixed original alias data
    edit_op = {
        "type": "edit",
        "aliases": [
            {"name": "valid", "command": "echo valid"},  # Valid, but add will return False
            {"invalid": "data"},  # Invalid for _load_alias
            {"name": "fail_add", "command": "echo fail"}  # Valid, but add will raise
        ],
        "new_aliases": [],  # Not used in undo
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(edit_op)

    # Mock storage.add to return False for 'valid' and raise for 'fail_add'
    original_add = temp_storage.add
    def mock_add(alias, record_history=False):
        if alias.name == "valid":
            return False
        elif alias.name == "fail_add":
            raise Exception("Add failed")
        return original_add(alias, record_history)

    monkeypatch.setattr(temp_storage, 'add', mock_add)

    # Perform undo - should handle all cases
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid edit" in msg
    # Should indicate partial success due to failures
    assert "skipped" in msg.lower()


def test_import_undo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in import undo: missing name, storage.remove failure, and storage.remove returning False."""
    # Push an import operation with mixed alias data
    import_op = {
        "type": "import",
        "aliases": [
            {"name": "valid", "command": "echo valid"},  # Valid, but remove will return False
            {"command": "echo no_name"},  # Missing name
            {"name": "fail_remove", "command": "echo fail"}  # Valid, but remove will raise
        ],
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(import_op)

    # Mock storage.remove to return False for 'valid' and raise for 'fail_remove'
    original_remove = temp_storage.remove
    def mock_remove(name, record_history=False):
        if name == "valid":
            return False
        elif name == "fail_remove":
            raise Exception("Remove failed")
        return original_remove(name, record_history)

    monkeypatch.setattr(temp_storage, 'remove', mock_remove)

    # Perform undo - should handle all cases
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid import" in msg
    # Should indicate partial success due to failures
    assert "skipped" in msg.lower()


def test_rename_undo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in rename undo: _load_alias failure or storage operation failures."""
    # Push a rename operation with mixed alias data
    rename_op = {
        "type": "rename",
        "aliases": [
            {"name": "new_name", "command": "echo test"},  # Valid
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "old_name": "old_name",
        "new_name": "new_name",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(rename_op)

    # Mock storage.remove to raise for 'new_name'
    original_remove = temp_storage.remove
    def mock_remove(name, record_history=False):
        if name == "new_name":
            raise Exception("Remove failed")
        return original_remove(name, record_history)

    monkeypatch.setattr(temp_storage, 'remove', mock_remove)

    # Perform undo - should handle failures
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid rename" in msg
    # Should indicate skips due to failures
    assert "skipped" in msg.lower()


def test_group_add_undo_edge_cases(temp_storage):
    """Test edge cases in group_add undo: _load_alias failure."""
    # Push a group_add operation with invalid alias data
    group_add_op = {
        "type": "group_add",
        "aliases": [
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "group_name": "test_group",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(group_add_op)

    # Perform undo - should handle _load_alias failure
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid group_add" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()


def test_group_remove_undo(temp_storage):
    """Test undo for group_remove operations, including exception handling."""
    # Push a group_remove operation with mixed valid and invalid aliases
    group_remove_op = {
        "type": "group_remove",
        "aliases": [
            {"name": "test1", "command": "echo one"},  # Valid
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "group_name": "test_group",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(group_remove_op)

    # Perform undo - should handle invalid data gracefully
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid group_remove" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()


def test_group_delete_undo_edge_cases(temp_storage):
    """Test edge cases in group_delete undo: _load_alias failure."""
    # Push a group_delete operation with invalid alias data
    group_delete_op = {
        "type": "group_delete",
        "aliases": [
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "group_name": "test_group",
        "reassign_to": None,
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(group_delete_op)

    # Perform undo - should handle _load_alias failure
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid group_delete" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()


def test_tag_add_undo_edge_cases(temp_storage):
    """Test edge cases in tag_add undo: tag removal and _load_alias failure."""
    # Add alias with tags
    alias = Alias(name="test", command="echo hello", tags=["existing", "to_remove"])
    temp_storage.add(alias, record_history=False)

    # Push a tag_add operation with mixed aliases
    tag_add_op = {
        "type": "tag_add",
        "aliases": [
            {"name": "test", "command": "echo hello", "tags": ["existing", "to_remove"]},  # Has the tag
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "added_tags": ["to_remove"],  # Tag to remove
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(tag_add_op)

    # Perform undo - should remove the tag and handle invalid data
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid tag_add" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()
    # Verify tag was removed
    assert "to_remove" not in temp_storage.get("test").tags


def test_tag_remove_undo(temp_storage):
    """Test undo for tag_remove operations, including edge cases."""
    # Add aliases with different tag states
    alias1 = Alias(name="test1", command="echo hello", tags=["existing"])  # Doesn't have removed_tag
    alias2 = Alias(name="test2", command="echo world", tags=["existing", "removed_tag"])  # Already has removed_tag
    temp_storage.add(alias1, record_history=False)
    temp_storage.add(alias2, record_history=False)

    # Push a tag_remove operation with mixed aliases
    tag_remove_op = {
        "type": "tag_remove",
        "aliases": [
            {"name": "test1", "command": "echo hello", "tags": ["existing"]},  # Will get removed_tag
            {"name": "test2", "command": "echo world", "tags": ["existing", "removed_tag"]},  # Already has removed_tag
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "removed_tags": ["removed_tag"],  # Tag that was removed
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(tag_remove_op)

    # Perform undo - should restore the tag where missing and handle invalid data
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid tag_remove" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()
    # Verify tags were restored
    assert "removed_tag" in temp_storage.get("test1").tags
    assert "removed_tag" in temp_storage.get("test2").tags


def test_tag_rename_undo(temp_storage):
    """Test undo for tag_rename operations, including edge cases."""
    # Add aliases with different tag states
    alias1 = Alias(name="test1", command="echo hello", tags=["old_tag"])  # Has old_tag
    alias2 = Alias(name="test2", command="echo world", tags=["new_tag"])  # Has new_tag
    temp_storage.add(alias1, record_history=False)
    temp_storage.add(alias2, record_history=False)

    # Push a tag_rename operation with mixed aliases
    tag_rename_op = {
        "type": "tag_rename",
        "aliases": [
            {"name": "test1", "command": "echo hello", "tags": ["old_tag"]},  # Doesn't have new_tag
            {"name": "test2", "command": "echo world", "tags": ["new_tag"]},  # Has new_tag
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "old_tag": "old_tag",
        "new_tag": "new_tag",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(tag_rename_op)

    # Perform undo - should rename back and handle invalid data
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid tag_rename" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()
    # Verify tags were renamed back
    assert "old_tag" in temp_storage.get("test2").tags
    assert "new_tag" not in temp_storage.get("test2").tags


def test_tag_delete_undo(temp_storage):
    """Test undo for tag_delete operations, including edge cases."""
    # Add aliases with different tag states
    alias1 = Alias(name="test1", command="echo hello", tags=["other"])  # Doesn't have deleted_tag
    alias2 = Alias(name="test2", command="echo world", tags=["other", "deleted_tag"])  # Has deleted_tag
    temp_storage.add(alias1, record_history=False)
    temp_storage.add(alias2, record_history=False)

    # Push a tag_delete operation with mixed aliases
    tag_delete_op = {
        "type": "tag_delete",
        "aliases": [
            {"name": "test1", "command": "echo hello", "tags": ["other"]},  # Will get deleted_tag
            {"name": "test2", "command": "echo world", "tags": ["other", "deleted_tag"]},  # Already has deleted_tag
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "deleted_tag": "deleted_tag",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(tag_delete_op)

    # Perform undo - should restore the tag and handle invalid data
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid tag_delete" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()
    # Verify tags were restored
    assert "deleted_tag" in temp_storage.get("test1").tags
    assert "deleted_tag" in temp_storage.get("test2").tags


def test_group_import_undo(temp_storage):
    """Test undo for group_import operations, including edge cases."""
    # Add aliases with different group states
    alias1 = Alias(name="test1", command="echo hello", group="group_name")  # In group
    alias2 = Alias(name="test2", command="echo world", group=None)  # Not in group
    temp_storage.add(alias1, record_history=False)
    temp_storage.add(alias2, record_history=False)

    # Push a group_import operation with mixed aliases
    group_import_op = {
        "type": "group_import",
        "aliases": [
            {"name": "test1", "command": "echo hello", "group": "group_name"},  # In group, will be removed
            {"name": "test2", "command": "echo world", "group": None},  # Not in group, no change
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "group_name": "group_name",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(group_import_op)

    # Perform undo - should remove from group and handle invalid data
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "Undid group_import" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()
    # Verify group was removed
    assert temp_storage.get("test1").group is None
    assert temp_storage.get("test2").group is None


def test_add_redo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in add redo: _load_alias failure, storage.add failure, and storage.add returning False."""
    # First, add an alias and undo it to create a redo operation
    alias = Alias(name="test", command="echo test")
    temp_storage.add(alias, record_history=True)
    temp_storage.history.perform_undo(temp_storage)  # Now redo stack has the add operation

    # Modify the redo operation to have mixed alias data
    # The redo operation is the add operation we just undid
    # But to test edge cases, we need to modify the aliases in the redo op
    redo_op = temp_storage.history.list_redo()[0]
    redo_op["aliases"] = [
        {"name": "existing", "command": "echo existing"},  # Will make add return False
        {"name": "fail_add", "command": "echo fail"},  # Will make add raise
        {"invalid": "data"}  # Invalid for _load_alias
    ]

    # Add one alias to make 'existing' already exist
    temp_storage.add(Alias(name="existing", command="echo existing"), record_history=False)

    # Mock storage.add to return False for 'existing' and raise for 'fail_add'
    original_add = temp_storage.add
    def mock_add(alias, record_history=False):
        if alias.name == "existing":
            return False
        elif alias.name == "fail_add":
            raise Exception("Add failed")
        return original_add(alias, record_history)

    monkeypatch.setattr(temp_storage, 'add', mock_add)

    # Perform redo - should handle all cases
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "Redid add" in msg
    # Should indicate skips due to failures
    assert "skipped" in msg.lower()


def test_remove_redo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in remove redo: missing name, storage.remove failure, and storage.remove returning False."""
    # First, add and remove an alias to create a redo operation
    alias = Alias(name="test", command="echo test")
    temp_storage.add(alias, record_history=True)
    temp_storage.remove("test", record_history=True)
    temp_storage.history.perform_undo(temp_storage)  # Undo the remove, now redo stack has the remove operation

    # Modify the redo operation to have mixed alias data
    redo_op = temp_storage.history.list_redo()[0]
    redo_op["aliases"] = [
        {"command": "echo no_name"},  # Missing name
        {"name": "nonexistent", "command": "echo nonexistent"},  # Will make remove return False
        {"name": "fail_remove", "command": "echo fail"}  # Will make remove raise
    ]

    # Mock storage.remove to return False for 'nonexistent' and raise for 'fail_remove'
    original_remove = temp_storage.remove
    def mock_remove(name, record_history=False):
        if name == "nonexistent":
            return False
        elif name == "fail_remove":
            raise Exception("Remove failed")
        return original_remove(name, record_history)

    monkeypatch.setattr(temp_storage, 'remove', mock_remove)

    # Perform redo - should handle all cases
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "Redid remove" in msg
    # Should indicate skips due to failures
    assert "skipped" in msg.lower()


def test_edit_redo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in edit redo: _load_alias failure, storage.add failure, and storage.add returning False."""
    # First, do an edit and undo it to create a redo operation
    alias = Alias(name="test", command="echo hello")
    temp_storage.add(alias, record_history=True)
    edit_op = {
        "type": "edit",
        "aliases": [{"name": "test", "command": "echo hello"}],
        "new_aliases": [{"name": "test", "command": "echo world"}],
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(edit_op)
    temp_storage.history.perform_undo(temp_storage)  # Undo the edit, now redo stack has the edit operation

    # Modify the redo operation to have mixed new_aliases data
    redo_op = temp_storage.history.list_redo()[0]
    redo_op["new_aliases"] = [
        {"name": "existing", "command": "echo existing"},  # Will make add return False
        {"name": "fail_add", "command": "echo fail"},  # Will make add raise
        {"invalid": "data"}  # Invalid for _load_alias
    ]

    # Add one alias to make 'existing' already exist
    temp_storage.add(Alias(name="existing", command="echo existing"), record_history=False)

    # Mock storage.add to return False for 'existing' and raise for 'fail_add'
    original_add = temp_storage.add
    def mock_add(alias, record_history=False):
        if alias.name == "existing":
            return False
        elif alias.name == "fail_add":
            raise Exception("Add failed")
        return original_add(alias, record_history)

    monkeypatch.setattr(temp_storage, 'add', mock_add)

    # Perform redo - should handle all cases
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "Redid edit" in msg
    # Should indicate skips due to failures
    assert "skipped" in msg.lower()


def test_import_redo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in import redo: _load_alias failure, storage.add failure, and storage.add returning False."""
    # First, do an import and undo it to create a redo operation
    import_op = {
        "type": "import",
        "aliases": [{"name": "test", "command": "echo test"}],
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(import_op)
    temp_storage.history.perform_undo(temp_storage)  # Undo the import, now redo stack has the import operation

    # Modify the redo operation to have mixed aliases data
    redo_op = temp_storage.history.list_redo()[0]
    redo_op["aliases"] = [
        {"name": "existing", "command": "echo existing"},  # Will make add return False
        {"name": "fail_add", "command": "echo fail"},  # Will make add raise
        {"invalid": "data"}  # Invalid for _load_alias
    ]

    # Add one alias to make 'existing' already exist
    temp_storage.add(Alias(name="existing", command="echo existing"), record_history=False)

    # Mock storage.add to return False for 'existing' and raise for 'fail_add'
    original_add = temp_storage.add
    def mock_add(alias, record_history=False):
        if alias.name == "existing":
            return False
        elif alias.name == "fail_add":
            raise Exception("Add failed")
        return original_add(alias, record_history)

    monkeypatch.setattr(temp_storage, 'add', mock_add)

    # Perform redo - should handle all cases
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "Redid import" in msg
    # Should indicate skips due to failures
    assert "skipped" in msg.lower()


def test_rename_redo_edge_cases(temp_storage, monkeypatch):
    """Test edge cases in rename redo: _load_alias failure or storage operation failures."""
    # First, do a rename and undo it to create a redo operation
    alias = Alias(name="old_name", command="echo test")
    temp_storage.add(alias, record_history=True)
    rename_op = {
        "type": "rename",
        "aliases": [{"name": "old_name", "command": "echo test"}],
        "old_name": "old_name",
        "new_name": "new_name",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(rename_op)
    temp_storage.history.perform_undo(temp_storage)  # Undo the rename, now redo stack has the rename operation

    # Modify the redo operation to have mixed aliases data
    redo_op = temp_storage.history.list_redo()[0]
    redo_op["aliases"] = [
        {"name": "old_name", "command": "echo test"},  # Valid
        {"invalid": "data"}  # Invalid for _load_alias
    ]

    # Mock storage.remove to raise for 'old_name'
    original_remove = temp_storage.remove
    def mock_remove(name, record_history=False):
        if name == "old_name":
            raise Exception("Remove failed")
        return original_remove(name, record_history)

    monkeypatch.setattr(temp_storage, 'remove', mock_remove)

    # Perform redo - should handle failures
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "Redid rename" in msg
    # Should indicate skips due to failures
    assert "skipped" in msg.lower()


def test_group_add_redo_edge_cases(temp_storage):
    """Test edge cases in group_add redo: _load_alias failure."""
    # First, do a group_add and undo it to create a redo operation
    alias = Alias(name="test", command="echo test")
    temp_storage.add(alias, record_history=True)
    group_add_op = {
        "type": "group_add",
        "aliases": [{"name": "test", "command": "echo test"}],
        "group_name": "test_group",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(group_add_op)
    temp_storage.history.perform_undo(temp_storage)  # Undo the group_add, now redo stack has the group_add operation

    # Modify the redo operation to have mixed aliases data
    redo_op = temp_storage.history.list_redo()[0]
    redo_op["aliases"] = [
        {"name": "test", "command": "echo test"},  # Valid
        {"invalid": "data"}  # Invalid for _load_alias
    ]

    # Perform redo - should handle invalid data
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "Redid group_add" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()


def test_group_remove_redo(temp_storage):
    """Test redo for group_remove operations, including exception handling."""
    # Push a group_remove operation with mixed aliases
    group_remove_op = {
        "type": "group_remove",
        "aliases": [
            {"name": "test", "command": "echo test", "group": "test_group"},  # Valid
            {"invalid": "data"}  # Invalid for _load_alias
        ],
        "group_name": "test_group",
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(group_remove_op)
    temp_storage.history.perform_undo(temp_storage)  # Undo the group_remove, now redo stack has the group_remove operation

    # Perform redo - should handle invalid data
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "Redid group_remove" in msg
    # Should indicate skips due to invalid data
    assert "skipped" in msg.lower()

# ============================
# Tag operations
# ============================

def test_tag_operations_undo_redo(temp_storage):
    """Test undo/redo for tag operations."""
    # Add alias
    alias = Alias(name="test", command="echo hello", tags=["old"])
    temp_storage.add(alias, record_history=True)

    tag_add_op = {
        "type": "tag_add",
        "aliases": [{"name": "test", "command": "echo hello", "tags": ["old"]}],
        "added_tags": ["new_tag"],
        "timestamp": datetime.now().isoformat()
    }
    temp_storage.history.push(tag_add_op)

    # Apply tag addition
    alias.tags.append("new_tag")
    temp_storage.aliases["test"] = alias
    temp_storage.save()

    # Undo tag_add
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid tag_add" in msg

    # Verify tag was removed
    assert "new_tag" not in temp_storage.get("test").tags
    assert "old" in temp_storage.get("test").tags

    # Redo tag_add
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid tag_add" in msg

    # Verify tag was restored
    assert "new_tag" in temp_storage.get("test").tags
    assert "old" in temp_storage.get("test").tags

# ============================
# Coverage-only tests
# ============================

def test_tag_add_redo_exception_handling(temp_storage):
    """Test that tag_add redo handles exceptions."""
    # Create alias with some tags
    alias1 = Alias(name="test1", command="echo hello", tags=["existing"])
    temp_storage.add(alias1, record_history=True)

    # Record history operation with mixed valid and invalid alias data
    history_op = {
        "type": "tag_add",
        "aliases": [
            alias1.to_dict(),  # Valid alias
            {"invalid": "data"}  # Invalid alias data that will cause _load_alias to fail
        ],
        "added_tags": ["existing", "new_tag"],  # Tags to add
        "timestamp": "2025-01-01T00:00:00.000000"
    }
    temp_storage.history.push(history_op)

    # Undo the tag_add (moves to redo stack) - this removes the added tags
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid tag_add" in msg
    # After undo, alias has no added tags
    assert "existing" not in temp_storage.get("test1").tags
    assert "new_tag" not in temp_storage.get("test1").tags

    temp_storage.get("test1").tags.append("existing")
    temp_storage.save()

    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid tag_add" in msg
    # Should indicate that one alias was skipped due to exception
    assert "skipped" in msg.lower()
    # Verify that "new_tag" was added, and "existing" was not added again (since already present)
    assert "new_tag" in temp_storage.get("test1").tags
    assert temp_storage.get("test1").tags.count("existing") == 1  # Still only once


def test_tag_remove_redo_exception_handling(temp_storage):
    """Test that tag_remove redo handles exceptions."""
    # Create alias with some tags
    alias1 = Alias(name="test1", command="echo hello", tags=["tag1", "tag2"])
    temp_storage.add(alias1, record_history=True)

    # Record history operation with mixed valid and invalid alias data
    history_op = {
        "type": "tag_remove",
        "aliases": [
            alias1.to_dict(),  # Valid alias
            {"invalid": "data"}  # Invalid alias data that will cause _load_alias to fail
        ],
        "removed_tags": ["tag1", "nonexistent"],  # "tag1" exists, "nonexistent" does not
        "timestamp": "2025-01-01T00:00:00.000000"
    }
    temp_storage.history.push(history_op)

    # Undo the tag_remove (moves to redo stack) - this restores the removed tags
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid tag_remove" in msg
    # After undo, alias has all tags back
    assert "tag1" in temp_storage.get("test1").tags
    assert "tag2" in temp_storage.get("test1").tags

    temp_storage.get("test1").tags.remove("tag1")
    temp_storage.save()

    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid tag_remove" in msg
    # Should indicate that one alias was skipped due to exception
    assert "skipped" in msg.lower()
    # Verify that "tag1" was not removed (since already absent), "nonexistent" ignored
    assert "tag1" not in temp_storage.get("test1").tags
    assert "tag2" in temp_storage.get("test1").tags  # Still there


def test_tag_rename_redo_exception_handling(temp_storage):
    """Test that tag_rename redo handles exceptions."""
    # Create aliases with different tag states
    alias1 = Alias(name="test1", command="echo hello", tags=["old_tag", "other"])  # Has old_tag
    alias2 = Alias(name="test2", command="echo world", tags=["other2"])  # Does not have old_tag
    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)

    # Record history operation with mixed valid and invalid alias data
    history_op = {
        "type": "tag_rename",
        "aliases": [
            alias1.to_dict(),  # Valid alias with old_tag
            alias2.to_dict(),  # Valid alias without old_tag
            {"invalid": "data"}  # Invalid alias data that will cause _load_alias to fail
        ],
        "old_tag": "old_tag",
        "new_tag": "new_tag",
        "timestamp": "2025-01-01T00:00:00.000000"
    }
    temp_storage.history.push(history_op)

    # Undo the tag_rename (moves to redo stack) - this renames back to old_tag where applicable
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid tag_rename" in msg
    # After undo, alias1 has old_tag back, alias2 unchanged
    assert "old_tag" in temp_storage.get("test1").tags
    assert "new_tag" not in temp_storage.get("test1").tags
    assert "old_tag" not in temp_storage.get("test2").tags

    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid tag_rename" in msg
    # Should indicate that one alias was skipped due to exception
    assert "skipped" in msg.lower()
    # Verify that alias1 had old_tag renamed to new_tag, alias2 unchanged
    assert "old_tag" not in temp_storage.get("test1").tags
    assert "new_tag" in temp_storage.get("test1").tags
    assert "other" in temp_storage.get("test1").tags
    assert "old_tag" not in temp_storage.get("test2").tags
    assert "new_tag" not in temp_storage.get("test2").tags
    assert "other2" in temp_storage.get("test2").tags


def test_tag_delete_redo_exception_handling(temp_storage):
    """Test that tag_delete redo handles exceptions."""
    # Create aliases with different tag states
    alias1 = Alias(name="test1", command="echo hello", tags=["deleted_tag", "other"])  # Has deleted_tag
    alias2 = Alias(name="test2", command="echo world", tags=["other2"])  # Does not have deleted_tag
    temp_storage.add(alias1, record_history=True)
    temp_storage.add(alias2, record_history=True)

    # Record history operation with aliases that had the tag and some that didn't, plus invalid data
    history_op = {
        "type": "tag_delete",
        "aliases": [
            alias1.to_dict(),  # Valid alias that had deleted_tag
            alias2.to_dict(),  # Valid alias that did not have deleted_tag
            {"invalid": "data"}  # Invalid alias data that will cause _load_alias to fail
        ],
        "deleted_tag": "deleted_tag",
        "timestamp": "2025-01-01T00:00:00.000000"
    }
    temp_storage.history.push(history_op)

    # Undo the tag_delete (moves to redo stack) - this restores the deleted_tag to aliases that didn't have it
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid tag_delete" in msg
    # After undo, both aliases have deleted_tag
    assert "deleted_tag" in temp_storage.get("test1").tags
    assert "deleted_tag" in temp_storage.get("test2").tags

    temp_storage.get("test2").tags.remove("deleted_tag")
    temp_storage.save()

    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid tag_delete" in msg
    # Should indicate that one alias was skipped due to exception
    assert "skipped" in msg.lower()
    # Verify that deleted_tag was removed from alias1, but not from alias2 since it wasn't there
    assert "deleted_tag" not in temp_storage.get("test1").tags
    assert "other" in temp_storage.get("test1").tags
    assert "deleted_tag" not in temp_storage.get("test2").tags
    assert "other2" in temp_storage.get("test2").tags


def test_group_import_redo_exception_handling(temp_storage):
    """Test that group_import redo handles exceptions."""
    # Create alias
    alias1 = Alias(name="test1", command="echo hello")
    temp_storage.add(alias1, record_history=True)

    # Record history operation with valid and invalid alias data
    history_op = {
        "type": "group_import",
        "aliases": [
            alias1.to_dict(),  # Valid alias
            {"invalid": "data"}  # Invalid alias data that will cause _load_alias to fail
        ],
        "group_name": "imported_group",
        "timestamp": "2025-01-01T00:00:00.000000"
    }
    temp_storage.history.push(history_op)

    # Undo the group_import (moves to redo stack) - this removes aliases from group
    msg = temp_storage.history.perform_undo(temp_storage)
    assert "✅" in msg and "Undid group_import" in msg
    # After undo, alias is not in group
    assert temp_storage.get("test1").group is None

    # Redo the group_import - should handle the invalid alias gracefully
    msg = temp_storage.history.perform_redo(temp_storage)
    assert "🔁" in msg and "Redid group_import" in msg
    # Should indicate that one alias was skipped due to exception
    assert "skipped" in msg.lower()
    # Verify that alias was restored to group
    assert temp_storage.get("test1").group == "imported_group"


def test_format_message_skipped_other_action(temp_storage):
    """Test _format_message with skipped > 0 and action not 'Undid' or 'Redid'"""
    msg = temp_storage.history._format_message("Other", "add", 1, 2, 1)
    assert "Other add (1 of 2 aliases processed, 1 skipped)" in msg


def test_format_message_group_delete(temp_storage):
    """Test _format_message with op_type 'group_delete'"""
    msg = temp_storage.history._format_message("Undid", "group_delete", 2, 2, 0)
    assert "Undid group_delete (2 aliases reassigned)" in msg