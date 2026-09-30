from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "mic_test.wav"


def main() -> None:
    device = sd.query_devices(kind="input")
    default_index = sd.default.device[0]
    name = str(device.get("name") or "Default input")
    hostapi_index = int(device.get("hostapi") or 0)
    hostapi_name = str(sd.query_hostapis(hostapi_index).get("name") or "unknown")
    sample_rate = int(round(float(device.get("default_samplerate") or 48000)))
    channels = 1
    seconds = 5

    print("SMARTIS microphone diagnostic")
    print(f"Device     : {name}")
    print(f"Device idx : {default_index}")
    print(f"Host API   : {hostapi_name}")
    print(f"Sample rate: {sample_rate} Hz")
    print(f"Recording  : {seconds} seconds")
    print("Speak normally into the selected microphone...\n")

    audio = sd.rec(
        int(sample_rate * seconds),
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
    )
    sd.wait()
    mono = np.asarray(audio[:, 0], dtype=np.int16)
    normalized = mono.astype(np.float32) / 32768.0
    peak = float(np.max(np.abs(normalized)))
    rms = float(np.sqrt(np.mean(np.square(normalized))))
    peak_db = 20 * math.log10(max(peak, 1e-9))
    rms_db = 20 * math.log10(max(rms, 1e-9))

    with wave.open(str(OUT), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(mono.tobytes())

    print(f"Peak       : {peak_db:.1f} dBFS")
    print(f"RMS        : {rms_db:.1f} dBFS")
    print(f"Saved WAV  : {OUT}")

    if rms_db < -45:
        print("RESULT    : WARNING — capture is effectively silent.")
        print("Next checks: Windows Settings > Privacy & security > Microphone, microphone mute switch, and the selected input device/level.")
        print("Available input devices:")
        try:
            for idx, item in enumerate(sd.query_devices()):
                if int(item.get("max_input_channels", 0) or 0) > 0:
                    print(f"  [{idx}] {item.get('name')} | {item.get('default_samplerate')} Hz | inputs={item.get('max_input_channels')}")
        except Exception as exc:
            print(f"  Could not enumerate devices: {exc}")
    else:
        print("RESULT    : OK — real microphone signal was captured.")


if __name__ == "__main__":
    main()
