"""Per-build pub/sub: connected clients receive events; there is no replay."""
import asyncio
import json
from collections import defaultdict
from contextlib import asynccontextmanager


class EventBus:
    def __init__(self):
        self.subscribers = defaultdict(set)

    @asynccontextmanager
    async def subscribe(self, build_id):
        queue = asyncio.Queue()
        self.subscribers[build_id].add(queue)
        try:
            yield queue
        finally:
            self.subscribers[build_id].discard(queue)
            if not self.subscribers[build_id]:
                del self.subscribers[build_id]

    async def publish(self, build_id, event, data):
        item = {"event": event, "data": json.dumps(data)}
        for queue in tuple(self.subscribers.get(build_id, ())):
            queue.put_nowait(item)

    async def stream(self, build_id):
        async with self.subscribe(build_id) as queue:
            yield {"event": "ready", "data": json.dumps({"build_id": build_id})}
            while True:
                yield await queue.get()
