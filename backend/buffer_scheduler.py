import asyncio
import time
from conductor import Conductor, NoteEvent
from dataclasses import asdict

CHUNK_DURATION = 4.0   # seconds per chunk
LOOKAHEAD = 3          # generate this many chunks ahead


class BufferScheduler:
    def __init__(self, conductor: Conductor):
        self.conductor = conductor
        self._running = False
        self._send_callback = None
        self._task: asyncio.Task | None = None
        self._generation_count = 0

    def set_send_callback(self, cb):
        """cb(notes: list[dict]) — called when a chunk is ready to send."""
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
        """Continuously generate chunks and send them, staying LOOKAHEAD ahead."""
        while self._running:
            # Generate next chunk
            try:
                notes = self.conductor.generate_chunk(CHUNK_DURATION)
                if self._send_callback:
                    payload = [asdict(n) for n in notes]
                    await self._send_callback(payload)
                self._generation_count += 1
            except Exception as e:
                print(f'[BufferScheduler] Error generating chunk: {e}')

            # Wait chunk_duration before generating the next one
            # This keeps us ~CHUNK_DURATION ahead of playback
            await asyncio.sleep(CHUNK_DURATION)
