import 'dart:convert';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:window_manager/window_manager.dart';

import 'services/backend_socket.dart';
import 'services/wake_listener.dart';
import 'widgets/smartis_log_panel.dart';
import 'widgets/smartis_orb.dart';

class SmartisApp extends StatefulWidget {
  const SmartisApp({super.key});

  @override
  State<SmartisApp> createState() => _SmartisAppState();
}

class _SmartisAppState extends State<SmartisApp> {
  static const Color gold = Color(0xFFFFD700);

  final BackendSocket backend = BackendSocket();
  final AudioPlayer player = AudioPlayer();
  late final WakeListener wakeListener;

  SmartisVisualState visualState = SmartisVisualState.idle;
  double audioLevel = 0.0;

  String status = 'در حال اتصال...';
  String transcript = 'بگو «اسمارتیز»';
  String detectedLanguage = '';
  String mode = '...';

  bool recording = false;
  bool processing = false;
  bool shuttingDown = false;

  final List<String> logs = <String>[];

  @override
  void initState() {
    super.initState();

    wakeListener = WakeListener(backend);

    backend.connect(
      onMessage: (message) {
        if (!mounted) return;
        if (message['type'] == 'backend_ready') {
          final online = message['internet'] == true;
          final googleStt = message['online_stt_ready'] == true;
          setState(() {
            mode = online ? 'ONLINE' : 'OFFLINE';
            status = online
                ? 'آنلاین — آماده شنیدن «اسمارتیز»'
                : 'آفلاین — آماده شنیدن «اسمارتیز»';
          });
          _log('Backend ready • internet=$online • google_stt=$googleStt');
        }
      },
      onError: (error) {
        _log('Backend error: $error');
        if (mounted) {
          setState(() => status = 'Backend پیدا نشد');
        }
      },
    );

    Future<void>.delayed(
      const Duration(milliseconds: 700),
      _armWake,
    );
  }

  void _log(String message) {
    if (!mounted) return;
    final now = DateTime.now();
    final stamp =
        '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}';
    setState(() {
      logs.add('[$stamp] $message');
      if (logs.length > 120) {
        logs.removeRange(0, logs.length - 120);
      }
    });
  }

  Future<void> _armWake() async {
    if (!mounted || shuttingDown || processing || recording) return;

    setState(() {
      visualState = SmartisVisualState.listening;
      audioLevel = 0.0;
    });
    _log('Wake listener armed');

    await wakeListener.start(
      onStatus: (message) {
        if (!mounted) return;
        setState(() {
          status = message;
          visualState = SmartisVisualState.listening;
        });
      },
      onLevel: (level) {
        if (!mounted) return;
        setState(() => audioLevel = level);
      },
      onWake: _onWake,
    );
  }

  Future<void> _onWake(Map<String, dynamic> result) async {
    if (!mounted) return;

    await wakeListener.stop();

    final language = (result['language'] ?? 'fa').toString();
    detectedLanguage = language;
    final reply = language == 'fa' ? 'جانم' : "Yes, I'm listening.";

    setState(() {
      visualState = SmartisVisualState.speaking;
      status = reply;
      transcript = (result['text'] ?? '').toString();
      if (transcript.isEmpty) transcript = 'Smartis';
      mode = result['offline'] == true ? 'OFFLINE' : 'ONLINE';
    });

    _log(
      'Wake detected • lang=$language • mode=$mode • provider=${result['provider'] ?? 'unknown'}',
    );

    await _speak(reply, language);

    if (!mounted) return;

    await Future<void>.delayed(
      const Duration(milliseconds: 220),
    );

    if (!mounted) return;

    // Command capture always records a short WAV clip and sends it to the
    // backend's /transcribe endpoint, which itself tries Google's Web Speech
    // API (via SpeechRecognition) first when online and automatically falls
    // back to the local offline Whisper model otherwise. This single path
    // replaces the old Deepgram-only live-streaming route.
    await _recordCommand();
  }

  Future<void> _recordCommand() async {
    if (processing || recording || shuttingDown) return;

    final AudioRecorder recorder = wakeListener.recorderA;

    if (!await recorder.hasPermission()) {
      if (mounted) {
        setState(() => status = 'اجازه دسترسی به میکروفون داده نشده');
      }
      return;
    }

    final dir = await getTemporaryDirectory();
    final path =
        '${dir.path}\\smartis_command_${DateTime.now().millisecondsSinceEpoch}.wav';

    try {
      // Same reasoning as the wake listener: no forced sampleRate/channels,
      // and Windows' DSP chain (autoGain/echoCancel/noiseSuppress) disabled —
      // both were candidates for silently muting audio after the first
      // buffer. faster-whisper on the backend handles whatever format the
      // device natively records in.
      await recorder.start(
        const RecordConfig(
          encoder: AudioEncoder.wav,
          autoGain: false,
          echoCancel: false,
          noiseSuppress: false,
        ),
        path: path,
      );

      setState(() {
        recording = true;
        visualState = SmartisVisualState.listening;
        audioLevel = 0.0;
        status = 'گوش می‌دهم...';
        transcript = 'صحبت کن...';
      });

      _log('Offline/file STT recording started');

      DateTime? quietSince;
      bool speechStarted = false;
      final startedAt = DateTime.now();

      while (mounted && recording) {
        final amplitude = await recorder.getAmplitude();
        final level =
            ((amplitude.current + 60.0) / 60.0).clamp(0.0, 1.0).toDouble();

        setState(() => audioLevel = level);

        if (level >= 0.060) {
          speechStarted = true;
          quietSince = null;
        } else if (speechStarted) {
          quietSince ??= DateTime.now();
        }

        final elapsed = DateTime.now().difference(startedAt);
        final quiet = quietSince == null
            ? Duration.zero
            : DateTime.now().difference(quietSince!);

        if (speechStarted &&
            elapsed > const Duration(milliseconds: 1800) &&
            quiet > const Duration(milliseconds: 1900)) {
          break;
        }

        if (elapsed > const Duration(seconds: 20)) break;

        await Future<void>.delayed(
          const Duration(milliseconds: 90),
        );
      }

      final recorded = await recorder.stop();
      _log('File audio captured; sending to STT');

      setState(() {
        recording = false;
        processing = true;
        visualState = SmartisVisualState.thinking;
        status = 'در حال تبدیل صدا به متن...';
        audioLevel = 0.0;
      });

      if (recorded == null) {
        throw Exception('Audio file was not created');
      }

      final started = DateTime.now();
      final result = await backend.transcribe(
        recorded,
        languageHint: detectedLanguage.isEmpty ? null : detectedLanguage,
      );

      _log(
        'File STT finished in ${DateTime.now().difference(started).inMilliseconds}ms • provider=${result['provider'] ?? 'unknown'}',
      );

      if (!mounted) return;

      if (result['ok'] == true) {
        final text = (result['text'] ?? '').toString().trim();
        final language =
            (result['language'] ?? detectedLanguage).toString();

        setState(() {
          transcript = text.isEmpty ? 'صدایی تشخیص داده نشد' : text;
          detectedLanguage = language;
          mode = result['offline'] == true ? 'OFFLINE' : 'ONLINE';
          status = result['offline'] == true
              ? 'تشخیص آفلاین'
              : 'تشخیص آنلاین';
        });

        if (text.isNotEmpty) {
          await _runAgent(text, language);
        }
      } else {
        setState(() {
          status =
              'خطا در تشخیص گفتار: ${result['error'] ?? 'نامشخص'}';
        });
      }
    } catch (error) {
      _log('File STT error • $error');
      if (mounted) setState(() => status = 'خطا: $error');
    } finally {
      if (mounted) {
        setState(() {
          recording = false;
          processing = false;
          visualState = SmartisVisualState.idle;
          audioLevel = 0.0;
        });
        Future<void>.delayed(
          const Duration(milliseconds: 300),
          () {
            if (mounted && !shuttingDown) _armWake();
          },
        );
      }
    }
  }

  Future<void> _runAgent(
    String text,
    String language,
  ) async {
    if (!mounted) return;

    setState(() {
      visualState = SmartisVisualState.thinking;
      status = 'در حال فکر کردن...';
    });

    try {
      _log('Agent plan started');
      final started = DateTime.now();
      final response = await backend.plan(text, language);
      _log(
        'Agent plan finished in ${DateTime.now().difference(started).inMilliseconds}ms • provider=${response['provider'] ?? 'unknown'}',
      );

      if (response['ok'] != true) {
        setState(() => status = 'Agent خطا داد: ${response['error'] ?? ''}');
        return;
      }

      final plan = Map<String, dynamic>.from(
        response['plan'] ?? {},
      );

      if (plan['needs_confirmation'] == true) {
        setState(() => status = 'این عملیات نیاز به تأیید دارد');
        await _speak(
          language == 'fa'
              ? 'برای این عملیات تأیید شما لازم است.'
              : 'I need your confirmation for this action.',
          language,
        );
        return;
      }

      _log('Tool execution started');
      final executeStarted = DateTime.now();
      final execution = await backend.execute(plan);
      _log(
        'Tool execution finished in ${DateTime.now().difference(executeStarted).inMilliseconds}ms',
      );

      if (execution['needs_confirmation'] == true) {
        setState(() => status = 'برای اجرای این عملیات تأیید لازم است');
        await _speak(
          language == 'fa'
              ? 'برای این عملیات تأیید شما لازم است.'
              : 'I need your confirmation for this action.',
          language,
        );
        return;
      }

      final reply = (plan['reply'] ?? '').toString();

      if (execution['ok'] == true) {
        setState(() => status = 'انجام شد');

        final results =
            (execution['results'] as List?) ?? const [];
        final spokenChunks = <String>[];

        for (final item in results) {
          if (item is Map) {
            final itemResult = item['result'];
            if (itemResult is Map) {
              final spoken =
                  (itemResult['speak'] ?? '').toString().trim();
              if (spoken.isNotEmpty) spokenChunks.add(spoken);
            }
          }
        }

        if (spokenChunks.isNotEmpty) {
          await _speak(
            spokenChunks.join('. '),
            language,
          );
        } else if (reply.isNotEmpty) {
          await _speak(reply, language);
        }
      } else {
        setState(() => status = 'خطا در اجرا');
        await _speak(
          language == 'fa'
              ? 'در اجرای درخواست مشکلی پیش آمد.'
              : 'There was a problem executing the request.',
          language,
        );
      }
    } catch (error) {
      _log('Agent error • $error');
      if (mounted) setState(() => status = 'خطا در Agent: $error');
    }
  }

  Future<void> _speak(
    String text,
    String? language,
  ) async {
    if (!mounted) return;

    setState(() {
      visualState = SmartisVisualState.speaking;
      audioLevel = 0.0;
    });

    final started = DateTime.now();
    final result = await backend.speak(text, language);
    _log(
      'TTS finished in ${DateTime.now().difference(started).inMilliseconds}ms • provider=${result['provider'] ?? 'unknown'}',
    );

    if (result['ok'] != true) {
      if (mounted) {
        setState(() => status = 'خطا در TTS: ${result['error'] ?? ''}');
      }
      return;
    }

    final encoded = result['audio_base64']?.toString();
    if (encoded != null && encoded.isNotEmpty) {
      await player.play(
        BytesSource(
          base64Decode(encoded),
          mimeType: result['mime_type']?.toString(),
        ),
      );
    }
  }

  @override
  void dispose() {
    shuttingDown = true;
    wakeListener.dispose();
    player.dispose();
    backend.dispose();
    super.dispose();
  }

  String _stateText() {
    switch (visualState) {
      case SmartisVisualState.idle:
        return 'بگو «اسمارتیز»';
      case SmartisVisualState.listening:
        return recording ? 'گوش می‌دهم...' : 'در حال شنیدن...';
      case SmartisVisualState.thinking:
        return 'دارم فکر می‌کنم...';
      case SmartisVisualState.speaking:
        return 'دارم صحبت می‌کنم...';
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(useMaterial3: true),
      home: Scaffold(
        backgroundColor: Colors.transparent,
        body: GestureDetector(
          behavior: HitTestBehavior.translucent,
          onPanStart: (_) => windowManager.startDragging(),
          child: SafeArea(
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    IconButton(
                      tooltip: 'بستن',
                      onPressed: () => windowManager.close(),
                      icon: const Icon(
                        Icons.close_rounded,
                        color: gold,
                      ),
                    ),
                    const SizedBox(width: 10),
                  ],
                ),
                // The orb widget paints itself at a fixed 360x360 size, but
                // the window can be resized down to its minimum (or the
                // content below can grow, e.g. long transcripts). Wrapping
                // it in Expanded+FittedBox lets it shrink to whatever space
                // is actually left instead of forcing the Column to be
                // taller than the window — which is what was causing the
                // window to grow and the yellow/black "overflowed" warning
                // bar to appear at the bottom.
                Expanded(
                  child: Center(
                    child: FittedBox(
                      fit: BoxFit.contain,
                      child: SmartisOrb(
                        state: visualState,
                        level: audioLevel,
                      ),
                    ),
                  ),
                ),
                const Text(
                  'S M A R T I S',
                  style: TextStyle(
                    fontSize: 25,
                    letterSpacing: 8,
                    fontWeight: FontWeight.w600,
                    color: gold,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  _stateText(),
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 12,
                    color: gold,
                  ),
                ),
                const SizedBox(height: 7),
                Text(
                  status,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Colors.white.withOpacity(.8),
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  'حالت: $mode',
                  style: TextStyle(
                    color: gold.withOpacity(.76),
                    fontSize: 11,
                    letterSpacing: 1,
                  ),
                ),
                if (detectedLanguage.isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(
                    detectedLanguage == 'fa'
                        ? 'فارسی'
                        : detectedLanguage == 'en'
                            ? 'English'
                            : detectedLanguage,
                    style: const TextStyle(
                      color: gold,
                      fontSize: 11,
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                Container(
                  margin: const EdgeInsets.symmetric(horizontal: 40),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 14,
                  ),
                  decoration: BoxDecoration(
                    border: Border.all(
                      color: gold.withOpacity(.24),
                    ),
                    borderRadius: BorderRadius.circular(18),
                    color: Colors.black.withOpacity(.24),
                  ),
                  child: Text(
                    transcript,
                    textAlign: TextAlign.center,
                    textDirection: TextDirection.rtl,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 15),
                  ),
                ),
                const SizedBox(height: 10),
                SmartisLogPanel(entries: logs),
                const SizedBox(height: 10),
                Text(
                  'Smartis • فارسی / English • Auto Online / Offline',
                  style: TextStyle(
                    fontSize: 10,
                    color: gold.withOpacity(.58),
                    letterSpacing: .6,
                  ),
                ),
                const SizedBox(height: 6),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
