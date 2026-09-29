"use client";

import { Modal } from "@/components/ui/Modal";
import type { MicDevice } from "@/lib/audio/useMicCapture";

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
  devices: MicDevice[];
  selectedDeviceId: string;
  onSelectDevice: (deviceId: string) => void;
  voices: SpeechSynthesisVoice[];
  selectedVoiceUri: string;
  onSelectVoice: (uri: string) => void;
  sessionActive: boolean;
}

export function SettingsPanel({
  open,
  onClose,
  devices,
  selectedDeviceId,
  onSelectDevice,
  voices,
  selectedVoiceUri,
  onSelectVoice,
  sessionActive,
}: SettingsPanelProps) {
  return (
    <Modal open={open} onClose={onClose} title="Settings">
      <div className="flex flex-col gap-5">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Microphone</label>
          <select
            value={selectedDeviceId}
            onChange={(e) => onSelectDevice(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground"
          >
            <option value="">System default</option>
            {devices.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            System Voice (TTS fallback / replay)
          </label>
          <select
            value={selectedVoiceUri}
            onChange={(e) => onSelectVoice(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground"
          >
            <option value="">Browser default</option>
            {voices.map((v) => (
              <option key={v.voiceURI} value={v.voiceURI}>
                {v.name} ({v.lang})
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-subtle-foreground">
            Primary audio streams directly from ElevenLabs. This voice is used as an immediate fallback or for replay.
          </p>
        </div>

        {sessionActive && (
          <p className="text-xs text-subtle-foreground">Stop the session to change these settings.</p>
        )}
      </div>
    </Modal>
  );
}
