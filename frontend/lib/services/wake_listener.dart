import 'dart:async';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'backend_socket.dart';

/// Continuously listens for the wake word.
///
/// IMPORTANT: this used to run two `AudioRecorder`s at the same time
/// (offset by half a window) to avoid clipping a wake word that happened to
/// fall on a window boundary. In practice, opening two simultaneous capture
/// sessions against the same physical microphone caused the underlying
/// Windows audio stack to hand back a real signal to only a sliver of each
/// clip (a single loud transient right at the start) while the rest of the
/// buffer was left essentially silent — exactly the "peak ~0dB / rms ~-90dB"
/// pattern that shows up in the backend logs, even though the OS's own
/// recorder captures the same microphone perfectly fine on its own.
///
/// The fix is to go back to a SINGLE recorder and simply never let it sit
/// idle: the next window starts recording immediately after the previous
/// one stops, and the previous chunk is shipped to the backend in the
/// background (not awaited), so the mic is effectively never idle and there
/// is never more than one capture session open at a time.
class WakeListener {
  final AudioRecorder recorderA = AudioRecorder();
  final BackendSocket backend;
  bool running = false;
  int counter = 0;
  int _generation = 0;
  static const Duration _windowLength = Duration(milliseconds: 1800);
  WakeListener(this.backend);

  Future<void> start({
    required void Function(String) onStatus,
    required void Function(Map<String, dynamic>) onWake,
    required void Function(double) onLevel,
  }) async {
    if (running) return;
    if (!await recorderA.hasPermission()) {
      onStatus('اجازه دسترسی به میکروفون داده نشده');
      return;
    }
    running = true;
    final myGeneration = ++_generation;
    onStatus('در حال گوش دادن به «اسمارتیز»...');
    await _listenLoop(myGeneration, onWake, onLevel);
  }

  Future<void> _listenLoop(
    int generation,
    void Function(Map<String, dynamic>) onWake,
    void Function(double) onLevel,
  ) async {
    while (running && generation == _generation) {
      String? path;
      try {
        final dir = await getTemporaryDirectory();
        path = '${dir.path}\\smartis_wake_${counter++}.wav';
        await recorderA.start(
          // autoGain/echoCancel/noiseSuppress route capture through Windows'
          // audio-processing (APO) chain, which on some Windows 10 builds
          // silently hands back an almost-empty stream (one brief buffer at
          // open, then digital silence) even though the raw mic is fine —
          // exactly the symptom seen in the backend logs. Forcing a specific
          // sampleRate/numChannels can trigger the same kind of silent
          // software resample/downmix failure. Neither is actually needed:
          // faster-whisper decodes whatever format comes in, so we just take
          // whatever the device natively gives us, unprocessed.
          const RecordConfig(
            encoder: AudioEncoder.wav,
            autoGain: false,
            echoCancel: false,
            noiseSuppress: false,
          ),
          path: path,
        );
      } catch (_) {
        await Future<void>.delayed(const Duration(milliseconds: 200));
        continue;
      }
      final until = DateTime.now().add(_windowLength);
      while (running && generation == _generation && DateTime.now().isBefore(until)) {
        try {
          final a = await recorderA.getAmplitude();
          onLevel(((a.current + 60) / 60).clamp(0.0, 1.0).toDouble());
        } catch (_) {}
        await Future<void>.delayed(const Duration(milliseconds: 70));
      }
      String? saved;
      try {
        saved = await recorderA.stop();
      } catch (_) {
        saved = null;
      }
      onLevel(0.0);
      if (!running || generation != _generation) return;
      // Fire recognition in the background: do NOT await it here. The loop
      // above immediately starts the next recording window, so the mic is
      // never left idle while we wait on the network/STT — and, crucially,
      // there is only ever one capture session open at a time.
      if (saved != null) {
        unawaited(_checkChunk(saved, generation, onWake));
      }
    }
  }

  Future<void> _checkChunk(
    String path,
    int generation,
    void Function(Map<String, dynamic>) onWake,
  ) async {
    try {
      final result = await backend.wakeAudio(path);
      if (!running || generation != _generation) return;
      if (result['detected'] == true) {
        _generation++; // invalidates the listen loop so it stops cleanly
        running = false;
        try {
          if (await recorderA.isRecording()) await recorderA.stop();
        } catch (_) {}
        onWake(result);
      }
    } catch (_) {
      /* transient network/backend errors: just keep listening */
    }
  }

  Future<void> stop() async {
    running = false;
    _generation++;
    try {
      if (await recorderA.isRecording()) await recorderA.stop();
    } catch (_) {}
  }

  Future<void> dispose() async {
    await stop();
    await recorderA.dispose();
  }
}
