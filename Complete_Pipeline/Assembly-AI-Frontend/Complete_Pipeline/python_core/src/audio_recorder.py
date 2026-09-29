import pyaudio
import sys
import time
import uuid
import os
from typing import Iterator
from contracts import AudioChunk


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 512
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.format = pyaudio.paInt16
        self.p = pyaudio.PyAudio()

    def record_until_release(self, trigger_key: str = "m") -> Iterator[AudioChunk]:
        """
        Windows-compatible microphone recorder.

        Press M + Enter to start recording.
        Press M + Enter again to stop recording.
        """

        print(f"Press '{trigger_key.upper()}' then Enter to start recording...")

        input()

        print(
            f"\n[RECORDING STARTED] Speak now. "
            f"Press '{trigger_key.upper()}' + Enter again to stop."
        )

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

        try:
            while True:
                data = stream.read(
                    self.chunk_size,
                    exception_on_overflow=False
                )

                timestamp_ms = int(
                    (time.time() - start_time) * 1000
                )

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

                # Windows-friendly stop check
                if os.name == "nt":
                    import msvcrt

                    if msvcrt.kbhit():
                        key = msvcrt.getwch()

                        if key.lower() == trigger_key.lower():
                            break

                        # If Enter was pressed, ignore it
                        if key == "\r":
                            continue

        finally:
            print("\n[RECORDING STOPPED]")

            if stream.is_active():
                stream.stop_stream()

            stream.close()

    def terminate(self):
        self.p.terminate()


if __name__ == "__main__":
    recorder = AudioRecorder()

    try:
        for chunk in recorder.record_until_release(trigger_key="m"):
            pass
    finally:
        recorder.terminate()