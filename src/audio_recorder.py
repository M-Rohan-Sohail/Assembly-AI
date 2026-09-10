import pyaudio
import sys
import select
import tty
import termios
import time
import uuid
from typing import Iterator
from contracts import AudioChunk

class AudioRecorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1, chunk_size: int = 512):
        """
        Initializes the AudioRecorder.
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.format = pyaudio.paInt16
        self.p = pyaudio.PyAudio()

    def record_until_release(self, trigger_key: str = 'm') -> Iterator[AudioChunk]:
        """
        Waits for the trigger key to be pressed, then yields AudioChunks until the key is pressed again.
        """
        print(f"Press '{trigger_key.upper()}' to start recording...")
        
        # Save terminal settings to restore them later
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        
        try:
            # Set to cbreak mode to read single characters instantly without hitting Enter
            tty.setcbreak(sys.stdin.fileno())
            
            # Wait for start key
            while True:
                key = sys.stdin.read(1)
                if key.lower() == trigger_key.lower():
                    break
                
            print(f"\n[RECORDING STARTED] Speak now. Press '{trigger_key.upper()}' again to stop.")
            session_id = str(uuid.uuid4())
            sequence = 0
            
            stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            start_time = time.time()
            
            while True:
                # Non-blocking check for stop key
                if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                    key = sys.stdin.read(1)
                    if key.lower() == trigger_key.lower():
                        break
                        
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                timestamp_ms = int((time.time() - start_time) * 1000)
                
                chunk = AudioChunk(
                    session_id=session_id,
                    sequence=sequence,
                    timestamp_ms=timestamp_ms,
                    payload=data,
                    sample_rate=self.sample_rate,
                    channels=self.channels
                )
                yield chunk
                sequence += 1
                
        finally:
            print(f"\n[RECORDING STOPPED]")
            # Restore terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            
            if 'stream' in locals() and stream.is_active():
                stream.stop_stream()
                stream.close()

    def terminate(self):
        self.p.terminate()

if __name__ == "__main__":
    recorder = AudioRecorder()
    try:
        for chunk in recorder.record_until_release(trigger_key='m'):
            pass
    finally:
        recorder.terminate()
