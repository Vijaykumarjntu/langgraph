import json
from io import StringIO
from datetime import datetime, timezone
import pytest
from pytest_mock import MockerFixture

from langgraph.store.base import GetOp, PutOp, SearchOp, ListNamespacesOp
from langgraph.store.mimir import MimirStore


class MockSubprocessPipe:
    """Simulates a bidirectional subprocess stdio pipe for JSON-RPC framing."""
    def __init__(self):
        self.written_data = []
        self.mock_responses = []

    def write(self, data: str):
        self.written_data.append(json.loads(data.strip()))

    def flush(self):
        pass

    def readline(self) -> str:
        if self.mock_responses:
            return json.dumps(self.mock_responses.pop(0)) + "\n"
        return ""


@pytest.fixture
def mock_mimir_engine(mocker: MockerFixture):
    """Mocks out the low-level Popen engine to avoid calling external binaries."""
    mocker.patch("shutil.which", return_value="/usr/local/bin/mimir")
    
    mock_process = mocker.MagicMock()
    mock_process.poll.return_value = None
    
    pipe = MockSubprocessPipe()
    mock_process.stdin = pipe
    mock_process.stdout = pipe
    
    mocker.patch("subprocess.Popen", return_value=mock_process)
    return pipe


def test_mimir_store_lifecycle(mock_mimir_engine) -> None:
    """Verifies that the store starts and cleanly terminates backend subprocesses."""
    store = MimirStore(db_path="./test.db")
    store.start()
    assert store._process is not None

    store.stop()
    assert store._process is None


def test_mimir_store_handle_put(mock_mimir_engine) -> None:
    """Verifies that PutOp correctly routes payload serialization into 'remember'."""
    store = MimirStore()
    
    # Setup mock response for successful 'remember' invocation
    mock_mimir_engine.mock_responses.append({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"status": "success"}
    })

    op = PutOp(namespace=("users", "alice"), key="settings", value={"theme": "dark"}, index=None)
    store.batch([op])

    # Check outgoing call properties
    assert len(mock_mimir_engine.written_data) == 1
    call = mock_mimir_engine.written_data[0]
    assert call["method"] == "tools/call"
    # assert call["params"]["name"] == "remember"
    assert call["params"]["name"] == "mimir_remember"
    assert call["params"]["arguments"] == {
        "namespace": "users.alice",
        "key": "settings",
        "value": {"theme": "dark"}
    }
    store.stop()


def test_mimir_store_handle_forget(mock_mimir_engine) -> None:
    """Verifies that passing a None value triggers a 'forget' invocation."""
    store = MimirStore()
    mock_mimir_engine.mock_responses.append({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"status": "deleted"}
    })

    op = PutOp(namespace=("users", "alice"), key="settings", value=None, index=None)
    store.batch([op])

    call = mock_mimir_engine.written_data[0]
    # assert call["params"]["name"] == "forget"
    assert call["params"]["name"] == "mimir_forget"
    assert call["params"]["arguments"] == {
        "namespace": "users.alice",
        "key": "settings"
    }
    store.stop()


def test_mimir_store_handle_get(mock_mimir_engine) -> None:
    """Verifies that GetOp handles namespace un-flattening and parses dates."""
    store = MimirStore()
    now_iso = datetime.now(timezone.utc).isoformat()
    
    mock_mimir_engine.mock_responses.append({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "value": {"theme": "light"},
            "created_at": now_iso,
            "updated_at": now_iso
        }
    })

    op = GetOp(namespace=("users", "bob"), key="prefs")
    results = store.batch([op])

    assert len(results) == 1
    item = results[0]
    assert item.namespace == ("users", "bob")
    assert item.key == "prefs"
    assert item.value == {"theme": "light"}
    assert item.created_at.isoformat() == now_iso
    store.stop()


def test_mimir_store_handle_search(mock_mimir_engine) -> None:
    """Verifies hybrid search extraction parses matches and scores accurately."""
    store = MimirStore()
    now_iso = datetime.now(timezone.utc).isoformat()

    mock_mimir_engine.mock_responses.append({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "matches": [
                {
                    "namespace": "docs.python",
                    "key": "intro",
                    "value": {"text": "Python tutorial"},
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "score": 0.95
                }
            ]
        }
    })

    op = SearchOp(namespace_prefix=("docs",), query="python programming", filter=None, limit=5, offset=0)
    results = store.batch([op])

    assert len(results) == 1
    search_items = results[0]
    assert len(search_items) == 1
    
    match = search_items[0]
    assert match.namespace == ("docs", "python")
    assert match.key == "intro"
    assert match.value == {"text": "Python tutorial"}
    assert match.score == 0.95
    store.stop()


@pytest.mark.asyncio
async def test_mimir_store_async_abatch(mock_mimir_engine) -> None:
    """Validates that abatch executes correctly inside the asynchronous thread pool loop."""
    store = MimirStore()
    mock_mimir_engine.mock_responses.append({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"status": "success"}
    })

    op = PutOp(namespace=("logs",), key="1", value={"status": "ok"}, index=None)
    # Testing our async execution thread runner wrapper
    await store.abatch([op])
    
    assert len(mock_mimir_engine.written_data) == 1
    store.stop()