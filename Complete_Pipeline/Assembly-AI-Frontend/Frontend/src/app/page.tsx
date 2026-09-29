"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Copy, Mic, MicOff, RotateCcw, Trash2, Check } from "lucide-react";
import { TopBar } from "@/components/session/TopBar";
import { RecordButton } from "@/components/session/RecordButton";
import { TranscriptPanel } from "@/components/session/TranscriptPanel";
import { ValidationFlag } from "@/components/session/ValidationFlag";
import { HistoryList } from "@/components/session/HistoryList";
import { SettingsPanel } from "@/components/session/SettingsPanel";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { useMicCapture } from "@/lib/audio/useMicCapture";
import { useSpeechPlayback } from "@/lib/audio/useSpeechPlayback";
import { useClearVoiceSession } from "@/lib/ws/useClearVoiceSession";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL;

export default function Home() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [selectedVoiceUri, setSelectedVoiceUri] = useState("");
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [demoModeOverride, setDemoModeOverride] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const load = () => setVoices(window.speechSynthesis.getVoices());
    load();
    window.speechSynthesis.onvoiceschanged = load;
    return () => {
      window.speechSynthesis.onvoiceschanged = null;
    };
  }, []);

  const selectedVoice = useMemo(
    () => voices.find((v) => v.voiceURI === selectedVoiceUri) ?? null,
    [voices, selectedVoiceUri]
  );

  const playback = useSpeechPlayback();

  const handleAudioOutputChunk = useCallback(
    (b64: string, isFinal: boolean) => playback.playPcmChunk(b64, isFinal),
    [playback]
  );

  const handleDemoSpeak = useCallback(
    (text: string) => playback.speakWithBrowserTts(text, selectedVoice),
    [playback, selectedVoice]
  );

  const session = useClearVoiceSession({
    wsUrl: WS_URL,
    useDemoMode: demoModeOverride || !WS_URL,
    onAudioOutputChunk: handleAudioOutputChunk,
    onDemoSpeak: handleDemoSpeak,
  });

  const mic = useMicCapture({ onAudioChunk: session.sendAudioChunk });

  const sessionActive = session.state.sessionId !== null;

  const handleToggleSession = useCallback(async () => {
    if (sessionActive) {
      session.stopSession();
      mic.stop();
      playback.cancel();
    } else {
      playback.playPcmChunk("", false); // Unlock AudioContext on user gesture
      session.startSession();
      await mic.start(selectedDeviceId || undefined);
    }
  }, [sessionActive, session, mic, playback, selectedDeviceId]);

  const handleReplay = useCallback(() => {
    const last = session.state.current ?? session.state.history[0];
    if (!last) return;
    void playback.speakWithBrowserTts(last.repairedText || last.rawText, selectedVoice);
  }, [session.state.current, session.state.history, playback, selectedVoice]);

  const handleCopy = useCallback(async () => {
    const text = session.state.current?.repairedText;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard permission denied; ignore
    }
  }, [session.state.current]);

  const handleClearSession = useCallback(() => {
    session.clearHistory();
  }, [session]);

  const current = session.state.current;

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col">
      <TopBar
        stage={session.state.stage}
        connection={session.state.connection}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <main className="flex flex-1 flex-col gap-6 px-6 py-8">
        {(session.state.error || mic.error) && (
          <div className="rounded-lg border border-loss/40 bg-loss-bg px-4 py-2.5 text-sm text-loss">
            {session.state.error ?? mic.error}
          </div>
        )}

        <div className="flex flex-col items-center py-4">
          <RecordButton
            isActive={sessionActive}
            stage={session.state.stage}
            analyser={mic.analyserRef.current}
            onToggle={handleToggleSession}
          />
        </div>

        <div className="flex flex-col gap-4 sm:flex-row">
          <TranscriptPanel
            title="Raw speech"
            text={current?.rawText ?? ""}
            placeholder="Your speech will appear here as you talk."
            isFinal={current?.isFinal}
          />
          <TranscriptPanel
            title="Repaired"
            text={current?.repairedText ?? ""}
            placeholder="The cleaned-up version will appear here."
            accent="accent"
            isFinal
            headerRight={
              current?.repairedText ? (
                <IconButton label="Copy repaired transcript" onClick={handleCopy}>
                  {copied ? <Check size={15} className="text-profit" /> : <Copy size={15} />}
                </IconButton>
              ) : undefined
            }
          >
            <ValidationFlag
              approved={current?.approved ?? null}
              reason={current?.reason ?? null}
              source={current?.source ?? null}
            />
          </TranscriptPanel>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-2">
          <IconButton
            label={session.state.isMuted ? "Unmute" : "Mute"}
            active={session.state.isMuted}
            onClick={session.toggleMute}
            disabled={!sessionActive}
          >
            {session.state.isMuted ? <MicOff size={16} /> : <Mic size={16} />}
          </IconButton>
          <Button variant="ghost" size="sm" onClick={handleReplay} disabled={!current}>
            <RotateCcw size={14} />
            Replay
          </Button>
          <Button variant="ghost" size="sm" onClick={handleClearSession} disabled={session.state.history.length === 0}>
            <Trash2 size={14} />
            Clear history
          </Button>
        </div>

        <HistoryList items={session.state.history} />
      </main>

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        devices={mic.devices}
        selectedDeviceId={selectedDeviceId}
        onSelectDevice={setSelectedDeviceId}
        voices={voices}
        selectedVoiceUri={selectedVoiceUri}
        onSelectVoice={setSelectedVoiceUri}
        demoMode={demoModeOverride}
        onToggleDemoMode={setDemoModeOverride}
        wsUrlConfigured={Boolean(WS_URL)}
        sessionActive={sessionActive}
      />
    </div>
  );
}
