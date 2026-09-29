import os
import sys
import time
import base64
import json
import asyncio
from typing import Dict, Any
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# [PERSON 3] Make `src.*` importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.endpointing import EndpointingEngine
from src.assemblyai_service import AssemblyAIService
from src.orchestrator.runtime import Person3Runtime
from src.orchestrator.repair_clients import create_repair_client

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    loop = asyncio.get_running_loop()
    outgoing_queue = asyncio.Queue()
    
    async def send_worker():
        while True:
            msg = await outgoing_queue.get()
            try:
                await websocket.send_json(msg)
            except Exception as e:
                print("Error sending message:", e)
                break
    
    sender_task = asyncio.create_task(send_worker())
    
    def emit_sync(msg: dict):
        asyncio.run_coroutine_threadsafe(outgoing_queue.put(msg), loop)

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        print("ERROR: ASSEMBLYAI_API_KEY not set.")
        emit_sync({"type": "pipeline.error", "stage": "init", "message": "ASSEMBLYAI_API_KEY not set"})
        return
        
    endpointer = EndpointingEngine(min_silence_duration_ms=1500)
    aai_service = AssemblyAIService(api_key=api_key)
    audio_buffer = bytearray()
    
    # Custom sink to stream audio back
    def ws_sink(audio_event):
        msg = {
            "type": "audio.chunk",
            "audio_chunk_b64": base64.b64encode(audio_event["payload"]).decode("utf-8"),
            "is_final": audio_event.get("is_final", False)
        }
        emit_sync(msg)
        
    person3 = Person3Runtime(repair=create_repair_client(), sink=ws_sink)
    
    # Monkey-patch orchestrator to emit events
    def on_repair(sid, uid, orig, rep):
        emit_sync({
            "type": "repair.completed",
            "version": 1,
            "session_id": sid,
            "utterance_id": uid,
            "original_text": orig,
            "repaired_text": rep or "",
            "confidence": 1.0,
            "changes": []
        })
    def on_validation(sid, uid, approved, source, spoken_text):
        emit_sync({
            "type": "validation.result",
            "session_id": sid,
            "utterance_id": uid,
            "approved": approved,
            "reason": "",
            "source": source,
            "spoken_text": spoken_text
        })
        emit_sync({"type": "stage.update", "stage": "speaking"})
        
    person3.orchestrator._on_repair = on_repair
    person3.orchestrator._on_validation = on_validation

    def handle_transcript(event):
        if event['is_final']:
            emit_sync({
                "type": "transcript.final",
                "version": 1,
                "session_id": event['session_id'],
                "utterance_id": event['utterance_id'],
                "text": event['text'],
                "is_final": True,
                "confidence": event['confidence'],
                "start_ms": 0,
                "end_ms": 0,
            })
            emit_sync({"type": "stage.update", "stage": "repairing"})
            person3.submit(event)
        else:
            emit_sync({
                "type": "transcript.partial",
                "version": 1,
                "session_id": event['session_id'],
                "utterance_id": event['utterance_id'],
                "text": event['text'],
                "is_final": False,
                "confidence": event['confidence'],
                "start_ms": 0,
                "end_ms": 0,
            })

    aai_service.on_transcript_event = handle_transcript

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg["type"] == "session.start":
                aai_service.start_session(session_id=msg["session_id"])
                endpointer.reset()
                audio_buffer.clear()
                emit_sync({"type": "stage.update", "stage": "listening"})
                
            elif msg["type"] == "audio.chunk":
                payload = base64.b64decode(msg["payload_b64"])
                chunk = {
                    'session_id': msg['session_id'],
                    'sequence': msg['sequence'],
                    'payload': payload,
                    'timestamp_ms': msg['timestamp_ms']
                }
                
                vad_event, endpoint_decision = endpointer.process_chunk(chunk)
                
                audio_buffer.extend(payload)
                if len(audio_buffer) >= 3200:
                    aai_service.send_audio(bytes(audio_buffer))
                    audio_buffer.clear()
                    
                if endpoint_decision and endpoint_decision['finalized']:
                    aai_service.force_endpoint()
                    
            elif msg["type"] == "session.stop":
                if len(audio_buffer) > 0:
                    if len(audio_buffer) < 1600:
                        audio_buffer.extend(b'\x00' * (1600 - len(audio_buffer)))
                    aai_service.send_audio(bytes(audio_buffer))
                    audio_buffer.clear()
                aai_service.force_endpoint()
                aai_service.flush_final()
                break
                
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        aai_service.end_session()
        person3.close()

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
