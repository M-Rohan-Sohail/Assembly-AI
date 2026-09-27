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
  demoMode: boolean;
  onToggleDemoMode: (value: boolean) => void;
  wsUrlConfigured: boolean;
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
  demoMode,
  onToggleDemoMode,
  wsUrlConfigured,
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
            Playback voice (demo mode)
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
        </div>

        <div className="flex items-start justify-between gap-4 rounded-lg border border-border bg-background px-3 py-3">
          <div>
            <p className="text-sm font-medium text-foreground">Demo mode</p>
            <p className="text-xs text-subtle-foreground">
              {wsUrlConfigured
                ? "Simulate the pipeline locally instead of using the configured backend."
                : "No NEXT_PUBLIC_WS_URL configured — demo mode is the only option."}
            </p>
          </div>
          <input
            type="checkbox"
            checked={demoMode || !wsUrlConfigured}
            disabled={!wsUrlConfigured || sessionActive}
            onChange={(e) => onToggleDemoMode(e.target.checked)}
            className="mt-1 h-4 w-4 accent-[var(--accent)]"
          />
        </div>
        {sessionActive && (
          <p className="text-xs text-subtle-foreground">Stop the session to change these settings.</p>
        )}
      </div>
    </Modal>
  );
}
