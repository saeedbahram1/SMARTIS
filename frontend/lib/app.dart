import 'dart:async';

import 'dart:convert';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'services/backend_socket.dart';
import 'services/windows_window.dart';
import 'widgets/smartis_chat_panel.dart';
import 'widgets/smartis_log_panel.dart';
import 'widgets/smartis_orb.dart';

class SmartisApp extends StatefulWidget {
  const SmartisApp({super.key});
  @override
  State<SmartisApp> createState() => _SmartisAppState();
}

class _SmartisAppState extends State<SmartisApp> {
  static const gold = Color(0xFFFFD700);
  final BackendSocket backend = BackendSocket();
  final AudioPlayer player = AudioPlayer();

  // Structured technical logs (streamed from the backend) + typed-chat history.
  final List<SmartisLogEntry> techLogs = [];
  final List<SmartisChatMessage> chat = [];

  Timer? clockTimer;
  Timer? dashboardTimer;

  SmartisVisualState visualState = SmartisVisualState.idle;
  double audioLevel = 0;
  String status = 'در حال اتصال به Backend...';
  String transcript = 'فرمان بده...';
  String detectedLanguage = '';
  String mode = '...';
  bool processing = false;
  bool shuttingDown = false;
  DateTime localNow = DateTime.now();
  Map<String, dynamic> dashboard = {};
  String faGender = 'female';
  String enGender = 'male';
  bool loadingDashboard = false;

  int leftTab = 0; // 0 = Technical Logs, 1 = Chat
  bool backendConnected = false;
  bool chatBusy = false;

  @override
  void initState() {
    super.initState();
    backend.connect(onMessage: _handleBackendMessage, onError: _handleBackendError);
    _refreshDashboard();
    clockTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => localNow = DateTime.now());
    });
    dashboardTimer = Timer.periodic(const Duration(seconds: 20), (_) => _refreshDashboard());
  }

  void _handleBackendMessage(Map<String, dynamic> message) {
    if (!mounted) return;
    final type = message['type']?.toString();
    switch (type) {
      case 'backend_ready':
        final internet = message['internet'] == true;
        final mic = Map<String, dynamic>.from(message['microphone'] as Map? ?? const {});
        final ready = mic['running'] == true;
        setState(() {
          backendConnected = true;
          mode = internet ? 'ONLINE TTS' : 'OFFLINE';
          status = ready ? 'گوش می‌دهم...' : 'میکروفون آماده نیست';
          visualState = ready ? SmartisVisualState.listening : SmartisVisualState.idle;
          transcript = ready ? 'فرمان بده...' : 'میکروفون را بررسی کن';
        });
        _log('Backend ready • mic=$ready • device=${mic['device'] ?? 'unknown'}');
        break;
      case 'mic_ready':
        setState(() { visualState = SmartisVisualState.listening; status = 'گوش می‌دهم...'; transcript = 'فرمان بده...'; });
        break;
      case 'mic_error':
        setState(() { visualState = SmartisVisualState.idle; status = 'خطای میکروفون'; });
        _log('Microphone error • ${message['error'] ?? 'unknown'}');
        break;
      case 'mic_state':
        final state = message['state']?.toString() ?? '';
        if (state == 'listening' && !processing) {
          setState(() { visualState = SmartisVisualState.listening; status = 'گوش می‌دهم...'; });
        } else if (state == 'stopped') {
          setState(() { visualState = SmartisVisualState.idle; status = 'میکروفون متوقف است'; });
        }
        break;
      case 'mic_level':
        final raw = message['level'];
        final level = raw is num ? raw.toDouble().clamp(0.0, 1.0).toDouble() : 0.0;
        if (mounted) setState(() => audioLevel = level);
        break;
      case 'command_result': unawaited(_onCommand(message)); break;
      case 'mic_restarted':
        final mic = Map<String, dynamic>.from(message['microphone'] as Map? ?? const {});
        final ready = mic['running'] == true;
        setState(() { processing = false; visualState = ready ? SmartisVisualState.listening : SmartisVisualState.idle; status = ready ? 'گوش می‌دهم...' : 'میکروفون آماده نیست'; });
        break;
      case 'log':
        _pushTechLog(message);
        break;
      case 'chat':
        final plan = Map<String, dynamic>.from(message['plan'] as Map? ?? const {});
        final reply = (plan['reply'] ?? '').toString().trim();
        if (reply.isNotEmpty) _pushChat(reply, fromUser: false, provider: message['provider']?.toString());
        break;
    }
  }

  void _handleBackendError(Object error) {
    _log('Backend connection • $error');
    if (mounted) {
      setState(() {
        backendConnected = false;
        status = 'در حال اتصال دوباره به Backend...';
        visualState = SmartisVisualState.idle;
      });
    }
  }

  String _stamp() {
    final n = DateTime.now();
    return '${n.hour.toString().padLeft(2, '0')}:${n.minute.toString().padLeft(2, '0')}:${n.second.toString().padLeft(2, '0')}';
  }

  void _log(String message, {String category = 'SYSTEM'}) {
    if (!mounted) return;
    setState(() {
      techLogs.add(SmartisLogEntry(category: category, message: message, time: _stamp()));
      if (techLogs.length > 400) techLogs.removeRange(0, techLogs.length - 400);
    });
  }

  void _pushTechLog(Map<String, dynamic> frame) {
    setState(() {
      techLogs.add(
        SmartisLogEntry(
          category: (frame['category'] ?? 'SYSTEM').toString(),
          message: (frame['message'] ?? '').toString(),
          detail: frame['detail']?.toString(),
          time: (frame['time'] ?? _stamp()).toString(),
        ),
      );
      if (techLogs.length > 400) techLogs.removeRange(0, techLogs.length - 400);
    });
  }

  void _pushChat(String text, {required bool fromUser, String? provider}) {
    if (!mounted) return;
    setState(() {
      chat.add(SmartisChatMessage(text: text, fromUser: fromUser, time: _stamp(), provider: provider));
      if (chat.length > 300) chat.removeRange(0, chat.length - 300);
    });
  }

  Future<void> _refreshDashboard() async {
    if (loadingDashboard || !mounted) return;
    loadingDashboard = true;
    try {
      final result = await backend.dashboard();
      if (!mounted || result['ok'] != true) return;
      final voices = Map<String, dynamic>.from(result['voices'] as Map? ?? const {});
      setState(() {
        dashboard = result;
        final fa = Map<String, dynamic>.from(voices['fa'] as Map? ?? const {});
        final en = Map<String, dynamic>.from(voices['en'] as Map? ?? const {});
        faGender = (fa['key']?.toString() ?? 'fa_female').endsWith('female') ? 'female' : 'male';
        enGender = (en['key']?.toString() ?? 'en_male').endsWith('female') ? 'female' : 'male';
      });
    } catch (e) { _log('Dashboard • $e'); }
    finally { loadingDashboard = false; }
  }

  Future<void> _changeVoice(String language, String gender) async {
    try {
      final r = await backend.setVoice(language, gender);
      if (r['ok'] == true && mounted) {
        setState(() { if (language == 'fa') faGender = gender; else enGender = gender; });
        _log('Voice • $language/${gender == 'female' ? 'female' : 'male'}');
      }
    } catch (e) { _log('Voice settings • $e'); }
  }

  Future<void> _onCommand(Map<String, dynamic> result) async {
    if (!mounted || shuttingDown) return;
    try {
      if (result['ok'] != true) {
        setState(() { processing = false; status = 'خطا در تشخیص گفتار'; audioLevel = 0; });
        _log('STT failed • ${result['error'] ?? 'unknown'}', category: 'STT');
        return;
      }
      if (result['ignored'] == true) {
        processing = false;
        _log('Transcript ignored (noise/echo) • ${result['provider'] ?? ''}', category: 'STT');
        return;
      }
      final text = (result['text'] ?? '').toString().trim();
      final language = (result['language'] ?? '').toString().trim();
      setState(() { transcript = text.isEmpty ? 'صدایی تشخیص داده نشد' : text; detectedLanguage = language; mode = result['offline'] == true ? 'OFFLINE STT' : 'ONLINE'; visualState = SmartisVisualState.thinking; status = text.isEmpty ? 'صدایی تشخیص داده نشد' : 'در حال اجرا...'; audioLevel = 0; });
      _log('Recognized audio text: «$text»', category: 'STT');
      if (text.isNotEmpty) {
        _pushChat(text, fromUser: true);
        processing = true;
        await _runAgent(text, language.isEmpty ? null : language);
        processing = false;
      }
    } finally {
      if (!mounted || shuttingDown) return;
      processing = false;
      backend.resumeListening();
      setState(() { visualState = SmartisVisualState.listening; status = 'گوش می‌دهم...'; audioLevel = 0; });
    }
  }

  Future<void> _runAgent(String text, String? language) async {
    try {
      final started = DateTime.now();
      final response = await backend.command(text, language);
      _log('Execute • ${DateTime.now().difference(started).inMilliseconds}ms • ${response['provider'] ?? 'unknown'}', category: 'EXECUTOR');
      if (response['ok'] != true) {
        await _speak(language == 'fa' ? 'در اجرای درخواست مشکلی پیش آمد.' : 'I could not execute that request.', language);
        return;
      }
      final plan = Map<String, dynamic>.from(response['plan'] as Map? ?? {});
      final execution = Map<String, dynamic>.from(response['execution'] as Map? ?? {});
      if (execution['needs_confirmation'] == true || plan['needs_confirmation'] == true) {
        setState(() => status = 'منتظر تأیید...');
        final q = (plan['reply'] ?? (language == 'fa' ? 'تأیید می‌کنی؟' : 'Please confirm.')).toString();
        _pushChat(q, fromUser: false, provider: 'confirmation');
        await _speak(q, language);
        return;
      }
      final results = (execution['results'] as List?) ?? const [];
      if (execution['ok'] != true) {
        String detail = '';
        for (final item in results) {
          if (item is Map && item['result'] is Map) {
            final x = Map<String, dynamic>.from(item['result'] as Map);
            detail = (x['speak'] ?? x['error'] ?? '').toString().trim();
            if (detail.isNotEmpty) break;
          }
        }
        final message = detail.isNotEmpty ? detail : (language == 'fa' ? 'اجرای دستور با مشکل روبه‌رو شد.' : 'The command could not be completed.');
        _pushChat(message, fromUser: false, provider: 'executor');
        await _speak(message, language);
        return;
      }
      final chunks = <String>[];
      for (final item in results) {
        if (item is Map && item['result'] is Map) {
          final x = Map<String, dynamic>.from(item['result'] as Map);
          final t = (x['speak'] ?? '').toString().trim();
          if (t.isNotEmpty) chunks.add(t);
        }
      }
      final reply = (plan['reply'] ?? '').toString().trim();
      final spoken = chunks.isNotEmpty ? chunks.join('. ') : reply;
      if (spoken.isNotEmpty) {
        _pushChat(spoken, fromUser: false, provider: response['provider']?.toString());
        await _speak(spoken, language);
      }
      if (mounted) setState(() => status = 'انجام شد');
    } catch (e) {
      _log('Command • $e', category: 'EXECUTOR');
      await _speak(language == 'fa' ? 'در اجرای درخواست مشکلی پیش آمد.' : 'I could not execute that request.', language);
    }
  }

  /// Typed chat: the answer is shown as a bubble AND spoken out loud.
  Future<void> _sendChat(String text) async {
    if (text.trim().isEmpty || chatBusy) return;
    _pushChat(text, fromUser: true);
    setState(() { chatBusy = true; visualState = SmartisVisualState.thinking; status = 'در حال فکر کردن...'; });
    try {
      final response = await backend.chat(text, null);
      final plan = Map<String, dynamic>.from(response['plan'] as Map? ?? const {});
      final reply = (plan['reply'] ?? '').toString().trim();
      if (reply.isEmpty) {
        _pushChat('پاسخی تولید نشد.', fromUser: false);
      } else {
        _pushChat(reply, fromUser: false, provider: response['provider']?.toString());
        final language = RegExp(r'[\u0600-\u06FF]').hasMatch(reply) ? 'fa' : 'en';
        await _speak(reply, language);
      }
    } catch (e) {
      _log('Chat • $e');
      _pushChat('ارتباط با Backend برقرار نشد.', fromUser: false);
    } finally {
      if (mounted) {
        setState(() { chatBusy = false; visualState = SmartisVisualState.listening; status = 'گوش می‌دهم...'; });
      }
      backend.resumeListening();
    }
  }

  /// Plays TTS audio and keeps the microphone suppressed for the WHOLE audio.
  ///
  /// The previous build capped playback at 30 s; a long Wikipedia article then
  /// re-enabled the microphone mid-speech, so Smartis heard itself and the loop
  /// started. The ceiling is now generous and the backend holds the microphone
  /// as a second line of defence.
  Future<void> _speak(String text, String? language) async {
    if (!mounted || text.trim().isEmpty) return;
    setState(() { visualState = SmartisVisualState.speaking; status = 'دارم صحبت می‌کنم...'; audioLevel = 0; });
    try {
      final result = await backend.speak(text, language);
      final encoded = result['audio_base64']?.toString();
      if (encoded != null && encoded.isNotEmpty) {
        // Wait for the audio to actually finish. Capping this (the previous
        // build used 30 s) is what made the microphone reopen mid-sentence, so
        // Smartis started hearing its own Wikipedia reading.
        final completion = player.onPlayerComplete.first;
        await player.play(BytesSource(base64Decode(encoded), mimeType: result['mime_type']?.toString()));
        try { await completion; } catch (_) {}
      }
    } catch (e) {
      _log('TTS playback • $e', category: 'SYSTEM');
    }
  }

  @override
  void dispose() { shuttingDown = true; clockTimer?.cancel(); dashboardTimer?.cancel(); player.dispose(); backend.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final weather = Map<String, dynamic>.from(dashboard['weather'] as Map? ?? const {});
    final location = Map<String, dynamic>.from(dashboard['location'] as Map? ?? const {});
    final timeDate = Map<String, dynamic>.from(dashboard['time_date'] as Map? ?? const {});
    final cpu = dashboard['cpu_percent'];
    final ram = dashboard['ram_percent'];
    final smartCpu = dashboard['smartis_cpu_percent'];
    final smartRam = dashboard['smartis_memory_mb'];
    final cpuTemp = dashboard['cpu_temp_c'];
    final ramTemp = dashboard['ram_temp_c'];
    final dateFa = (timeDate['date_fa'] ?? '').toString();
    final weatherText = (weather['message'] ?? '').toString();
    final locationOff = weather['location_required'] == true ||
        (location.isNotEmpty && location['ok'] == false && weather['ok'] != true);

    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        useMaterial3: true,
        scaffoldBackgroundColor: Colors.black,
        canvasColor: Colors.black,
        colorScheme: ColorScheme.fromSeed(seedColor: gold, brightness: Brightness.dark),
      ),
      home: Scaffold(
        backgroundColor: Colors.black,
        body: GestureDetector(
          behavior: HitTestBehavior.translucent,
          onPanStart: (_) => SmartisWindowsWindow.startDragging(),
          child: SafeArea(
            child: Column(
              children: [
                _topBar(),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
                    child: LayoutBuilder(
                      builder: (context, constraints) {
                        final compact = constraints.maxWidth < 1050;
                        if (compact) {
                          return _compactLayout(
                            timeDate, dateFa, weatherText, weather, location,
                            locationOff, cpu, ram, cpuTemp, ramTemp, smartCpu, smartRam,
                          );
                        }
                        return Row(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            SizedBox(width: 340, child: _leftPanel()),
                            const SizedBox(width: 18),
                            Expanded(child: _orbPanel()),
                            const SizedBox(width: 18),
                            SizedBox(
                              width: 360,
                              child: _rightPanel(
                                timeDate, dateFa, weatherText, weather, location,
                                locationOff, cpu, ram, cpuTemp, ramTemp, smartCpu, smartRam,
                              ),
                            ),
                          ],
                        );
                      },
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _topBar() => Padding(
        padding: const EdgeInsets.fromLTRB(22, 10, 22, 10),
        child: Row(
          children: [
            const Icon(Icons.auto_awesome, color: gold, size: 20),
            const SizedBox(width: 9),
            const Text('SMARTIS', style: TextStyle(color: gold, fontWeight: FontWeight.w800, letterSpacing: 2.4)),
            const SizedBox(width: 14),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(color: const Color(0xFF101010), borderRadius: BorderRadius.circular(20), border: Border.all(color: gold.withOpacity(.12))),
              child: Text(mode, style: const TextStyle(color: Colors.white54, fontSize: 10, letterSpacing: .8)),
            ),
            const Spacer(),
            IconButton(tooltip: 'بازنشانی میکروفون', onPressed: backend.restartMicrophone, icon: const Icon(Icons.mic_none_rounded, color: gold)),
            IconButton(tooltip: 'بستن', onPressed: SmartisWindowsWindow.close, icon: const Icon(Icons.close_rounded, color: Colors.white54)),
          ],
        ),
      );

  Widget _orbPanel() => Container(
        decoration: _box().copyWith(borderRadius: BorderRadius.circular(26)),
        child: Stack(
          children: [
            Positioned(top: 22, left: 22, child: _hudLabel('SMARTIS CORE')),
            Positioned(top: 22, right: 22, child: _hudLabel(detectedLanguage.isEmpty ? 'AUTO' : detectedLanguage.toUpperCase())),
            Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // smartis_orb.dart itself is intentionally NOT modified: the orb is
                  // only scaled up a little here so it reads closer to the
                  // reference image without touching the original widget.
                  FittedBox(
                    fit: BoxFit.contain,
                    child: Transform.scale(
                      scale: 1.08,
                      child: SmartisOrb(state: visualState, level: audioLevel),
                    ),
                  ),
                  const SizedBox(height: 28),
                  Text(status, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 8),
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 620),
                    child: Text(transcript, maxLines: 3, overflow: TextOverflow.ellipsis, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white54, fontSize: 14, height: 1.5)),
                  ),
                ],
              ),
            ),
            Positioned(left: 22, right: 22, bottom: 20, child: Row(children: [
              _statusDot(visualState == SmartisVisualState.listening),
              const SizedBox(width: 8),
              Text(visualState == SmartisVisualState.listening ? 'LISTENING' : visualState.name.toUpperCase(), style: const TextStyle(color: Colors.white38, fontSize: 10, letterSpacing: 1.2)),
              const Spacer(),
              Text(_clock(localNow), style: const TextStyle(color: gold, fontSize: 13, fontWeight: FontWeight.w700)),
            ])),
          ],
        ),
      );

  Widget _rightPanel(Map<String, dynamic> td, String dateFa, String weatherText, Map<String, dynamic> weather, Map<String, dynamic> location, bool locationOff, dynamic cpu, dynamic ram, dynamic cpuTemp, dynamic ramTemp, dynamic smartCpu, dynamic smartRam) => SingleChildScrollView(
        physics: const BouncingScrollPhysics(),
        child: Column(
          children: [
            _heroCard(td, dateFa),
            const SizedBox(height: 12),
            _weatherCard(weatherText, weather, location, locationOff),
            const SizedBox(height: 12),
            _dashboardGrid(cpu, ram, cpuTemp, ramTemp, smartCpu, smartRam),
            const SizedBox(height: 12),
            _voiceCard(),
          ],
        ),
      );

  /// Left column: a segmented switch between Technical Logs and Chat.
  Widget _leftPanel() => Column(
        children: [
          Container(
            padding: const EdgeInsets.all(5),
            decoration: BoxDecoration(
              color: const Color(0xFF080808),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: gold.withOpacity(.14)),
            ),
            child: Row(
              children: [
                _tabButton('پنل لاگ‌های فنی', 0, Icons.insights_rounded),
                const SizedBox(width: 5),
                _tabButton('چت', 1, Icons.forum_rounded),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Expanded(
            child: leftTab == 0
                ? SmartisLogPanel(entries: techLogs, connected: backendConnected)
                : SmartisChatPanel(
                    messages: chat,
                    busy: chatBusy,
                    onSend: _sendChat,
                    onMic: backend.restartMicrophone,
                  ),
          ),
        ],
      );

  Widget _tabButton(String label, int index, IconData icon) {
    final selected = leftTab == index;
    return Expanded(
      child: GestureDetector(
        onTap: () => setState(() => leftTab = index),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: selected ? gold.withOpacity(.14) : Colors.transparent,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: selected ? gold.withOpacity(.55) : Colors.transparent),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 15, color: selected ? gold : Colors.white38),
              const SizedBox(width: 7),
              Text(
                label,
                style: TextStyle(
                  color: selected ? gold : Colors.white38,
                  fontSize: 11.5,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _compactLayout(Map<String, dynamic> td, String dateFa, String weatherText, Map<String, dynamic> weather, Map<String, dynamic> location, bool locationOff, dynamic cpu, dynamic ram, dynamic cpuTemp, dynamic ramTemp, dynamic smartCpu, dynamic smartRam) => SingleChildScrollView(
        physics: const BouncingScrollPhysics(),
        child: Column(children: [
          SizedBox(height: 430, child: _orbPanel()),
          const SizedBox(height: 14),
          _rightPanel(td, dateFa, weatherText, weather, location, locationOff, cpu, ram, cpuTemp, ramTemp, smartCpu, smartRam),
          const SizedBox(height: 14),
          SizedBox(height: 460, child: _leftPanel()),
        ]),
      );

  Widget _hudLabel(String value) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
        decoration: BoxDecoration(color: gold.withOpacity(.06), borderRadius: BorderRadius.circular(20), border: Border.all(color: gold.withOpacity(.12))),
        child: Text(value, style: const TextStyle(color: Colors.white30, fontSize: 9, letterSpacing: 1.1)),
      );

  Widget _statusDot(bool active) => Container(width: 7, height: 7, decoration: BoxDecoration(shape: BoxShape.circle, color: active ? gold : Colors.white24, boxShadow: active ? [BoxShadow(color: gold.withOpacity(.45), blurRadius: 8)] : null));

  Widget _heroCard(Map<String, dynamic> td, String dateFa) => Container(width: double.infinity, padding: const EdgeInsets.all(18), decoration: _box(), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Row(children: [const Icon(Icons.schedule_rounded, color: gold, size: 22), const SizedBox(width: 10), Expanded(child: Text(_clock(localNow), style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: 1.1)))]),
    const SizedBox(height: 8),
    Row(children: [const Icon(Icons.calendar_month_rounded, color: gold, size: 17), const SizedBox(width: 8), Expanded(child: Text(dateFa.isNotEmpty ? dateFa : 'تاریخ در حال دریافت...', style: const TextStyle(color: Colors.white70, fontSize: 13)))]),
    const SizedBox(height: 8),
    Text('فرمان‌ها را مستقیم می‌شنوم؛ گفتن «اسمارتیز» اختیاری است.', style: TextStyle(color: gold.withOpacity(.82), fontSize: 10)),
  ]));

  Widget _dashboardGrid(dynamic cpu, dynamic ram, dynamic cpuTemp, dynamic ramTemp, dynamic smartCpu, dynamic smartRam) => GridView.count(crossAxisCount: 2, shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), crossAxisSpacing: 8, mainAxisSpacing: 8, childAspectRatio: 1.65, children: [
    _metric(Icons.memory_rounded, 'CPU', cpu == null ? '--' : '$cpu%'),
    _metric(Icons.device_thermostat_rounded, 'دمای CPU', cpuTemp == null ? '--' : '$cpuTemp°C'),
    _metric(Icons.storage_rounded, 'RAM', ram == null ? '--' : '$ram%'),
    _metric(Icons.thermostat_rounded, 'دمای RAM', ramTemp == null ? '--' : '$ramTemp°C'),
    _metric(Icons.bolt_rounded, 'CPU Smartis', smartCpu == null ? '--' : '$smartCpu%'),
    _metric(Icons.memory_rounded, 'RAM Smartis', smartRam == null ? '--' : '$smartRam MB'),
  ]);

  Widget _weatherCard(String text, Map<String, dynamic> weather, Map<String, dynamic> location, bool off) => Container(width: double.infinity, padding: const EdgeInsets.all(15), decoration: _box(), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Row(children: [const Icon(Icons.cloud_rounded, color: gold), const SizedBox(width: 8), const Text('آب‌وهوا', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)), const Spacer(), IconButton(onPressed: off ? SmartisWindowsWindow.openLocationSettings : null, tooltip: 'مکان ویندوز', icon: Icon(off ? Icons.location_disabled : Icons.location_on, color: off ? Colors.redAccent : gold))]),
    const SizedBox(height: 4),
    Text(off ? 'مکان ویندوز در دسترس نیست؛ می‌توانی شهر را مستقیم از Smartis بپرسی.' : (text.isNotEmpty ? text : 'آب‌وهوا در حال دریافت است...'), style: const TextStyle(color: Colors.white70, fontSize: 13, height: 1.5)),
    if (!off) Padding(padding: const EdgeInsets.only(top: 7), child: Text('${weather['city'] ?? location['city'] ?? ''}  •  ${weather['humidity'] ?? '--'}% رطوبت  •  ${weather['wind_kmh'] ?? '--'} km/h باد', style: const TextStyle(color: Colors.white38, fontSize: 10))),
  ]));

  Widget _voiceCard() => Container(width: double.infinity, padding: const EdgeInsets.all(15), decoration: _box(), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    const Row(children: [Icon(Icons.record_voice_over_rounded, color: gold), SizedBox(width: 8), Text('صدای Smartis', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))]),
    const SizedBox(height: 10),
    Row(children: [Expanded(child: _voiceDropdown('فارسی', faGender, (v) => _changeVoice('fa', v))), const SizedBox(width: 8), Expanded(child: _voiceDropdown('English', enGender, (v) => _changeVoice('en', v)))]),
  ]));

  Widget _voiceDropdown(String label, String value, ValueChanged<String> onChanged) => InputDecorator(decoration: InputDecoration(labelText: label, labelStyle: const TextStyle(color: Colors.white54), filled: true, fillColor: const Color(0xFF101010), border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: Color(0x22FFD700))), enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(12)), borderSide: BorderSide(color: Color(0x22FFD700)))), child: DropdownButtonHideUnderline(child: DropdownButton<String>(isExpanded: true, value: value, dropdownColor: const Color(0xFF151515), items: const [DropdownMenuItem(value: 'female', child: Text('زن / Female')), DropdownMenuItem(value: 'male', child: Text('مرد / Male'))], onChanged: (v) { if (v != null) onChanged(v); })));

  BoxDecoration _box() => BoxDecoration(color: const Color(0xFF080808), borderRadius: BorderRadius.circular(18), border: Border.all(color: gold.withOpacity(.14)));

  Widget _metric(IconData icon, String title, String value) => Container(padding: const EdgeInsets.all(10), decoration: _box(), child: Row(children: [Icon(icon, color: gold, size: 18), const SizedBox(width: 7), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [Text(title, style: const TextStyle(color: Colors.white54, fontSize: 9), maxLines: 1, overflow: TextOverflow.ellipsis), const SizedBox(height: 2), Text(value, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13))]))]));

  String _clock(DateTime x) => '${x.hour.toString().padLeft(2, '0')}:${x.minute.toString().padLeft(2, '0')}:${x.second.toString().padLeft(2, '0')}';
}
