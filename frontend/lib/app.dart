import 'dart:convert';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'services/backend_socket.dart';
import 'services/google_voice_session.dart';
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
  final GoogleVoiceSessionClient voiceClient = GoogleVoiceSessionClient();
  final AudioPlayer player = AudioPlayer();

  SmartisVisualState visualState = SmartisVisualState.idle;
  double audioLevel = 0.0;

  String status = 'در حال اتصال به سرور...';
  String transcript = 'بگو «اسمارتیز» یا «سعید»';
  String detectedLanguage = 'fa';
  String mode = 'ONLINE';

  bool processing = false;
  bool shuttingDown = false;

  final List<String> logs = <String>[];

  @override
  void initState() {
    super.initState();

    // 1. Connect to general backend WebSocket for health & agent execution
    _initBackendSocket();

    // 2. Connect to dedicated /voice WebSocket managing PyAudio & Google STT
    _initVoiceSession();
  }

  void _initBackendSocket() {
    backend.connect(
      onMessage: (message) {
        if (!mounted) return;
        if (message['type'] == 'backend_ready') {
          final online = message['internet'] == true;
          setState(() {
            mode = online ? 'ONLINE' : 'OFFLINE';
            if (status == 'در حال اتصال به سرور...') {
              status = 'متصل به سرور • در انتظار میکروفون...';
            }
          });
          _log('Backend connected • internet=$online • provider=google_stt');
        }
      },
      onError: (error) {
        _log('Backend error: $error');
        if (mounted) {
          setState(() => status = 'سرور پایتون در دسترس نیست. تلاش مجدد...');
          Future.delayed(const Duration(seconds: 3), () {
            if (mounted && !shuttingDown) {
              _initBackendSocket();
            }
          });
        }
      },
    );
  }

  void _initVoiceSession() {
    voiceClient.connect(
      onEvent: _onVoiceEvent,
      onError: (err) {
        _log('Voice connection error: $err');
        if (mounted) {
          setState(() => status = 'در حال تلاش برای اتصال صوتی...');
        }
        // Attempt reconnect after brief delay
        Future.delayed(const Duration(seconds: 3), () {
          if (mounted && !shuttingDown && !voiceClient.isConnected) {
            _initVoiceSession();
          }
        });
      },
      onDone: () {
        _log('Voice session closed');
        if (mounted) {
          setState(() => status = 'ارتباط صوتی قطع شد. تلاش مجدد...');
        }
        Future.delayed(const Duration(seconds: 3), () {
          if (mounted && !shuttingDown && !voiceClient.isConnected) {
            _initVoiceSession();
          }
        });
      },
    );
  }

  void _onVoiceEvent(Map<String, dynamic> event) {
    if (!mounted || shuttingDown) return;
    final type = event['type']?.toString();

    switch (type) {
      case 'voice_ready':
        _log('Microphone initialized');
        final pyaudioAvailable = event['pyaudio_available'] != false;
        if (!pyaudioAvailable) {
          _log('PyAudio is not available on Python backend');
          setState(() {
            status = 'خطا: PyAudio در پایتون نصب نیست';
          });
          break;
        }

        final currentMode = event['mode']?.toString() ?? 'idle';
        if (currentMode == 'wake') {
          _log('Listening for wake word');
          setState(() {
            visualState = SmartisVisualState.listening;
            status = 'در حال شنیدن... بگو «اسمارتیز» یا «سعید»';
          });
        } else {
          // If session is idle or newly connected, start wake listening
          _log('Starting wake listening...');
          setState(() {
            visualState = SmartisVisualState.listening;
            status = 'در حال شنیدن... بگو «اسمارتیز» یا «سعید»';
          });
          _startWakeListening();
        }
        break;

      case 'calibrating':
        final dur = event['duration'] ?? 0.7;
        final thresh = event['energy_threshold'];
        final threshInfo = thresh != null ? ' (threshold: $thresh)' : '';
        _log('Calibration complete ($dur s)$threshInfo');
        setState(() => status = 'کالیبراسیون صدای محیط...');
        break;

      case 'listening':
        final currentMode = event['mode']?.toString() ?? 'wake';
        if (currentMode == 'wake') {
          _log('Listening for wake word');
          setState(() {
            visualState = SmartisVisualState.listening;
            status = 'در حال شنیدن... بگو «اسمارتیز» یا «سعید»';
            transcript = 'بگو «اسمارتیز» یا «سعید»';
          });
        } else if (currentMode == 'command') {
          _log('Listening for command');
          setState(() {
            visualState = SmartisVisualState.listening;
            status = 'گوش می‌دهم... دستور خود را بگویید';
            transcript = 'صحبت کن...';
          });
        }
        break;

      case 'speech_captured':
        _log('Voice captured, processing STT...');
        setState(() {
          visualState = SmartisVisualState.thinking;
          status = 'در حال پردازش گفتار...';
        });
        break;

      case 'transcript':
        final text = event['text']?.toString() ?? '';
        final prov = event['provider']?.toString() ?? 'google';
        if (text.isNotEmpty) {
          _log('STT captured: "$text" ($prov)');
        }
        break;

      case 'wake_detected':
        _onWakeDetected(event);
        break;

      case 'wake_miss':
        final heard = event['text']?.toString() ?? '';
        if (heard.isNotEmpty) {
          _log('Heard: "$heard" (wake word not matched)');
        }
        setState(() {
          visualState = SmartisVisualState.listening;
          status = 'در حال شنیدن... بگو «اسمارتیز» یا «سعید»';
        });
        break;

      case 'command_final':
        _onCommandFinal(event);
        break;

      case 'recognition_error':
        final err = event['error']?.toString() ?? '';
        _log('Recognition notice: $err');
        // If command timed out or had error, cycle back to wake
        if (!processing) {
          Future.delayed(const Duration(milliseconds: 500), () {
            if (mounted && !shuttingDown) _startWakeListening();
          });
        }
        break;

      case 'voice_error':
        _log('Voice error: ${event['error']}');
        break;

      case 'voice_fatal':
        final errMsg = event['error']?.toString() ?? '';
        _log('Voice fatal: $errMsg');
        setState(() => status = 'میکروفون در دسترس نیست');
        break;

      case 'voice_stopped':
        break;
    }
  }

  void _log(String message) {
    if (!mounted) return;
    final now = DateTime.now();
    final stamp =
        '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}';
    setState(() {
      logs.add('[$stamp] $message');
      if (logs.length > 150) {
        logs.removeRange(0, logs.length - 150);
      }
    });
  }

  void _startWakeListening() {
    if (!mounted || shuttingDown || processing) return;
    voiceClient.startWake(language: detectedLanguage);
  }

  Future<void> _onWakeDetected(Map<String, dynamic> event) async {
    if (!mounted || shuttingDown || processing) return;

    final wakeWord = (event['wake_word'] ?? event['text'] ?? 'اسمارتیز').toString();
    _log('Wake detected: $wakeWord');
    final language = (event['language'] ?? 'fa').toString();
    detectedLanguage = language;
    final reply = language == 'fa' ? 'جانم' : "Yes, I'm listening.";

    setState(() {
      visualState = SmartisVisualState.speaking;
      status = reply;
      transcript = wakeWord;
      mode = event['offline'] == true ? 'OFFLINE' : 'ONLINE';
    });

    _log('TTS: $reply');
    await _speak(reply, language);

    if (!mounted || shuttingDown) return;

    // Small delay to clear speaker audio before microphone opens for command
    await Future.delayed(const Duration(milliseconds: 280));

    if (!mounted || shuttingDown) return;

    // Start command session on backend PyAudio
    _log('Listening for command');
    voiceClient.startCommand(language: detectedLanguage);
  }

  Future<void> _onCommandFinal(Map<String, dynamic> event) async {
    if (!mounted || shuttingDown) return;

    final commandText = (event['text'] ?? '').toString().trim();
    final language = (event['language'] ?? detectedLanguage).toString();
    final isOffline = event['offline'] == true;

    _log('Google STT: $commandText');

    setState(() {
      transcript = commandText.isEmpty ? 'دستوری دریافت نشد' : commandText;
      detectedLanguage = language;
      mode = isOffline ? 'OFFLINE' : 'ONLINE';
      visualState = SmartisVisualState.thinking;
      status = 'در حال تحلیل دستور...';
    });

    if (commandText.isNotEmpty) {
      await _executeCommand(commandText, language);
    } else {
      _startWakeListening();
    }
  }

  Future<void> _executeCommand(String text, String language) async {
    if (processing) return;
    processing = true;

    final overallStart = DateTime.now();

    try {
      // 1. Agent planning (Fast Path or LLM)
      final planStart = DateTime.now();
      final response = await backend.plan(text, language);
      final planTime = DateTime.now().difference(planStart).inMilliseconds;

      if (response['ok'] != true) {
        setState(() => status = 'خطا در برنامه‌ریزی: ${response['error'] ?? ''}');
        _startWakeListening();
        return;
      }

      final isFastPath = response['provider'] == 'fast-path';
      if (isFastPath) {
        _log('Fast Path matched');
      } else {
        _log('Agent planned in ${planTime}ms');
      }

      final plan = Map<String, dynamic>.from(response['plan'] ?? {});

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

      // 2. Tool Execution
      final toolStart = DateTime.now();
      final actions = (plan['actions'] as List?) ?? [];
      for (final act in actions) {
        if (act is Map) {
          final tool = act['tool']?.toString();
          final args = act['args'];
          if (tool == 'open_application') {
            _log('Opening ${args?['app'] ?? 'application'}');
          } else if (tool == 'open_website') {
            _log('Opening website ${args?['url'] ?? ''}');
          }
        }
      }

      final execution = await backend.execute(plan);
      final toolTime = DateTime.now().difference(toolStart).inMilliseconds;

      if (execution['needs_confirmation'] == true) {
        setState(() => status = 'تأیید لازم است');
        await _speak(
          language == 'fa'
              ? 'برای این عملیات تأیید شما لازم است.'
              : 'I need your confirmation for this action.',
          language,
        );
        return;
      }

      _log('Command complete');

      // 3. TTS Response
      final reply = (plan['reply'] ?? '').toString();
      final ttsStart = DateTime.now();

      if (execution['ok'] == true) {
        setState(() => status = 'انجام شد');
        final results = (execution['results'] as List?) ?? const [];
        final spokenChunks = <String>[];

        for (final item in results) {
          if (item is Map) {
            final itemResult = item['result'];
            if (itemResult is Map) {
              final spoken = (itemResult['speak'] ?? '').toString().trim();
              if (spoken.isNotEmpty) spokenChunks.add(spoken);
            }
          }
        }

        if (spokenChunks.isNotEmpty) {
          await _speak(spokenChunks.join('. '), language);
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

      final ttsTime = DateTime.now().difference(ttsStart).inMilliseconds;
      final totalTime = DateTime.now().difference(overallStart).inMilliseconds;

      _log(
        'STT: Google | Agent: ${planTime}ms | Tool: ${toolTime}ms | TTS: ${ttsTime}ms | Total: ${totalTime}ms',
      );
    } catch (error) {
      _log('Execution error: $error');
      if (mounted) setState(() => status = 'خطا: $error');
    } finally {
      processing = false;
      if (mounted && !shuttingDown) {
        setState(() {
          visualState = SmartisVisualState.idle;
          audioLevel = 0.0;
        });
        // Loop back to wake listening smoothly
        Future.delayed(const Duration(milliseconds: 350), () {
          if (mounted && !shuttingDown) {
            _startWakeListening();
          }
        });
      }
    }
  }

  Future<void> _speak(String text, String? language) async {
    if (!mounted) return;

    setState(() {
      visualState = SmartisVisualState.speaking;
      audioLevel = 0.0;
    });

    final result = await backend.speak(text, language);
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
    voiceClient.dispose();
    player.dispose();
    backend.dispose();
    super.dispose();
  }

  String _stateText() {
    switch (visualState) {
      case SmartisVisualState.idle:
        return 'بگو «اسمارتیز» یا «سعید»';
      case SmartisVisualState.listening:
        return 'گوش می‌دهم...';
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
            child: LayoutBuilder(
              builder: (context, constraints) {
                // Responsively scale Orb so it never overflows 520x610 or any window size,
                // keeping its majestic, full-sized presence intact.
                final orbDimension =
                    (constraints.maxHeight * 0.38).clamp(180.0, 280.0);

                return SingleChildScrollView(
                  physics: const BouncingScrollPhysics(),
                  child: ConstrainedBox(
                    constraints: BoxConstraints(
                      minHeight: constraints.maxHeight,
                    ),
                    child: IntrinsicHeight(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          // Top bar with close button
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
                              const SizedBox(width: 8),
                            ],
                          ),

                          // Smartis Orb (unmodified CustomPainter animation)
                          Center(
                            child: SizedBox(
                              width: orbDimension,
                              height: orbDimension,
                              child: FittedBox(
                                fit: BoxFit.contain,
                                child: SmartisOrb(
                                  state: visualState,
                                  level: audioLevel,
                                ),
                              ),
                            ),
                          ),

                          const SizedBox(height: 6),
                          const Text(
                            'S M A R T I S',
                            style: TextStyle(
                              fontSize: 22,
                              letterSpacing: 8,
                              fontWeight: FontWeight.w600,
                              color: gold,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            _stateText(),
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              fontSize: 12,
                              color: gold,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 20),
                            child: Text(
                              status,
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                color: Colors.white.withOpacity(.82),
                                fontSize: 13,
                              ),
                            ),
                          ),
                          const SizedBox(height: 4),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Text(
                                'حالت: $mode',
                                style: TextStyle(
                                  color: gold.withOpacity(.76),
                                  fontSize: 11,
                                  letterSpacing: 1,
                                ),
                              ),
                              const SizedBox(width: 12),
                              Text(
                                detectedLanguage == 'fa' ? 'فارسی' : 'English',
                                style: TextStyle(
                                  color: gold.withOpacity(.9),
                                  fontSize: 11,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 8),

                          // Transcript box
                          Container(
                            margin: const EdgeInsets.symmetric(horizontal: 36),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 10,
                            ),
                            decoration: BoxDecoration(
                              border: Border.all(
                                color: gold.withOpacity(.24),
                              ),
                              borderRadius: BorderRadius.circular(16),
                              color: Colors.black.withOpacity(.24),
                            ),
                            child: Text(
                              transcript,
                              textAlign: TextAlign.center,
                              textDirection: TextDirection.rtl,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 14),
                            ),
                          ),

                          const SizedBox(height: 8),

                          // Real-time Live Log panel
                          SmartisLogPanel(entries: logs),

                          const SizedBox(height: 6),
                          Text(
                            'Smartis • Google SpeechRecognition + PyAudio • Windows',
                            style: TextStyle(
                              fontSize: 9.5,
                              color: gold.withOpacity(.58),
                              letterSpacing: .5,
                            ),
                          ),
                          const SizedBox(height: 6),
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}
