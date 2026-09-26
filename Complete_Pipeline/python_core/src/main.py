import os
import sys  # [PERSON 3]
import time
import wave
from datetime import datetime
from pathlib import Path  # [PERSON 3]
from dotenv import load_dotenv
from audio_recorder import AudioRecorder
from endpointing import EndpointingEngine
from assemblyai_service import AssemblyAIService
from contracts import TranscriptEvent


# [PERSON 3] Make `src.*` importable when this file is run as `python src/main.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.orchestrator.runtime import Person3Runtime  # [PERSON 3]
from src.orchestrator.repair_clients import create_repair_client  # [PERSON 3]

# Keep track of current session id and partial text for file saving
current_session_txt_path = ""
current_partial_text = ""
person3 = None  # [PERSON 3] speech-output pipeline, created in main()

def handle_transcript(event: TranscriptEvent):
    global current_session_txt_path, current_partial_text
    if event['is_final']:
        final_text = f"[FINAL] {event['text']} (Confidence: {event['confidence']})"
        print(f"\n{final_text}")
        
        # Save both Partial and Clean to output folder
        if current_session_txt_path:
            partial_display = current_partial_text if current_partial_text else event['text']
            with open(current_session_txt_path, "a", encoding="utf-8") as f:
                f.write(f"Partial:\n{partial_display}\n\n")
                f.write(f"Clean:\n{event['text']}\n\n")
                f.write("-" * 40 + "\n\n")
            print(f"[SAVED] Appended Partial & Clean transcript to {current_session_txt_path}")
            
        # Reset partial tracking for next utterance
        current_partial_text = ""

        # [PERSON 3] repair -> validate -> speak this final transcript
        if person3:
            person3.submit(event)
    else:
        current_partial_text = event['text']
        print(f"\r[PARTIAL] {event['text']}", end="", flush=True)

def main():
    global current_session_txt_path, current_partial_text, person3  # [PERSON 3]
    load_dotenv()
    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        print("ERROR: Please set the ASSEMBLYAI_API_KEY environment variable.")
        return

    # Initialize components
    recorder = AudioRecorder(chunk_size=512)
    endpointer = EndpointingEngine(min_silence_duration_ms=1500)
    aai_service = AssemblyAIService(api_key=api_key)
    aai_service.on_transcript_event = handle_transcript
    person3 = Person3Runtime(repair=create_repair_client())  # [PERSON 3]
    
    print("\n--- ClearVoice 2.0 (Person 1 Pipeline) ---")
    
    audio_buffer = bytearray()
    all_audio_bytes = bytearray() # To save the full recording
    
    # Ensure directories exist
    os.makedirs("src/input", exist_ok=True)
    os.makedirs("src/output", exist_ok=True)
    
    try:
        # Start recording (toggles with 'm')
        for chunk in recorder.record_until_release(trigger_key='m'):
            # 1. Ensure AssemblyAI session is open for the current chunk's session
            if aai_service.current_session_id != chunk['session_id']:
                if aai_service.transcriber:
                    aai_service.end_session()
                
                aai_service.start_session(session_id=chunk['session_id'])
                endpointer.reset()
                audio_buffer.clear()
                all_audio_bytes.clear()
                
                # Set up file paths for this session
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                current_session_txt_path = f"src/output/transcript_{timestamp_str}.txt"
                current_partial_text = ""
            
            # 2. Process VAD and endpointing logic
            vad_event, endpoint_decision = endpointer.process_chunk(chunk)
            
            # 3. Stream audio to AssemblyAI
            audio_buffer.extend(chunk['payload'])
            all_audio_bytes.extend(chunk['payload']) # Store for saving later
            
            if len(audio_buffer) >= 3200:
                aai_service.send_audio(bytes(audio_buffer))
                audio_buffer.clear()
            
            # 4. Handle custom endpointing decision
            if endpoint_decision and endpoint_decision['finalized']:
                print(f"\n[ENDPOINT] Reached due to: {endpoint_decision['reason']}")
                aai_service.force_endpoint()
                
        # After recording stops, flush remaining audio
        if len(audio_buffer) > 0:
            if len(audio_buffer) < 1600:
                audio_buffer.extend(b'\x00' * (1600 - len(audio_buffer)))
            aai_service.send_audio(bytes(audio_buffer))
            audio_buffer.clear()
            
        print("\nWaiting for final transcripts from AssemblyAI...")
        # Force endpoint so AssemblyAI finalizes any speech turn currently open
        aai_service.force_endpoint()
        time.sleep(2.0)
        # Flush any transcript that remained pending
        aai_service.flush_final() 
        
        # Save the complete audio to a wav file
        if all_audio_bytes:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            wav_path = f"src/input/audio_{timestamp_str}.wav"
            with wave.open(wav_path, 'wb') as wf:
                wf.setnchannels(recorder.channels)
                wf.setsampwidth(recorder.p.get_sample_size(recorder.format))
                wf.setframerate(recorder.sample_rate)
                wf.writeframes(bytes(all_audio_bytes))
            print(f"Saved recording to {wav_path}")
            
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        if person3:  # [PERSON 3] let the last utterance finish speaking
            person3.close()
        recorder.terminate()
        aai_service.end_session()

if __name__ == "__main__":
    main()