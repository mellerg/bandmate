import asyncio
from conductor import Conductor
from dataclasses import asdict

CHUNK_DURATION = 4.0   # target seconds per chunk (actual is bar-aligned)


class BufferScheduler:
    def __init__(self, conductor: Conductor):
        self.conductor = conductor
        self._running = False
        self._send_callback = None
        self._task: asyncio.Task | None = None
        self._generation_count = 0

    def set_send_callback(self, cb):
        """cb(notes: list[dict], actual_duration: float) — called when a chunk is ready."""
        self._send_callback = cb

    def start(self):
        self._running = True
        self._generation_count = 0
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self):
        """Generate chunks continuously, sleeping actual_duration between each."""
        while self._running:
            actual_duration = CHUNK_DURATION
            try:
                notes, actual_duration = self.conductor.generate_chunk(CHUNK_DURATION)
                if self._send_callback:
                    payload = [asdict(n) for n in notes]
                    await self._send_callback(payload, actual_duration)
                self._generation_count += 1
            except Exception as e:
                print(f'[BufferScheduler] Error generating chunk: {e}')

            await asyncio.sleep(actual_duration)
