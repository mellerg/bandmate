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


@app.get("/health/drums", include_in_schema=False)
async def health_drums():
    dist = Path(__file__).parent.parent / "frontend" / "dist" / "drums"
    files = {f.name: f.stat().st_size for f in dist.iterdir()} if dist.exists() else {}
    return {"drums_dir_exists": dist.exists(), "files": files}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    print(f"[WS] Client connected: {ws.client}")

    analyzer = AudioAnalyzer()
    conductor = Conductor()
    scheduler = BufferScheduler(conductor)
    generation_started = False
    session_stopped = False   # True while waiting for keep_jamming after 14s silence
    genre = "blues"
    reanalysis_task: asyncio.Task | None = None

    # KPI timing state (mutable dict avoids nonlocal for multiple vars)
    kpi_state = {
        'first_audio_time': None,   # wall time when first PCM chunk arrived
        'first_notes_sent': False,  # have we emitted the first notes batch?
        'last_energy': 0.0,
        'last_bpm': 0.0,
        'change_detected_time': None,  # wall time of last significant change
    }

    async def send_notes(notes: list[dict], actual_duration: float):
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
            await ws.send_text(json.dumps({
                "type": "notes",
                "notes": notes,
                "actual_duration": round(actual_duration, 4),
            }))
            await ws.send_text(json.dumps({"type": "kpi", "metrics": kpi}))
        except Exception:
            pass

    async def _reanalysis_loop() -> None:
        """Re-detect key and BPM every 8 s while the band is playing."""
        await asyncio.sleep(8.0)
        while generation_started and not session_stopped:
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, analyzer.analyze_recent)
                if result:
                    key_changed = result['key'] != conductor.key
                    bpm_changed = abs(result['bpm'] - conductor.bpm) > 5
                    if key_changed or bpm_changed:
                        conductor.update(
                            key=result['key'],
                            bpm=result['bpm'],
                            genre=genre,
                            energy=conductor.energy,
                        )
                        print(
                            f"[WS] Re-analysis update: "
                            f"key={result['key']}{'*' if key_changed else ''}, "
                            f"bpm={result['bpm']:.1f}{'*' if bpm_changed else ''}"
                        )
            except Exception as e:
                print(f"[WS] Re-analysis error: {e}")
            await asyncio.sleep(8.0)

    scheduler.set_send_callback(send_notes)

    try:
        await ws.send_text(json.dumps({
            "type": "status",
            "message": "Connected to Bandmate server. Start playing!"
        }))

        while True:
            data = await ws.receive()

            if data.get("type") == "websocket.disconnect":
                break

            # Text messages: JSON control commands
            if "text" in data:
                try:
                    msg = json.loads(data["text"])

                    if msg.get("type") == "keep_jamming":
                        # User wants to resume after 14s silence stop
                        if session_stopped:
                            session_stopped = False
                            generation_started = True
                            analyzer.reset_silence()
                            conductor.set_silence_state(0.0)
                            scheduler.start()
                            if reanalysis_task is None or reanalysis_task.done():
                                reanalysis_task = asyncio.create_task(_reanalysis_loop())
                            print("[WS] Keep jamming — scheduler restarted.")

                    elif msg.get("type") == "genre":
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
                        print(f"[WS] start_generation received, genre={genre}")

                        # Run full-buffer analysis in a thread so it doesn't block
                        # the async event loop (librosa yin + beat_track are CPU-bound).
                        # Meanwhile send keepalive pings so Render's proxy (50s idle
                        # timeout) doesn't close the WebSocket before notes arrive.
                        loop = asyncio.get_event_loop()
                        analysis_future = loop.run_in_executor(
                            None, analyzer.finalize_analysis
                        )
                        try:
                            while not analysis_future.done():
                                await ws.send_text(json.dumps({
                                    "type": "status",
                                    "message": "Analyzing your playing..."
                                }))
                                await asyncio.wait_for(
                                    asyncio.shield(analysis_future), timeout=5.0
                                )
                        except asyncio.TimeoutError:
                            pass  # still running — loop again and ping
                        except Exception as e:
                            print(f"[WS] Analysis ping error: {e}")

                        try:
                            final = await analysis_future
                        except Exception as e:
                            print(f"[WS] finalize_analysis error: {e}")
                            final = {'key': 'A', 'bpm': 100.0, 'chord_root': 'A'}

                        conductor.update(
                            key=final['key'],
                            bpm=final['bpm'],
                            genre=genre,
                            energy=conductor.energy
                        )
                        print(f"[WS] Start generation: key={final['key']}, bpm={final['bpm']:.1f}, genre={genre}")
                        if not generation_started:
                            generation_started = True
                            scheduler.start()
                            reanalysis_task = asyncio.create_task(_reanalysis_loop())
                            print("[WS] Buffer scheduler started.")

                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    print(f"[WS] Text handler error: {e}")

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

                    silence_duration = analysis.get("silence_duration", 0.0)
                    conductor.set_silence_state(silence_duration)
                    # Only update energy per-chunk; key+BPM are set by
                    # finalize_analysis() (start) and analyze_recent() (periodic).
                    conductor.update(
                        key=conductor.key,
                        bpm=conductor.bpm,
                        genre=genre,
                        energy=analysis["energy"]
                    )

                    # 14-second silence rule — stop band and notify frontend
                    if generation_started and not session_stopped and silence_duration >= 14.0:
                        session_stopped = True
                        generation_started = False
                        scheduler.stop()
                        if reanalysis_task and not reanalysis_task.done():
                            reanalysis_task.cancel()
                        print(f"[WS] 14s silence detected — stopping band.")
                        try:
                            await ws.send_text(json.dumps({"type": "session_stop"}))
                        except Exception:
                            pass

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
        if reanalysis_task and not reanalysis_task.done():
            reanalysis_task.cancel()
        analyzer.reset()


# ── Serve built frontend (production) ────────────────────────────────────────
# StaticFiles(html=True) mounted at "/" serves any matching file (drums, assets,
# audio-processor.js) and falls back to index.html for unknown paths (SPA routes).
# It is registered AFTER all API/WS routes so those always take priority.
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )
