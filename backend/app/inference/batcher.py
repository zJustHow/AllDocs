import asyncio
from collections.abc import Callable


class EmbedBatcher:
    """Micro-batch concurrent embed requests into fewer model.encode calls."""

    def __init__(
        self,
        encode_fn: Callable[[list[str]], list[list[float]]],
        *,
        max_wait_s: float = 0.01,
        max_batch_texts: int = 64,
    ) -> None:
        self._encode_fn = encode_fn
        self._max_wait_s = max_wait_s
        self._max_batch_texts = max_batch_texts
        self._queue: asyncio.Queue[tuple[list[str], asyncio.Future[list[list[float]]]]] = (
            asyncio.Queue()
        )
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        future: asyncio.Future[list[list[float]]] = loop.create_future()
        await self._queue.put((texts, future))
        return await future

    async def _run(self) -> None:
        while True:
            first_texts, first_future = await self._queue.get()
            batch: list[tuple[list[str], asyncio.Future[list[list[float]]]]] = [
                (first_texts, first_future)
            ]
            total_texts = len(first_texts)
            deadline = asyncio.get_running_loop().time() + self._max_wait_s

            while total_texts < self._max_batch_texts:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    texts, future = await asyncio.wait_for(self._queue.get(), timeout)
                except TimeoutError:
                    break
                batch.append((texts, future))
                total_texts += len(texts)

            all_texts: list[str] = []
            spans: list[tuple[int, int, asyncio.Future[list[list[float]]]]] = []
            for texts, future in batch:
                start = len(all_texts)
                all_texts.extend(texts)
                spans.append((start, start + len(texts), future))

            try:
                vectors = await asyncio.to_thread(self._encode_fn, all_texts)
                for start, end, future in spans:
                    if not future.done():
                        future.set_result(vectors[start:end])
            except Exception as exc:
                for _, _, future in spans:
                    if not future.done():
                        future.set_exception(exc)
