from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langchain_core.runnables import RunnableConfig
# ==========================================
# 🧱 STEP 1: ABSTRACT BASE CLASSES
# ==========================================

class BasePostgresCursor(ABC):
    """Abstract cursor providing standardized row generation and execution maps."""
    
    @abstractmethod
    async def execute(self, query: str, params: Optional[Union[List[Any], tuple]] = None) -> None:
        """Executes a parameterized SQL query."""
        pass

    @abstractmethod
    async def fetchone(self) -> Optional[Dict[str, Any]]:
        """Fetches a single row mapped as a key-value dictionary."""
        pass

    @abstractmethod
    async def fetchall(self) -> List[Dict[str, Any]]:
        """Fetches all matching rows mapped as key-value dictionaries."""
        pass


class BasePostgresConnection(ABC):
    """Abstract database adapter interface separating LangGraph from engine drivers."""

    def __init__(self, external_client: Any):
        self.client = external_client

    @abstractmethod
    def cursor(self) -> BasePostgresCursor:
        """Spawns an abstract cursor executing inside the current connection instance."""
        pass

    @abstractmethod
    async def commit(self) -> None:
        """Commits the active transaction layer safely."""
        pass

    @abstractmethod
    async def rollback(self) -> None:
        """Rolls back the active transaction layer safely."""
        pass


# ==========================================
# ⚡ STEP 2: CONCRETE ASYNCPG ADAPTER
# ==========================================

class AsyncpgCursorAdapter(BasePostgresCursor):
    """Bridges asyncpg query loops to match LangGraph checkpoint execution patterns."""

    def __init__(self, connection: Any):
        self.connection = connection
        self._results: List[Dict[str, Any]] = []
        self._index: int = 0

    def _translate_query(self, query: str) -> str:
        """Transforms traditional '%s' positional parameters into asyncpg numbered '$1' markers."""
        if "%s" not in query:
            return query
        parts = query.split("%s")
        translated = "".join(f"{part}${i+1}" for i, part in enumerate(parts[:-1])) + parts[-1]
        return translated

    async def execute(self, query: str, params: Optional[Union[List[Any], tuple]] = None) -> None:
        translated_query = self._translate_query(query)
        args = params if params is not None else []
        
        # Check if query expects rows back
        if query.strip().upper().startswith(("SELECT", "INSERT", "UPDATE")) and "RETURNING" in query.upper():
            records = await self.connection.fetch(translated_query, *args)
            self._results = [dict(r) for r in records]
        else:
            await self.connection.execute(translated_query, *args)
            self._results = []
        self._index = 0

    async def fetchone(self) -> Optional[Dict[str, Any]]:
        if self._index < len(self._results):
            row = self._results[self._index]
            self._index += 1
            return row
        return None

    async def fetchall(self) -> List[Dict[str, Any]]:
        remaining = self._results[self._index:]
        self._index = len(self._results)
        return remaining


class AsyncpgConnectionAdapter(BasePostgresConnection):
    """Wraps an external, active asyncpg Connection block for use by LangGraph."""

    def cursor(self) -> BasePostgresCursor:
        return AsyncpgCursorAdapter(self.client)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass



# ==================================================================
# 🧪 STEP 3: EXTENSIBLE PLUGGABLE POSTGRES CHECKPOINT SAVER
# ==================================================================

class ExtensiblePostgresSaver(BaseCheckpointSaver):
    """A pluggable, driver-agnostic LangGraph Checkpointer that can execute over
    psycopg3, asyncpg, or custom connection engines using the BasePostgresConnection abstraction.
    """

    def __init__(self, wrapped_conn: BasePostgresConnection, **kwargs: Any):
        super().__init__(**kwargs)
        self.conn = wrapped_conn

    async def setup(self) -> None:
        """Initializes system tables agnostic of underlying target driver configurations."""
        cursor = self.conn.cursor()
        await cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL,
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                checkpoint TEXT NOT NULL,
                metadata TEXT NOT NULL,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            );
            """
        )
        await self.conn.commit()

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Retrieves a single checkpoint tuple by configuration metrics."""
        thread_id = config["configurable"].get("thread_id")
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        cursor = self.conn.cursor()
        if checkpoint_id:
            query = (
                "SELECT checkpoint, metadata, parent_checkpoint_id FROM checkpoints "
                "WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s LIMIT 1"
            )
            await cursor.execute(query, [thread_id, checkpoint_ns, checkpoint_id])
        else:
            query = (
                "SELECT checkpoint, metadata, checkpoint_id, parent_checkpoint_id FROM checkpoints "
                "WHERE thread_id = %s AND checkpoint_ns = %s ORDER BY checkpoint_id DESC LIMIT 1"
            )
            await cursor.execute(query, [thread_id, checkpoint_ns])

        row = await cursor.fetchone()
        if not row:
            return None

        # Handle structural configuration fields dynamically
        c_id = checkpoint_id or row.get("checkpoint_id")
        
        # In a full deployment, deserialize row.get("checkpoint") and row.get("metadata") using self.serde
        checkpoint_data: Checkpoint = self.serde.loads(row.get("checkpoint").encode())
        metadata_data: CheckpointMetadata = self.serde.loads(row.get("metadata").encode())

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": c_id,
                }
            },
            checkpoint=checkpoint_data,
            metadata=metadata_data,
            parent_config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": row.get("parent_checkpoint_id"),
                }
            } if row.get("parent_checkpoint_id") else None,
        )

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> RunnableConfig:
        """Persists a fresh execution snapshot using the uniform cursor layer."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        # Package state signatures
        blob_checkpoint = self.serde.dumps(checkpoint).decode()
        blob_metadata = self.serde.dumps(metadata).decode()

        cursor = self.conn.cursor()
        query = (
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET checkpoint = EXCLUDED.checkpoint, metadata = EXCLUDED.metadata"
        )
        await cursor.execute(
            query,
            [thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, blob_checkpoint, blob_metadata],
        )
        await self.conn.commit()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    # Satisfy ABC requirements for sync variants by delegating to async loops
    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        raise NotImplementedError("Use async engine loops (aget_tuple) for extensible postgres saver contexts.")

    def put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: Any) -> RunnableConfig:
        raise NotImplementedError("Use async engine loops (aput) for extensible postgres saver contexts.")