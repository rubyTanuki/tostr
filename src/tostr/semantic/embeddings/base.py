import asyncio
import time
from abc import ABC, abstractmethod

class EmbeddingStrategy(ABC):
    def __init__(self, batch_size: int = 32, batch_timeout: float = 1.5):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout

    @property
    @abstractmethod
    def dimensions(self) -> int:
        pass

    @abstractmethod
    def embed_batch(self, descriptions: list[str]) -> list[list[float]]: 
        pass

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        pass

class EmbeddingClient:
    def __init__(self, strategy: EmbeddingStrategy):
        self.strategy = strategy
        # Unbounded queue is safe here
        self.queue = asyncio.Queue() 
        self._worker_task = None

    def start(self):
        """Starts the background consumer loop."""
        self._worker_task = asyncio.create_task(self._process_queue())

    def enqueue(self, struct: "BaseStruct"):
        """Fire-and-forget push from the DFS loop."""
        self.queue.put_nowait(struct)

    async def _process_queue(self):
        batch = []
        batch_start_time = None

        while True:
            try:
                if batch:
                    time_left = (batch_start_time + self.strategy.batch_timeout) - time.time()
                    if time_left <= 0:
                        raise asyncio.TimeoutError()

                    struct = await asyncio.wait_for(self.queue.get(), timeout=time_left)
                else:
                    struct = await self.queue.get()
                    batch_start_time = time.time()
                
                batch.append(struct)

                if len(batch) >= self.strategy.batch_size:
                    await self._flush_batch(batch)
                    batch = []

            except asyncio.TimeoutError:
                if batch:
                    await self._flush_batch(batch)
                    batch = []
            except asyncio.CancelledError:
                if batch:
                    await self._flush_batch(batch)
                break
    
    async def _flush_batch(self, batch: list["BaseStruct"]):
        if not batch:
            return
        
        descriptions = [f"{s.uid}: {s.description}" for s in batch]

        # Offload the computation to the thread pool
        embeddings = await asyncio.to_thread(
            self.strategy.embed_batch, 
            descriptions
        )

        for struct, vector in zip(batch, embeddings):
            struct.embedding = vector
        
        for _ in batch:
            self.queue.task_done()

    async def drain_and_stop(self):
        """Blocks until the queue is completely empty, then halts the worker."""
        await self.queue.join()

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass