import pytest
from langgraph.prebuilt.types import Interrupt, PregelTask
from langgraph.prebuilt.types import fetch, GraphInterrupt


def test_pregel_task_segregates_fetches_and_human_interrupts():
    """Confirms task.fetches and task.interrupts isolate their contexts cleanly."""
    i1 = Interrupt(value="Approve wire transfer?", id="1", kind="human")
    i2 = Interrupt(value={"get_weather": "zip_90210"}, id="2", kind="fetch")
    
    task = PregelTask(
        id="task_1",
        name="orchestrator_node",
        path=("__root__", "orchestrator_node"),
        interrupts=(i1, i2)
    )
    
    # Assert segregation properties hold true
    assert len(task.interrupts) == 2
    assert len(task.fetches) == 1
    assert task.fetches[0].value == {"get_weather": "zip_90210"}
    assert len(task.human_interrupts) == 1


def test_fetch_primitive_raises_correct_discriminator():
    """Confirms fetch() raises a GraphInterrupt holding the 'fetch' metadata assignment."""
    payload = {"require_schema": "PatientVitals"}
    
    with pytest.raises(GraphInterrupt) as exc_info:
        fetch(payload)
        
    interrupts = exc_info.value.interrupts
    assert len(interrupts) == 1
    assert interrupts[0].kind == "fetch"
    assert interrupts[0].value == payload
    assert interrupts[0].id.startswith("fch_")