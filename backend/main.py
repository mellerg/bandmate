import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audio_analyzer import AudioAnalyzer
from conductor import Conductor
from buffer_scheduler import BufferScheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Bandmate server started.")
    yield
    print("Bandmate server stopped.")


app = FastAPI(title="Bandmate POC Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "bandmate"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    print(f"[WS] Client connected: {ws.client}")

    analyzer = AudioAnalyzer()
    conductor = Conductor()
    scheduler = BufferScheduler(conductor)
    generation_started = False
    genre = "blues"

    # KPI timing state (mutable dict avoids nonlocal for multiple vars)
    kpi_state = {
        'first_audio_time': None,   # wall time when first PCM chunk arrived
        'first_notes_sent': False,  # have we emitted the first notes batch?
        'last_energy': 0.0,
        'last_bpm': 0.0,
        'change_detected_time': None,  # wall time of last significant change
    }

    async def send_notes(notes: list[dict]):
        now = time.time()
        kpi: dict = {
            'musicality_score': round(conductor.last_musicality_score * 100, 1),
        }

        # Buffer join time: first audio chunk → first notes sent
        if not kpi_state['first_notes_sent']:
            kpi_state['first_notes_sent'] = True
            if kpi_state['first_audio_time'] is not None:
                kpi['buffer_join_ms'] = round((now - kpi_state['first_audio_time']) * 1000)

        # Dynamic response: time from last significant change → this notes batch
        if kpi_state['change_detected_time'] is not None:
            kpi['dynamic_response_ms'] = round((now - kpi_state['change_detected_time']) * 1000)
            kpi_state['change_detected_time'] = None

        try:
            await ws.send_text(json.dumps({"type": "notes", "notes": notes}))
            await ws.send_text(json.dumps({"type": "kpi", "metrics": kpi}))
        except Exception:
            pass

    scheduler.set_send_callback(send_notes)

    try:
        await ws.send_text(json.dumps({
            "type": "status",
            "message": "Connected to Bandmate server. Start playing!"
        }))

        while True:
            data = await ws.receive()

            # Text messages: JSON control commands
            if "text" in data:
                try:
                    msg = json.loads(data["text"])

                    if msg.get("type") == "genre":
                        # Just update genre — does NOT start the scheduler
                        genre = msg.get("genre", "blues")
                        conductor.update(
                            key=conductor.key,
                            bpm=conductor.bpm,
                            genre=genre,
                            energy=conductor.energy
                        )
                        print(f"[WS] Genre set to: {genre}")

                    elif msg.get("type") == "start_generation":
                        # Sent by frontend after the listen phase — starts the scheduler
                        genre = msg.get("genre", genre)
                        conductor.update(
                            key=conductor.key,
                            bpm=conductor.bpm,
                            genre=genre,
                            energy=conductor.energy
                        )
                        print(f"[WS] Start generation requested (genre={genre})")
                        if not generation_started:
                            generation_started = True
                            scheduler.start()
                            print("[WS] Buffer scheduler started.")

                except json.JSONDecodeError:
                    pass

            # Binary messages: raw Float32 PCM audio
            elif "bytes" in data:
                pcm_bytes = data["bytes"]
                if len(pcm_bytes) < 8:
                    continue

                try:
                    analysis = analyzer.process_chunk(pcm_bytes)

                    # Record first audio arrival time for buffer-join KPI
                    if kpi_state['first_audio_time'] is None:
                        kpi_state['first_audio_time'] = time.time()

                    # Detect significant changes for dynamic-response KPI
                    if generation_started:
                        prev_energy = kpi_state['last_energy']
                        prev_bpm = kpi_state['last_bpm']
                        energy_delta = (
                            abs(analysis['energy'] - prev_energy) / max(prev_energy, 0.001)
                        )
                        bpm_delta = abs(analysis['bpm'] - prev_bpm)
                        if (prev_energy > 0 and energy_delta > 0.20) or bpm_delta > 10:
                            kpi_state['change_detected_time'] = time.time()

                    kpi_state['last_energy'] = analysis['energy']
                    kpi_state['last_bpm'] = analysis['bpm']

                    conductor.update(
                        key=analysis["key"],
                        bpm=analysis["bpm"],
                        genre=genre,
                        energy=analysis["energy"]
                    )
                    await ws.send_text(json.dumps({
                        "type": "analysis",
                        "analysis": analysis
                    }))
                except Exception as e:
                    print(f"[WS] Analysis error: {e}")

    except WebSocketDisconnect:
        print(f"[WS] Client disconnected: {ws.client}")
    finally:
        scheduler.stop()
        analyzer.reset()


# ── Serve built frontend (production) ────────────────────────────────────────
# This runs after all API/WS routes so they always take priority.
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_FRONTEND_DIST / "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(_: str):
        return FileResponse(str(_FRONTEND_DIST / "index.html"))
