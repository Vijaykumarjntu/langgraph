import pytest
from langgraph.prebuilt.semantic_scheduler import node, SemanticSuperstepAdmission, SemanticConflictError


def test_semantic_scheduler_enforces_exclusive_locks():
    """Confirms exclusive bare-keys raise hard errors under default 'refuse' policies."""
    @node(writes=["status", "assignee"])
    def branch_a(state): pass

    @node(writes=["assignee"])
    def branch_b(state): pass

    admission = SemanticSuperstepAdmission(policy="refuse")
    
    # Admitting Branch A should succeed and claim keys
    admitted, _ = admission.admit_batch([branch_a])
    assert len(admitted) == 1
    
    # Admitting concurrent Branch B over the same keys must raise a hard conflict error
    with pytest.raises(SemanticConflictError):
        admission.admit_batch([branch_b])


def test_semantic_scheduler_allows_append_concurrency():
    """Confirms .append suffix descriptors allow concurrent execution paths to share channels."""
    @node(writes=["history.append", "metrics.update"])
    def branch_b(state): pass

    @node(writes=["history.append"])
    def branch_c(state): pass

    admission = SemanticSuperstepAdmission(policy="refuse")
    admitted, _ = admission.admit_batch([branch_b, branch_c])
    
    # Both pass because append intent is non-exclusive
    assert len(admitted) == 2


def test_semantic_scheduler_queues_deferred_tasks():
    """Confirms 'queue' policy moves conflicting tasks out of the active batch cleanly."""
    @node(writes=["status"])
    def branch_a(state): pass

    @node(writes=["status"])
    def branch_b(state): pass

    admission = SemanticSuperstepAdmission(policy="queue")
    
    admitted, _ = admission.admit_batch([branch_a, branch_b])
    
    # Branch A claims status, Branch B gets safely deferred instead of crashing the process
    assert len(admitted) == 1
    assert admitted[0] == branch_a