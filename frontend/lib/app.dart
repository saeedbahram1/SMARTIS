import 'dart:async';

import 'dart:convert';
import 'dart:math' as math;
import 'package:audioplayers/audioplayers.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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
  // Stable identity per bubble so Telegram-style editing can replace a message
  // in place instead of appending a duplicate.
  int _chatIdSeq = 0;
  // Backend log entries are re-sent after every WebSocket reconnect; remember what was shown.
  final Set<String> _seenLogKeys = <String>{};

  Timer? clockTimer;
  Timer? dashboardTimer;

  SmartisVisualState visualState = SmartisVisualState.idle;
  // The orb level lives in a ValueNotifier, not in widget state: mic_level
  // arrives ~20x/s and a root setState at that rate rebuilds the whole window
  // (chat list, dashboard, clock) every frame, which is exactly the lag that
  // made the orb trail behind the real microphone. Only SmartisOrb listens.
  final ValueNotifier<double> orbLevel = ValueNotifier<double>(0);
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
  bool chatThinking = false;
  String? activeChatRequestId;
  int _chatGeneration = 0;

  // Files pinned to the conversation via the "+" button. They stay pinned
  // after Send (removed only with their X) so follow-up questions about the
  // same file keep their content context on the backend.
  final List<ChatAttachmentChip> chatAttachments = [];
  bool attachmentsBusy = false;

  // Live progress steps of the running turn, streamed by the backend as
  // {"type":"step"} frames. Cleared when a new turn starts and rendered by the
  // collapsible activity strip inside the chat panel.
  final List<ChatStep> chatSteps = [];

  // Voice operations share the same stop button as typed chat. The generation
  // token lets a late STT/model response safely die after the user presses Stop.
  String? activeVoiceRequestId;
  int _voiceGeneration = 0;
  // True for the whole TTS turn: synthesis + playback. The backend keeps the
  // microphone paused during that window and emits mic_state events, which must
  // never drag the orb back to listening/thinking while audio is on its way out.
  bool speakingActive = false;
  // Bumped on every _speak() and on Stop. A stopped turn can stay parked on its
  // 90 s completion timeout, and without this token its position listener would
  // keep driving the orb level during the NEXT answer.
  int _speechTurn = 0;
  // Chat-side voice controls. micMuted must survive every automatic resume
  // (after a command, a Stop, a reply) - those all go through _resumeMic().
  bool micMuted = false;
  bool voiceMuted = false;

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
          status = micMuted ? 'میکروفون قطع است' : (ready ? 'گوش می‌دهم...' : 'میکروفون آماده نیست');
          visualState = (ready && !micMuted) ? SmartisVisualState.listening : SmartisVisualState.idle;
          transcript = ready ? 'فرمان بده...' : 'میکروفون را بررسی کن';
        });
        if (ready && micMuted) backend.pauseListening();
        _log('Backend ready • mic=$ready • device=${mic['device'] ?? 'unknown'}');
        break;
      case 'mic_ready':
        if (micMuted) {
          backend.pauseListening();
          break;
        }
        setState(() { visualState = SmartisVisualState.listening; status = 'گوش می‌دهم...'; transcript = 'فرمان بده...'; });
        break;
      case 'mic_error':
        setState(() { visualState = SmartisVisualState.idle; status = 'خطای میکروفون'; });
        _log('Microphone error • ${message['error'] ?? 'unknown'}');
        break;
      case 'mic_state':
        final state = message['state']?.toString() ?? '';
        if (state == 'listening' && !processing && !speakingActive) {
          if (micMuted) {
            // Something re-enabled the mic server-side (e.g. speak_stop);
            // the user's mute is authoritative, so suppress it again.
            backend.pauseListening();
            break;
          }
          setState(() { visualState = SmartisVisualState.listening; status = 'گوش می‌دهم...'; });
        } else if (state == 'paused') {
          // _finish_command() pauses the microphone at the exact moment STT
          // starts decoding, so this is the first honest signal that the user
          // has stopped talking. Show "thinking" here instead of waiting for
          // the (much later) command_result. The TTS hold pauses the mic too,
          // so it must not be mistaken for the start of a new turn.
          if (!processing && !speakingActive && !micMuted && visualState == SmartisVisualState.listening) {
            setState(() { visualState = SmartisVisualState.thinking; status = 'در حال پردازش...'; });
          }
        } else if (state == 'stopped') {
          setState(() { visualState = SmartisVisualState.idle; status = 'میکروفون متوقف است'; });
        }
        break;
      case 'mic_level':
        final raw = message['level'];
        final level = raw is num ? raw.toDouble().clamp(0.0, 1.0).toDouble() : 0.0;
        // Deliberately NOT setState: the orb is the only consumer.
        orbLevel.value = level;
        break;
      case 'command_result': unawaited(_onCommand(message)); break;
      case 'mic_restarted':
        final mic = Map<String, dynamic>.from(message['microphone'] as Map? ?? const {});
        final ready = mic['running'] == true;
        setState(() { processing = false; visualState = (ready && !micMuted) ? SmartisVisualState.listening : SmartisVisualState.idle; status = micMuted ? 'میکروفون قطع است' : (ready ? 'گوش می‌دهم...' : 'میکروفون آماده نیست'); });
        if (ready && micMuted) backend.pauseListening();
        break;
      case 'log':
        _pushTechLog(message);
        break;
      case 'step':
        // Only collect steps while a turn is actually running: a late frame
        // after Stop must not pop the strip back onto a finished conversation.
        if (chatBusy || processing) {
          final text = (message['text'] ?? '').toString().trim();
          if (text.isNotEmpty) {
            setState(() => chatSteps.add(ChatStep(
                  text: text,
                  icon: (message['icon'] ?? 'brain').toString(),
                )));
          }
        }
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
    final session = frame['session']?.toString();
    final id = frame['id']?.toString();
    if (session != null && id != null) {
      if (!_seenLogKeys.add('$session:$id')) return;
    }
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

  void _pushChat(String text, {required bool fromUser, String? provider, bool confirm = false}) {
    if (!mounted) return;
    setState(() {
      chat.add(SmartisChatMessage(
        id: 'm${_chatIdSeq++}',
        text: text,
        fromUser: fromUser,
        time: _stamp(),
        provider: provider,
        confirm: confirm,
      ));
      if (chat.length > 300) chat.removeRange(0, chat.length - 300);
    });
  }

  /// Telegram-style edit: the bubble with [id] is REPLACED in place (no
  /// duplicate), and because the user asked the edited command to actually run
  /// again, the new text is immediately re-sent to the backend. The resend is
  /// flagged so it does NOT append a second copy of the bubble.
  void _editChatMessage(String id, String text) {
    if (!mounted) return;
    final value = text.trim();
    if (value.isEmpty) return;
    final index = chat.indexWhere((m) => m.id == id);
    if (index < 0) {
      _log('Edit ignored: message $id is no longer in the list', category: 'CHAT');
      return;
    }
    final previous = chat[index];
    if (previous.text == value) return;
    setState(() {
      chat[index] = previous.copyWith(text: value, edited: true);
    });
    _log('Message edited in place: «${previous.text}» -> «$value»', category: 'CHAT');
    // Only user messages are commands/questions worth re-running; re-running an
    // assistant bubble would just ask the model to answer itself.
    if (previous.fromUser) {
      unawaited(_sendChat(value, resend: true));
    }
  }

  Future<void> _copyChatMessage(String text) async {
    if (text.trim().isEmpty) return;
    await Clipboard.setData(ClipboardData(text: text));
    _log('Chat message copied', category: 'CHAT');
  }

  /// The "+" button: pick one or more files (a ZIP included) and upload them to
  /// the backend attachment store. Each successful upload becomes a pinned chip.
  Future<void> _pickAttachments() async {
    if (attachmentsBusy) return;
    List<PlatformFile> picked;
    try {
      picked = await FilePicker.pickFiles(dialogTitle: 'افزودن فایل یا زیپ به گفتگو');
    } catch (e) {
      _log('File picker • $e', category: 'CHAT');
      return;
    }
    if (picked.isEmpty) return;
    final paths = picked
        .map((f) => f.path)
        .whereType<String>()
        .where((p) => p.trim().isNotEmpty)
        .toList();
    if (paths.isEmpty) {
      _log('File picker returned no usable path', category: 'CHAT');
      return;
    }
    final room = 4 - chatAttachments.length;
    if (room <= 0) {
      _log('حداکثر ۴ فایل همزمان؛ برای افزودن فایل تازه یکی را حذف کن.', category: 'CHAT');
      return;
    }
    final selected = paths.take(room).toList();
    if (selected.length < paths.length) {
      _log('فقط ۴ فایل همزمان پشتیبانی می‌شود؛ بقیه نادیده گرفته شد.', category: 'CHAT');
    }
    setState(() => attachmentsBusy = true);
    try {
      final result = await backend.uploadFiles(selected);
      final incoming = <ChatAttachmentChip>[];
      for (final raw in (result['attachments'] as List? ?? const [])) {
        final item = Map<String, dynamic>.from(raw as Map);
        if (item['ok'] == true) {
          incoming.add(ChatAttachmentChip(
            id: (item['id'] ?? '').toString(),
            name: (item['name'] ?? 'file').toString(),
            kind: (item['kind'] ?? 'other').toString(),
            sizeLabel: (item['size_label'] ?? '').toString(),
          ));
        } else {
          _log('آپلود ناموفق: ${item['name']} • ${item['error']}', category: 'CHAT');
        }
      }
      if (!mounted) return;
      if (incoming.isNotEmpty) {
        setState(() => chatAttachments.addAll(incoming));
        _log('Attachment ready: ${incoming.map((a) => a.name).join(', ')}', category: 'CHAT');
      }
    } catch (e) {
      _log('Attachment upload • $e', category: 'CHAT');
    } finally {
      if (mounted) setState(() => attachmentsBusy = false);
    }
  }

  void _removeAttachment(String id) {
    setState(() => chatAttachments.removeWhere((a) => a.id == id));
    _log('Attachment unpinned: $id', category: 'CHAT');
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
    final generation = ++_voiceGeneration;
    activeVoiceRequestId = null;
    try {
      if (result['ok'] != true) {
        if (generation != _voiceGeneration) return;
        setState(() { processing = false; status = 'خطا در تشخیص گفتار'; });
        orbLevel.value = 0;
        _log('STT failed • ${result['error'] ?? 'unknown'}', category: 'STT');
        return;
      }
      if (result['ignored'] == true) {
        if (generation != _voiceGeneration) return;
        processing = false;
        _log('Transcript ignored (noise/echo) • ${result['provider'] ?? ''}', category: 'STT');
        return;
      }
      final text = (result['text'] ?? '').toString().trim();
      final language = (result['language'] ?? '').toString().trim();
      if (generation != _voiceGeneration) return;
      setState(() { transcript = text.isEmpty ? 'صدایی تشخیص داده نشد' : text; detectedLanguage = language; mode = result['offline'] == true ? 'OFFLINE STT' : 'ONLINE'; visualState = SmartisVisualState.thinking; status = text.isEmpty ? 'صدایی تشخیص داده نشد' : 'در حال اجرا...'; });
      orbLevel.value = 0;
      _log(
        'Recognized audio text: «$text» • capture=${result['audio_seconds'] ?? '?'}s • stt=${result['stt_elapsed_ms'] ?? '?'}ms',
        category: 'STT',
      );
      if (text.isNotEmpty) {
        _pushChat(text, fromUser: true);
        setState(() {
          processing = true;
          // New voice turn: the previous turn's steps are history.
          chatSteps.clear();
        });
        final requestId = 'v${DateTime.now().microsecondsSinceEpoch}_${generation}';
        activeVoiceRequestId = requestId;
        await _runAgent(text, language.isEmpty ? null : language, generation, requestId);
      }
    } finally {
      if (!mounted || shuttingDown || generation != _voiceGeneration) return;
      activeVoiceRequestId = null;
      processing = false;
      _resumeMic();
      setState(() {
        visualState = micMuted ? SmartisVisualState.idle : SmartisVisualState.listening;
        status = micMuted ? 'میکروفون قطع است' : 'گوش می‌دهم...';
      });
      orbLevel.value = 0;
    }
  }

  /// Shows and speaks ONE backend answer. Typed chat and voice share it, so a
  /// command result, a confirmation question and a chat reply behave the same.
  /// Returns true when the answer is a confirmation question (still pending).
  Future<bool> _presentResponse(
    Map<String, dynamic> response,
    String? language, {
    int? operationGeneration,
  }) async {
    if (response['cancelled'] == true) return false;
    if (operationGeneration != null && operationGeneration != _voiceGeneration) return false;
    final plan = Map<String, dynamic>.from(response['plan'] as Map? ?? const {});
    final execution = Map<String, dynamic>.from(response['execution'] as Map? ?? const {});
    final mode = (response['mode'] ?? '').toString();
    final provider = response['provider']?.toString();
    final reply = (plan['reply'] ?? '').toString().trim();
    final needsConfirm = response['needs_confirmation'] == true ||
        execution['needs_confirmation'] == true ||
        plan['needs_confirmation'] == true;
    bool hasArabicScript(String t) => RegExp(r'[\u0600-\u06FF]').hasMatch(t);

    if (needsConfirm) {
      final q = reply.isNotEmpty ? reply : (language == 'en' ? 'Please confirm.' : 'تأیید می‌کنی؟');
      if (mounted) setState(() => status = 'منتظر تأیید...');
      _pushChat(q, fromUser: false, provider: 'confirmation', confirm: true);
      await _speak(q, hasArabicScript(q) ? 'fa' : 'en', operationGeneration: operationGeneration);
      return true;
    }

    // For executed commands the tool's own speech (e.g. the full weather report) wins.
    final spokenExplicit = (response['spoken_reply'] ?? '').toString().trim();
    final text = (mode == 'command' && response['ok'] == true && spokenExplicit.isNotEmpty) ? spokenExplicit : reply;
    if (text.isEmpty) {
      if (mode == 'chat') _pushChat('پاسخی تولید نشد.', fromUser: false, provider: provider);
      return false;
    }
    _pushChat(text, fromUser: false, provider: provider);
    await _speak(text, hasArabicScript(text) ? 'fa' : 'en', operationGeneration: operationGeneration);
    return false;
  }

  /// Voice path: the transcript goes through the same router as typed chat.
  Future<void> _runAgent(
    String text,
    String? language,
    int generation,
    String requestId,
  ) async {
    try {
      final started = DateTime.now();
      final response = await backend.command(text, language, requestId: requestId, thinking: chatThinking);
      if (!mounted || generation != _voiceGeneration) return;
      _log(
        'Route • ${DateTime.now().difference(started).inMilliseconds}ms • ${response['mode'] ?? '-'} • ${response['provider'] ?? 'unknown'}',
        category: 'ROUTER',
      );
      if (response['ignored'] == true) return;
      if (response['ok'] != true && response['plan'] == null) {
        final msg = language == 'fa' ? 'در اجرای درخواست مشکلی پیش آمد.' : 'I could not execute that request.';
        _pushChat(msg, fromUser: false, provider: 'error');
        await _speak(msg, language, operationGeneration: generation);
        return;
      }
      final pending = await _presentResponse(response, language, operationGeneration: generation);
      if (mounted && generation == _voiceGeneration && !pending) setState(() => status = 'انجام شد');
    } catch (e) {
      if (!mounted || generation != _voiceGeneration) return;
      _log('Command • $e', category: 'EXECUTOR');
      final msg = language == 'fa' ? 'در اجرای درخواست مشکلی پیش آمد.' : 'I could not execute that request.';
      _pushChat(msg, fromUser: false, provider: 'error');
      await _speak(msg, language, operationGeneration: generation);
    }
  }

  /// Typed chat: commands are executed, everything else is answered by the
  /// local model; the answer is shown as a bubble AND spoken. Pinned attachment
  /// ids travel with every message so the model keeps the file content.
  /// [resend] is true when the call comes from an in-place edit: the bubble
  /// already shows the new text, so it must not be pushed a second time.
  Future<void> _sendChat(String text, {bool resend = false}) async {
    final value = text.trim();
    final attachmentIds = chatAttachments.map((a) => a.id).toList();
    if (chatBusy || attachmentsBusy) return;
    if (value.isEmpty && attachmentIds.isEmpty) return;
    final requestId = '${DateTime.now().microsecondsSinceEpoch}_${_chatGeneration++}';
    activeChatRequestId = requestId;
    final generation = _chatGeneration;
    if (!resend) _pushChat(value.isEmpty ? 'این فایل را بررسی کن.' : value, fromUser: true);
    setState(() {
      chatBusy = true;
      // New turn: drop the previous turn's steps so the strip starts clean.
      chatSteps.clear();
      visualState = SmartisVisualState.thinking;
      status = chatThinking ? 'در حال فکر کردن عمیق...' : 'در حال فکر کردن...';
    });
    try {
      final response = await backend.chat(
        value,
        null,
        requestId,
        thinking: chatThinking,
        attachmentIds: attachmentIds,
      );
      if (!mounted || generation != _chatGeneration || activeChatRequestId != requestId) return;
      _log('Route • ${response['mode'] ?? '-'} • ${response['provider'] ?? 'unknown'}', category: 'ROUTER');
      await _presentResponse(response, null);
    } catch (e) {
      _log('Chat • $e', category: 'CHAT');
      _pushChat('ارتباط با Backend برقرار نشد یا پاسخ خیلی طول کشید.', fromUser: false, provider: 'error');
    } finally {
      if (activeChatRequestId == requestId) activeChatRequestId = null;
      if (mounted && generation == _chatGeneration) {
        setState(() {
          chatBusy = false;
          visualState = micMuted ? SmartisVisualState.idle : SmartisVisualState.listening;
          status = micMuted ? 'میکروفون قطع است' : 'گوش می‌دهم...';
        });
      }
      _resumeMic();
    }
  }

  Future<void> _stopChat() async {
    final requestId = activeChatRequestId;
    _chatGeneration++;
    _speechTurn++;
    activeChatRequestId = null;
    speakingActive = false;
    try { await player.stop(); } catch (_) {}
    if (requestId != null) {
      try { await backend.cancelChat(requestId); } catch (_) {}
    }
    try { await backend.stopSpeech(); } catch (_) {}
    if (mounted) {
      setState(() {
        chatBusy = false;
        visualState = micMuted ? SmartisVisualState.idle : SmartisVisualState.listening;
        status = 'متوقف شد';
      });
      orbLevel.value = 0;
      _log('Chat stopped by user.', category: 'CHAT');
    }
    _resumeMic();
  }

  Future<void> _stopVoice() async {
    final requestId = activeVoiceRequestId;
    _voiceGeneration++;
    _speechTurn++;
    activeVoiceRequestId = null;
    speakingActive = false;
    processing = false;
    try { await player.stop(); } catch (_) {}
    if (requestId != null) {
      try { await backend.cancelChat(requestId); } catch (_) {}
    }
    try { backend.stopCommand(); } catch (_) {}
    try { await backend.stopSpeech(); } catch (_) {}
    if (mounted) {
      setState(() {
        processing = false;
        visualState = micMuted ? SmartisVisualState.idle : SmartisVisualState.listening;
        status = 'متوقف شد';
      });
      orbLevel.value = 0;
      _log('Voice operation stopped by user.', category: 'STT');
    }
    _resumeMic();
  }

  Future<void> _stopCurrentOperation() async {
    if (chatBusy) {
      await _stopChat();
      return;
    }
    if (processing || speakingActive || visualState == SmartisVisualState.speaking) {
      await _stopVoice();
    }
  }

  /// Chat mic toggle (cut/connect). When muted, every automatic resume point
  /// (_resumeMic) becomes a no-op and any server-side "listening" event is
  /// re-suppressed, so the microphone stays really off until the user turns it
  /// back on. The top-bar «بازنشانی میکروفون» button keeps its own behaviour.
  void _toggleMic() {
    final next = !micMuted;
    if (next) {
      backend.pauseListening();
    } else {
      backend.resumeListening();
    }
    setState(() {
      micMuted = next;
      visualState = next ? SmartisVisualState.idle : SmartisVisualState.listening;
      status = next ? 'میکروفون قطع است' : 'گوش می‌دهم...';
    });
    _log(next ? 'Microphone muted (chat).' : 'Microphone re-enabled (chat).', category: 'STT');
  }

  /// Single gate every automatic mic-resume goes through, so a muted
  /// microphone is never silently switched back on.
  void _resumeMic() {
    if (!micMuted) backend.resumeListening();
  }

  /// Chat voice toggle: cuts (or restores) Smartis's own spoken replies.
  /// Cutting also stops whatever is being said right now and releases the
  /// backend's echo-guard hold, then re-pauses the mic if it is muted.
  void _toggleVoice() {
    final next = !voiceMuted;
    setState(() {
      voiceMuted = next;
      if (next && visualState == SmartisVisualState.speaking) {
        visualState = micMuted ? SmartisVisualState.idle : SmartisVisualState.listening;
        status = micMuted ? 'میکروفون قطع است' : 'گوش می‌دهم...';
      }
    });
    if (next) {
      _speechTurn++;
      speakingActive = false;
      orbLevel.value = 0;
      unawaited(player.stop().catchError((_) {}));
      unawaited(backend.stopSpeech().then((_) {
        if (micMuted) backend.pauseListening();
      }));
    }
    _log(next ? 'Smartis voice muted.' : 'Smartis voice enabled.', category: 'CHAT');
  }

  /// Plays TTS audio and keeps the microphone suppressed for the WHOLE audio.
  ///
  /// The previous build capped playback at 30 s; a long Wikipedia article then
  /// re-enabled the microphone mid-speech, so Smartis heard itself and the loop
  /// started. The ceiling is now generous and the backend holds the microphone
  /// as a second line of defence.
  double _speechVisualLevel(Duration position, Duration duration, String text) {
    final totalMs = duration.inMilliseconds;
    if (totalMs <= 0) {
      return (.48 + .34 * math.sin(position.inMilliseconds / 85.0)).clamp(0.0, 1.0);
    }
    final progress = (position.inMilliseconds / totalMs).clamp(0.0, 1.0);
    final chars = text.runes.toList();
    if (chars.isEmpty) return .35;
    final index = (progress * (chars.length - 1)).round().clamp(0, chars.length - 1).toInt();
    final current = String.fromCharCode(chars[index]);
    if (RegExp(r'[\s،؛,.!?؟:؛]').hasMatch(current)) {
      return .16 + .10 * (0.5 + 0.5 * math.sin(progress * 80));
    }
    final syllableWave = .5 + .5 * math.sin(
      position.inMilliseconds / 72.0 + index * .83,
    );
    final wordWave = .5 + .5 * math.sin(
      position.inMilliseconds / 155.0 + index * .31,
    );
    return (.30 + .42 * syllableWave + .28 * wordWave).clamp(0.0, 1.0);
  }

  Future<void> _speak(
    String text,
    String? language, {
    int? operationGeneration,
  }) async {
    if (!mounted || text.trim().isEmpty) return;
    if (voiceMuted) return;
    if (operationGeneration != null && operationGeneration != _voiceGeneration) return;
    final turn = ++_speechTurn;
    speakingActive = true;
    // edge-tts synthesises the WHOLE clip before it returns, so claiming
    // "speaking" here would light the orb up seconds before any sound exists.
    // Synthesis is a thinking phase; the orb only switches when audio starts.
    if (mounted) {
      setState(() {
        if (visualState != SmartisVisualState.speaking) visualState = SmartisVisualState.thinking;
        status = 'در حال آماده‌سازی پاسخ صوتی...';
      });
    }

    try {
      final result = await backend.speak(text, language);
      if (!mounted || turn != _speechTurn) return;
      if (operationGeneration != null && operationGeneration != _voiceGeneration) return;
      final encoded = result['audio_base64']?.toString();
      if (encoded == null || encoded.isEmpty) return;

      StreamSubscription<Duration>? durationSub;
      StreamSubscription<Duration>? positionSub;
      Duration duration = Duration.zero;

      try {
        durationSub = player.onDurationChanged.listen((value) {
          duration = value;
        });
        positionSub = player.onPositionChanged.listen((position) {
          // A stopped-but-still-awaiting older turn must never drive the orb.
          if (!mounted || turn != _speechTurn) return;
          orbLevel.value = _speechVisualLevel(position, duration, text);
        });

        final completion = player.onPlayerComplete.first.timeout(
          const Duration(seconds: 90),
        );
        if (mounted) {
          setState(() {
            visualState = SmartisVisualState.speaking;
            status = 'دارم صحبت می‌کنم...';
          });
        }
        orbLevel.value = .25;
        await player.play(
          BytesSource(
            base64Decode(encoded),
            mimeType: result['mime_type']?.toString(),
          ),
        );
        try {
          await completion;
        } catch (_) {}
      } finally {
        await durationSub?.cancel();
        await positionSub?.cancel();
        if (turn == _speechTurn) orbLevel.value = 0;
      }
    } catch (e) {
      _log('TTS playback • $e', category: 'SYSTEM');
    } finally {
      if (turn == _speechTurn) speakingActive = false;
    }
  }

  Future<void> _gracefulClose() async {
    if (shuttingDown) return;
    shuttingDown = true;
    try { await player.stop(); } catch (_) {}
    try { await backend.cancelChat(activeChatRequestId ?? ''); } catch (_) {}
    try { await backend.shutdownBackend(); } catch (_) {}
    await Future<void>.delayed(const Duration(milliseconds: 800));
    await SmartisWindowsWindow.close();
  }

  @override
  void dispose() {
    shuttingDown = true;
    clockTimer?.cancel();
    dashboardTimer?.cancel();
    try { player.stop(); } catch (_) {}
    unawaited(backend.shutdownBackend());
    player.dispose();
    orbLevel.dispose();
    backend.dispose();
    super.dispose();
  }

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
                            SizedBox(width: 390, child: _leftPanel()),
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
            IconButton(tooltip: 'بستن', onPressed: _gracefulClose, icon: const Icon(Icons.close_rounded, color: Colors.white54)),
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
                      scale: 1.28,
                      child: ValueListenableBuilder<double>(
                        valueListenable: orbLevel,
                        builder: (context, level, _) => SmartisOrb(state: visualState, level: level),
                      ),
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
                    busy: chatBusy || processing || speakingActive || visualState == SmartisVisualState.speaking,
                    thinking: chatThinking,
                    onThinkingChanged: (value) => setState(() => chatThinking = value),
                    onSend: _sendChat,
                    onEditMessage: _editChatMessage,
                    onStop: _stopCurrentOperation,
                    micMuted: micMuted,
                    onToggleMic: _toggleMic,
                    voiceMuted: voiceMuted,
                    onToggleVoice: _toggleVoice,
                    onCopyMessage: _copyChatMessage,
                    onConfirm: () => _sendChat('بله'),
                    onCancel: () => _sendChat('لغو'),
                    attachments: chatAttachments,
                    attachmentsBusy: attachmentsBusy,
                    onPickFiles: _pickAttachments,
                    onRemoveAttachment: _removeAttachment,
                    steps: chatSteps,
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
