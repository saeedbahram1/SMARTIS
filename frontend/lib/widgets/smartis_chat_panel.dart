import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'smartis_orb.dart';

class _TopDownBrainIcon extends StatelessWidget {
  final double size;
  final Color color;
  const _TopDownBrainIcon({this.size = 24, this.color = const Color(0xFFFFD700)});
  @override
  Widget build(BuildContext context) => CustomPaint(size: Size.square(size), painter: _TopDownBrainPainter(color));
}

class _TopDownBrainPainter extends CustomPainter {
  final Color color;
  _TopDownBrainPainter(this.color);
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = size.width * .095
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final w = size.width, h = size.height;
    final left = Path()
      ..moveTo(w*.49,h*.12)
      ..cubicTo(w*.31,h*.04,w*.12,h*.15,w*.14,h*.36)
      ..cubicTo(w*.02,h*.57,w*.13,h*.78,w*.30,h*.86)
      ..cubicTo(w*.39,h*.91,w*.47,h*.83,w*.49,h*.70);
    final right = Path()
      ..moveTo(w*.51,h*.12)
      ..cubicTo(w*.69,h*.04,w*.88,h*.15,w*.86,h*.36)
      ..cubicTo(w*.98,h*.57,w*.87,h*.78,w*.70,h*.86)
      ..cubicTo(w*.61,h*.91,w*.53,h*.83,w*.51,h*.70);
    canvas.drawPath(left,p);
    canvas.drawPath(right,p);
    final mid = Paint()
      ..color=color
      ..style=PaintingStyle.stroke
      ..strokeWidth=size.width*.07
      ..strokeCap=StrokeCap.round;
    final l1=Path()
      ..moveTo(w*.42,h*.20)
      ..cubicTo(w*.34,h*.28,w*.44,h*.34,w*.36,h*.42)
      ..cubicTo(w*.29,h*.49,w*.39,h*.56,w*.31,h*.66);
    final l2=Path()
      ..moveTo(w*.27,h*.24)
      ..cubicTo(w*.20,h*.32,w*.31,h*.38,w*.22,h*.47)
      ..cubicTo(w*.18,h*.52,w*.25,h*.58,w*.23,h*.65);
    final r1=Path()
      ..moveTo(w*.58,h*.20)
      ..cubicTo(w*.66,h*.28,w*.56,h*.34,w*.64,h*.42)
      ..cubicTo(w*.71,h*.49,w*.61,h*.56,w*.69,h*.66);
    final r2=Path()
      ..moveTo(w*.73,h*.24)
      ..cubicTo(w*.80,h*.32,w*.69,h*.38,w*.78,h*.47)
      ..cubicTo(w*.82,h*.52,w*.75,h*.58,w*.77,h*.65);
    canvas.drawPath(l1,mid);
    canvas.drawPath(l2,mid);
    canvas.drawPath(r1,mid);
    canvas.drawPath(r2,mid);
  }
  @override bool shouldRepaint(covariant _TopDownBrainPainter oldDelegate)=>oldDelegate.color!=color;
}

class SmartisChatMessage {
  final String id;
  final String text;
  final bool fromUser;
  final String time;
  final String? provider;
  final bool confirm;
  final bool edited;

  const SmartisChatMessage({
    required this.id,
    required this.text,
    required this.fromUser,
    this.time = '',
    this.provider,
    this.confirm = false,
    this.edited = false,
  });

  SmartisChatMessage copyWith({String? text, bool? edited}) => SmartisChatMessage(
        id: id,
        text: text ?? this.text,
        fromUser: fromUser,
        time: time,
        provider: provider,
        confirm: confirm,
        edited: edited ?? this.edited,
      );
}

/// One file the user pinned to the chat (already uploaded and inspected by the
/// backend). Chips stay above the composer until the user removes them, so
/// follow-up questions keep working against the same file content.
class ChatAttachmentChip {
  final String id;
  final String name;
  final String kind; // zip | image | text | other
  final String sizeLabel;

  const ChatAttachmentChip({
    required this.id,
    required this.name,
    this.kind = 'other',
    this.sizeLabel = '',
  });
}

/// One live progress event streamed by the backend ({"type":"step"}). Steps
/// belong to the CURRENT turn only: they arrive in order while Smartis works
/// and disappear with the busy indicator, exactly like the step stream in
/// ChatGPT / Claude.
class ChatStep {
  final String text;
  final String icon;
  const ChatStep({required this.text, this.icon = 'brain'});
}

/// ChatGPT-style chat surface. While Smartis works, a collapsible progress
/// strip lives INSIDE the message stream, immediately after the latest user
/// bubble: the newest backend step plus an elapsed clock, expandable to the
/// full step history. The strip disappears when the real reply is inserted.
class SmartisChatPanel extends StatefulWidget {
  final List<SmartisChatMessage> messages;
  final bool busy;
  final bool thinking;
  final ValueChanged<bool>? onThinkingChanged;
  final void Function(String text) onSend;
  /// Telegram-style edit: replaces the bubble identified by [id] in place, and
  /// the app then RE-RUNS the edited text against the backend (the user asked
  /// for the edited command to execute again). No duplicate bubble is added.
  final void Function(String id, String text)? onEditMessage;
  /// Microphone cut/connect toggle (own state, just for the chat).
  final bool micMuted;
  final VoidCallback? onToggleMic;
  /// Smartis voice cut/connect toggle (its spoken replies in the chat).
  final bool voiceMuted;
  final VoidCallback? onToggleVoice;
  final VoidCallback? onStop;
  final ValueChanged<String>? onCopyMessage;
  final VoidCallback? onConfirm;
  final VoidCallback? onCancel;
  /// Files pinned to the conversation (the "+" button adds them).
  final List<ChatAttachmentChip> attachments;
  final bool attachmentsBusy;
  final VoidCallback? onPickFiles;
  final void Function(String id)? onRemoveAttachment;

  /// Live progress steps of the running turn (arrival order). The strip under
  /// the last bubble shows the newest one collapsed; tapping the small triangle
  /// expands the full history. Empty list = nothing shown.
  final List<ChatStep> steps;

  const SmartisChatPanel({
    super.key,
    required this.messages,
    required this.onSend,
    this.onEditMessage,
    this.busy = false,
    this.thinking = false,
    this.onThinkingChanged,
    this.micMuted = false,
    this.onToggleMic,
    this.voiceMuted = false,
    this.onToggleVoice,
    this.onStop,
    this.onCopyMessage,
    this.onConfirm,
    this.onCancel,
    this.attachments = const [],
    this.attachmentsBusy = false,
    this.onPickFiles,
    this.onRemoveAttachment,
    this.steps = const [],
  });

  @override
  State<SmartisChatPanel> createState() => _SmartisChatPanelState();
}

class _SmartisChatPanelState extends State<SmartisChatPanel> {
  static const gold = Color(0xFFFFD700);
  final TextEditingController _controller = TextEditingController();
  final FocusNode _focus = FocusNode();
  final ScrollController _scroll = ScrollController();
  bool _canSend = false;
  /// Id of the bubble currently loaded into the composer for editing.
  String? _editingId;
  /// Unsent draft that was in the composer before editing started, so cancel
  /// gives it back instead of throwing the user's typing away.
  String _draftBeforeEdit = '';
  /// Seconds the current turn has been running (shown next to the live step).
  int _stepSeconds = 0;
  Timer? _stepClock;
  /// The step history starts collapsed; the triangle toggles it.
  bool _stepsOpen = false;

  @override
  void initState() {
    super.initState();
    _controller.addListener(_syncCanSend);
    WidgetsBinding.instance.addPostFrameCallback((_) => _focus.requestFocus());
  }

  /// Send is enabled by typed text OR by pinned attachments (attachment-only
  /// send works: the backend then inspects the file and explains it).
  void _syncCanSend() {
    final next = _controller.text.trim().isNotEmpty || widget.attachments.isNotEmpty;
    if (next != _canSend) setState(() => _canSend = next);
  }

  @override
  void didUpdateWidget(covariant SmartisChatPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.messages.length != oldWidget.messages.length || widget.busy != oldWidget.busy) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _toBottom());
    }
    if (widget.steps.length != oldWidget.steps.length) {
      // New step arrived: keep the newest line visible in the stream.
      WidgetsBinding.instance.addPostFrameCallback((_) => _toBottom());
    }
    if (widget.busy != oldWidget.busy) {
      if (widget.busy) {
        // Fresh turn: start the elapsed clock and collapse the history.
        _stepsOpen = false;
        _stepSeconds = 0;
        _stepClock?.cancel();
        _stepClock = Timer.periodic(const Duration(seconds: 1), (_) {
          if (mounted && widget.busy) setState(() => _stepSeconds++);
        });
      } else {
        _stepClock?.cancel();
        _stepClock = null;
      }
    }
    if (widget.attachments.length != oldWidget.attachments.length) {
      _syncCanSend();
    }
    final editingId = _editingId;
    if (editingId != null && !widget.messages.any((m) => m.id == editingId)) {
      // The bubble we were editing is gone (chat cleared). Drop edit mode so the
      // next Send cannot target a message that no longer exists.
      _editingId = null;
      _draftBeforeEdit = '';
    }
  }

  void _toBottom() {
    if (!_scroll.hasClients) return;
    _scroll.animateTo(
      _scroll.position.maxScrollExtent,
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOut,
    );
  }

  /// Telegram behaviour: the bubble's text is loaded into THIS composer, the
  /// composer switches to edit mode, and Send replaces that exact bubble.
  void _beginEdit(SmartisChatMessage message) {
    if (widget.onEditMessage == null || widget.busy) return;
    setState(() {
      _draftBeforeEdit = _controller.text;
      _editingId = message.id;
      _controller.text = message.text;
      _controller.selection = TextSelection.collapsed(offset: _controller.text.length);
      _canSend = message.text.trim().isNotEmpty;
    });
    _focus.requestFocus();
  }

  void _cancelEdit() {
    if (_editingId == null) return;
    setState(() {
      _editingId = null;
      _controller.text = _draftBeforeEdit;
      _draftBeforeEdit = '';
      _controller.selection = TextSelection.collapsed(offset: _controller.text.length);
      _canSend = _controller.text.trim().isNotEmpty;
    });
    _focus.requestFocus();
  }

  void _submit() {
    final value = _controller.text.trim();
    if (widget.busy || widget.attachmentsBusy) return;
    final editingId = _editingId;
    if (editingId != null && widget.onEditMessage != null) {
      if (value.isEmpty) return;
      // In-place replacement: onEditMessage replaces THE bubble and the app
      // re-runs the edited text; the composer change is only the UI half.
      _controller.clear();
      setState(() {
        _editingId = null;
        _draftBeforeEdit = '';
      });
      _syncCanSend();
      widget.onEditMessage!(editingId, value);
      _focus.requestFocus();
      return;
    }
    if (value.isEmpty && widget.attachments.isEmpty) return;
    _controller.clear();
    _syncCanSend();
    widget.onSend(value);
    _focus.requestFocus();
  }

  @override
  void dispose() {
    _stepClock?.cancel();
    _controller.dispose();
    _focus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.escape): _cancelEdit,
      },
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xFF070709),
          borderRadius: BorderRadius.circular(26),
          border: Border.all(color: gold.withOpacity(.16)),
        ),
        child: Column(
          children: [
            _header(),
            Expanded(
              child: widget.messages.isEmpty && !widget.busy
                  ? _empty()
                  : ListView.builder(
                      controller: _scroll,
                      padding: const EdgeInsets.fromLTRB(16, 10, 16, 8),
                      itemCount: widget.messages.length + (widget.busy ? 1 : 0),
                      itemBuilder: (context, index) {
                        if (widget.busy && index == widget.messages.length) {
                          return _activityStrip();
                        }
                        final message = widget.messages[index];
                        return _bubble(
                          message,
                          index == widget.messages.length - 1,
                          message.id == _editingId,
                        );
                      },
                    ),
            ),
            if (_editingId != null) _editBanner(),
            if (widget.attachments.isNotEmpty || widget.attachmentsBusy) _attachmentRow(),
            _composer(),
          ],
        ),
      ),
    );
  }

  /// Pinned attachment chips above the composer, ChatGPT-style: each chip can
  /// be removed with its X, and stays pinned after Send for follow-up questions.
  Widget _attachmentRow() => Container(
        margin: const EdgeInsets.fromLTRB(12, 2, 12, 6),
        child: Wrap(
          spacing: 8,
          runSpacing: 6,
          alignment: WrapAlignment.end,
          children: [
            for (final item in widget.attachments) _attachmentChip(item),
            if (widget.attachmentsBusy) _uploadingChip(),
          ],
        ),
      );

  Widget _attachmentChip(ChatAttachmentChip item) {
    final icon = switch (item.kind) {
      'zip' => Icons.folder_zip_rounded,
      'image' => Icons.image_rounded,
      'text' => Icons.description_rounded,
      _ => Icons.insert_drive_file_rounded,
    };
    return Tooltip(
      message: item.name,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 220),
        padding: const EdgeInsets.fromLTRB(9, 5, 4, 5),
        decoration: BoxDecoration(
          color: gold.withOpacity(.08),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: gold.withOpacity(.35)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: gold.withOpacity(.9)),
            const SizedBox(width: 6),
            Flexible(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Color(0xFFE8D9A0), fontSize: 10.5, fontWeight: FontWeight.w600),
                  ),
                  if (item.sizeLabel.isNotEmpty)
                    Text(item.sizeLabel, style: const TextStyle(color: Colors.white38, fontSize: 8.5)),
                ],
              ),
            ),
            const SizedBox(width: 4),
            InkWell(
              borderRadius: BorderRadius.circular(10),
              onTap: widget.onRemoveAttachment == null ? null : () => widget.onRemoveAttachment!(item.id),
              child: const Padding(
                padding: EdgeInsets.all(3),
                child: Icon(Icons.close_rounded, size: 13, color: Colors.white54),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _uploadingChip() => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(.05),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: Colors.white.withOpacity(.14)),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(width: 11, height: 11, child: CircularProgressIndicator(strokeWidth: 1.4, color: Colors.white54)),
            SizedBox(width: 7),
            Text('در حال آپلود...', style: TextStyle(color: Colors.white54, fontSize: 10.5)),
          ],
        ),
      );

  Widget _editBanner() => Container(        margin: const EdgeInsets.fromLTRB(12, 0, 12, 6),
        padding: const EdgeInsets.fromLTRB(12, 7, 6, 7),
        decoration: BoxDecoration(
          color: gold.withOpacity(.08),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: gold.withOpacity(.30)),
        ),
        child: Row(
          children: [
            Icon(Icons.edit_rounded, size: 15, color: gold.withOpacity(.85)),
            const SizedBox(width: 8),
            const Expanded(
              child: Text(
                'در حال ویرایش پیام — ارسال، همان پیام را جایگزین می‌کند و دستور ویرایش‌شده دوباره اجرا می‌شود.',
                textDirection: TextDirection.rtl,
                textAlign: TextAlign.right,
                style: TextStyle(color: Color(0xFFE8D9A0), fontSize: 10.5, height: 1.4),
              ),
            ),
            Tooltip(
              message: 'لغو ویرایش (Esc)',
              child: InkWell(
                borderRadius: BorderRadius.circular(10),
                onTap: _cancelEdit,
                child: const Padding(
                  padding: EdgeInsets.all(4),
                  child: Icon(Icons.close_rounded, size: 16, color: Colors.white54),
                ),
              ),
            ),
          ],
        ),
      );

  Widget _header() => Padding(
        padding: const EdgeInsets.fromLTRB(18, 14, 18, 8),
        child: Row(
          children: [
            Container(
              width: 38,
              height: 38,
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: gold.withOpacity(.08),
                border: Border.all(color: gold.withOpacity(.45)),
                boxShadow: [BoxShadow(color: gold.withOpacity(.22), blurRadius: 14)],
              ),
              child: const _TopDownBrainIcon(size: 22),
            ),
            const SizedBox(width: 10),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Smartis', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15)),
                  SizedBox(height: 2),
                  Text('دستیار هوشمند ویندوز', style: TextStyle(color: Colors.white38, fontSize: 10.5)),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
              decoration: BoxDecoration(
                color: const Color(0xFF2ECC71).withOpacity(.12),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: const Color(0xFF2ECC71).withOpacity(.4)),
              ),
              child: const Text('LOCAL', style: TextStyle(color: Color(0xFF2ECC71), fontSize: 9, letterSpacing: 1, fontWeight: FontWeight.w700)),
            ),
          ],
        ),
      );

  Widget _empty() => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.forum_rounded, color: gold.withOpacity(.35), size: 44),
            const SizedBox(height: 12),
            const Text('هر چیزی بپرسی، جواب می‌دم.', style: TextStyle(color: Colors.white54, fontSize: 13)),
            const SizedBox(height: 6),
            Text('تایپ کن یا از میکروفون استفاده کن.', style: TextStyle(color: Colors.white.withOpacity(.28), fontSize: 11)),
          ],
        ),
      );

  /// Live progress strip shown while Smartis works, in place of the old
  /// "Smartis is typing…" pill. Collapsed by default: a mini copy of the main
  /// orb (same breathing animation) + the CURRENT step + elapsed seconds + a
  /// small triangle the user taps to unfold the full step history.
  Widget _activityStrip() {
    final steps = widget.steps;
    final current = steps.isEmpty ? null : steps.last;
    final label = current?.text ?? 'در حال آماده‌سازی…';
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 560),
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.fromLTRB(10, 7, 6, 7),
        decoration: BoxDecoration(
          color: const Color(0xFF121216),
          borderRadius: const BorderRadius.only(
            topLeft: Radius.circular(16),
            topRight: Radius.circular(16),
            bottomRight: Radius.circular(16),
            bottomLeft: Radius.circular(4),
          ),
          border: Border.all(color: gold.withOpacity(.22)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            InkWell(
              borderRadius: BorderRadius.circular(10),
              onTap: () => setState(() => _stepsOpen = !_stepsOpen),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    SizedBox(
                      width: 34,
                      height: 34,
                      child: SmartisOrb(state: SmartisVisualState.thinking, size: 34),
                    ),
                    const SizedBox(width: 9),
                    Expanded(
                      child: Text(
                        label,
                        textDirection: TextDirection.rtl,
                        textAlign: TextAlign.right,
                        style: const TextStyle(
                          color: Color(0xFFE8D9A0),
                          fontSize: 11.5,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    if (_stepSeconds > 0) ...[
                      const SizedBox(width: 8),
                      Text(
                        '$_stepSeconds ثانیه',
                        style: const TextStyle(color: Colors.white30, fontSize: 9.5),
                      ),
                    ],
                    const SizedBox(width: 4),
                    AnimatedRotation(
                      turns: _stepsOpen ? .5 : 0,
                      duration: const Duration(milliseconds: 180),
                      child: Icon(
                        Icons.arrow_drop_down_rounded,
                        size: 22,
                        color: gold.withOpacity(.85),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            if (_stepsOpen && steps.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(6, 4, 6, 6),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (int i = 0; i < steps.length; i++)
                      _stepRow(steps[i], i == steps.length - 1),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _stepRow(ChatStep step, bool isCurrent) {
    return Padding(
      padding: const EdgeInsets.only(top: 4, left: 2, right: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            isCurrent ? _stepIcon(step.icon) : Icons.check_circle_rounded,
            size: 13,
            color: isCurrent ? gold : const Color(0xFF2ECC71).withOpacity(.75),
          ),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              step.text,
              textDirection: TextDirection.rtl,
              textAlign: TextAlign.right,
              style: TextStyle(
                color: isCurrent ? const Color(0xFFEDEDEF) : Colors.white38,
                fontSize: 11,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Backend step icon keys ("brain", "web", "code", …) -> Material icons.
  IconData _stepIcon(String key) {
    switch (key) {
      case 'attach':
        return Icons.attach_file_rounded;
      case 'brain':
        return Icons.psychology_rounded;
      case 'open':
        return Icons.open_in_new_rounded;
      case 'web':
        return Icons.public_rounded;
      case 'wiki':
        return Icons.menu_book_rounded;
      case 'search':
        return Icons.search_rounded;
      case 'type':
        return Icons.keyboard_rounded;
      case 'code':
        return Icons.code_rounded;
      case 'settings':
        return Icons.settings_rounded;
      case 'folder':
        return Icons.folder_rounded;
      case 'file':
        return Icons.description_rounded;
      case 'delete':
        return Icons.delete_outline_rounded;
      case 'close':
        return Icons.close_rounded;
      case 'volume':
        return Icons.volume_up_rounded;
      case 'media':
        return Icons.play_circle_outline_rounded;
      case 'weather':
        return Icons.wb_sunny_rounded;
      case 'time':
        return Icons.schedule_rounded;
      case 'news':
        return Icons.newspaper_rounded;
      case 'calc':
        return Icons.calculate_rounded;
      case 'system':
        return Icons.memory_rounded;
      case 'power':
        return Icons.power_settings_new_rounded;
      default:
        return Icons.bolt_rounded;
    }
  }

  Widget _bubble(SmartisChatMessage message, bool isLast, bool editing) {
    final user = message.fromUser;
    final showConfirm = message.confirm && isLast && !widget.busy && (widget.onConfirm != null || widget.onCancel != null);
    final bubbleColor = user ? gold.withOpacity(.14) : const Color(0xFF121216);
    final borderColor = editing ? gold.withOpacity(.90) : (user ? gold.withOpacity(.45) : Colors.white.withOpacity(.08));
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 140),
        constraints: const BoxConstraints(maxWidth: 560),
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.fromLTRB(14, 11, 14, 8),
        decoration: BoxDecoration(
          color: bubbleColor,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(user ? 16 : 4),
            bottomRight: Radius.circular(user ? 4 : 16),
          ),
          border: Border.all(color: borderColor, width: editing ? 1.6 : 1.0),
          boxShadow: editing ? [BoxShadow(color: gold.withOpacity(.16), blurRadius: 16)] : null,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message.text,
              textDirection: _messageDirection(message.text),
              textAlign: _messageDirection(message.text) == TextDirection.rtl ? TextAlign.right : TextAlign.left,
              style: const TextStyle(color: Color(0xFFEDEDEF), fontSize: 13, height: 1.65),
            ),
            if (showConfirm) _confirmRow(),
            const SizedBox(height: 5),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (message.provider != null && message.provider!.isNotEmpty)
                  Text(message.provider!, style: const TextStyle(color: Colors.white24, fontSize: 8.5, fontFamily: 'Consolas')),
                const SizedBox(width: 8),
                Text(message.time, style: const TextStyle(color: Colors.white24, fontSize: 9)),
                if (message.edited) ...[
                  const SizedBox(width: 5),
                  const Text('ویرایش‌شده', style: TextStyle(color: Colors.white24, fontSize: 8.5)),
                ],
                if (user) ...[
                  const SizedBox(width: 7),
                  _messageAction(
                    icon: Icons.edit_rounded,
                    tooltip: 'ویرایش پیام',
                    onTap: (widget.busy || widget.onEditMessage == null || editing)
                        ? null
                        : () => _beginEdit(message),
                  ),
                  const SizedBox(width: 3),
                  _messageAction(
                    icon: Icons.content_copy_rounded,
                    tooltip: 'کپی پیام',
                    onTap: widget.onCopyMessage == null ? null : () => widget.onCopyMessage!(message.text),
                  ),
                  const SizedBox(width: 4),
                  Icon(Icons.done_all_rounded, size: 12, color: gold.withOpacity(.75)),
                ] else if (widget.onCopyMessage != null) ...[
                  const SizedBox(width: 7),
                  _messageAction(
                    icon: Icons.content_copy_rounded,
                    tooltip: 'کپی پاسخ',
                    onTap: () => widget.onCopyMessage!(message.text),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }


  TextDirection _messageDirection(String text) =>
      RegExp(r'[\u0600-\u06FF]').hasMatch(text) ? TextDirection.rtl : TextDirection.ltr;

  Widget _confirmRow() => Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _confirmButton('تأیید', Icons.check_rounded, const Color(0xFF2ECC71), widget.onConfirm),
            const SizedBox(width: 8),
            _confirmButton('لغو', Icons.close_rounded, Colors.redAccent, widget.onCancel),
          ],
        ),
      );

  Widget _confirmButton(String label, IconData icon, Color color, VoidCallback? onTap) => InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: color.withOpacity(.12),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: color.withOpacity(.55)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 14, color: color),
              const SizedBox(width: 5),
              Text(label, style: TextStyle(color: color, fontSize: 11.5, fontWeight: FontWeight.w700)),
            ],
          ),
        ),
      );

  Widget _messageAction({required IconData icon, required String tooltip, VoidCallback? onTap}) {
    return Tooltip(
      message: tooltip,
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(4),
          child: Icon(icon, size: 14, color: onTap == null ? Colors.white12 : Colors.white38),
        ),
      ),
    );
  }

  Widget _composer() => Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 14),
        child: Container(
          height: 54,
          padding: const EdgeInsets.symmetric(horizontal: 5),
          decoration: BoxDecoration(
            color: const Color(0xFF111114),
            borderRadius: BorderRadius.circular(28),
            border: Border.all(color: gold.withOpacity(_editingId != null ? .55 : .18)),
          ),
          child: Row(
            children: [
              _composerIcon(
                icon: Icons.add_rounded,
                tooltip: 'افزودن فایل یا زیپ به گفتگو',
                color: widget.attachments.isNotEmpty ? gold : Colors.white54,
                onTap: widget.onPickFiles ?? () => _focus.requestFocus(),
              ),
              const SizedBox(width: 3),
              Expanded(
                child: TextField(
                  controller: _controller,
                  focusNode: _focus,
                  readOnly: widget.busy,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _submit(),
                  textDirection: TextDirection.rtl,
                  textAlign: TextAlign.right,
                  style: const TextStyle(color: Colors.white, fontSize: 13),
                  decoration: InputDecoration(
                    isDense: true,
                    border: InputBorder.none,
                    hintText: _editingId != null ? 'متن پیام را ویرایش کن…' : 'پیام یا دستور بنویس…',
                    hintStyle: const TextStyle(color: Colors.white30, fontSize: 11.5),
                  ),
                ),
              ),
              const SizedBox(width: 3),
              _thinkingButton(),
              const SizedBox(width: 3),
              _toggleIcon(
                icon: widget.micMuted ? Icons.mic_off_rounded : Icons.mic_rounded,
                tooltip: widget.micMuted ? 'وصل کردن میکروفون' : 'قطع میکروفون',
                active: !widget.micMuted,
                onTap: widget.onToggleMic,
              ),
              const SizedBox(width: 3),
              _toggleIcon(
                icon: widget.voiceMuted ? Icons.volume_off_rounded : Icons.volume_up_rounded,
                tooltip: widget.voiceMuted ? 'وصل کردن صدای اسمارتیز' : 'قطع صدای اسمارتیز',
                active: !widget.voiceMuted,
                onTap: widget.onToggleVoice,
              ),
              const SizedBox(width: 3),
              _sendButton(),
            ],
          ),
        ),
      );

  Widget _thinkingButton() {
    final active = widget.thinking;
    return Tooltip(
      message: active ? 'فکر کردن فعال' : 'فکر کردن غیرفعال',
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: active ? gold.withOpacity(.13) : Colors.transparent,
          border: Border.all(color: active ? gold.withOpacity(.55) : Colors.white.withOpacity(.10)),
        ),
        child: Material(
          color: Colors.transparent,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: widget.busy ? null : (widget.onThinkingChanged == null ? null : () => widget.onThinkingChanged!(!active)),
            child: Center(child: _TopDownBrainIcon(size: 18, color: active ? gold : Colors.white38)),
          ),
        ),
      ),
    );
  }

  Widget _composerIcon({required IconData icon, required String tooltip, required Color color, required VoidCallback? onTap}) {
    return Tooltip(
      message: tooltip,
      child: SizedBox(
        width: 36,
        height: 36,
        child: Material(
          color: Colors.transparent,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: Icon(icon, size: 21, color: onTap == null ? Colors.white.withOpacity(.20) : color),
          ),
        ),
      ),
    );
  }

  /// Mic / speaker toggle in the composer. Muted (off) shows a dim red accent
  /// so the state is visible at a glance; on keeps the gold identity.
  Widget _toggleIcon({required IconData icon, required String tooltip, required bool active, required VoidCallback? onTap}) {
    return Tooltip(
      message: tooltip,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: active ? Colors.transparent : Colors.redAccent.withOpacity(.10),
          border: Border.all(color: active ? Colors.white.withOpacity(.10) : Colors.redAccent.withOpacity(.35)),
        ),
        child: Material(
          color: Colors.transparent,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: Icon(icon, size: 19, color: active ? gold : Colors.redAccent.withOpacity(.85)),
          ),
        ),
      ),
    );
  }

  Widget _sendButton() {
    if (widget.busy && widget.onStop != null) {
      return Tooltip(
        message: 'توقف',
        child: Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: const Color(0xFF2A1717),
            border: Border.all(color: Colors.redAccent.withOpacity(.55)),
            boxShadow: [BoxShadow(color: Colors.redAccent.withOpacity(.18), blurRadius: 14)],
          ),
          child: Material(
            color: Colors.transparent,
            shape: const CircleBorder(),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: widget.onStop,
              child: const Icon(Icons.stop_rounded, size: 23, color: Colors.redAccent),
            ),
          ),
        ),
      );
    }
    final active = _canSend && !widget.busy && !widget.attachmentsBusy;
    final editing = _editingId != null;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      width: 42,
      height: 42,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: active
              ? const [Color(0xFFFFE55C), Color(0xFFF0B400)]
              : const [Color(0xFF1A1A1F), Color(0xFF141418)],
        ),
        border: Border.all(color: active ? Colors.transparent : gold.withOpacity(.20)),
        boxShadow: active ? [BoxShadow(color: gold.withOpacity(.36), blurRadius: 14)] : null,
      ),
      child: Material(
        color: Colors.transparent,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: active ? _submit : null,
          child: editing
              ? Icon(Icons.check_rounded, size: 24, color: active ? const Color(0xFF14140A) : Colors.white24)
              : Transform.translate(
                  offset: const Offset(-1.5, 0),
                  child: Icon(Icons.arrow_upward_rounded, size: 23, color: active ? const Color(0xFF14140A) : Colors.white24),
                ),
        ),
      ),
    );
  }
}
