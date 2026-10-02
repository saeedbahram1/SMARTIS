import 'package:flutter/material.dart';

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
  final String text;
  final bool fromUser;
  final String time;
  final String? provider;
  final bool confirm;

  const SmartisChatMessage({
    required this.text,
    required this.fromUser,
    this.time = '',
    this.provider,
    this.confirm = false,
  });
}

/// ChatGPT-style chat surface. The busy indicator lives INSIDE the message
/// stream, immediately after the latest user bubble, then disappears when the
/// actual Smartis response is inserted.
class SmartisChatPanel extends StatefulWidget {
  final List<SmartisChatMessage> messages;
  final bool busy;
  final bool thinking;
  final ValueChanged<bool>? onThinkingChanged;
  final void Function(String text) onSend;
  final VoidCallback? onMic;
  final VoidCallback? onStop;
  final ValueChanged<String>? onCopyMessage;
  final VoidCallback? onConfirm;
  final VoidCallback? onCancel;

  const SmartisChatPanel({
    super.key,
    required this.messages,
    required this.onSend,
    this.busy = false,
    this.thinking = false,
    this.onThinkingChanged,
    this.onMic,
    this.onStop,
    this.onCopyMessage,
    this.onConfirm,
    this.onCancel,
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

  @override
  void initState() {
    super.initState();
    _controller.addListener(() {
      final next = _controller.text.trim().isNotEmpty;
      if (next != _canSend) setState(() => _canSend = next);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _focus.requestFocus());
  }

  @override
  void didUpdateWidget(covariant SmartisChatPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.messages.length != oldWidget.messages.length || widget.busy != oldWidget.busy) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _toBottom());
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

  /// Edit means: load the old text into the composer ONLY. The original
  /// bubble remains untouched, and pressing Send creates a new turn.
  void _editMessage(String text) {
    _controller.text = text;
    _controller.selection = TextSelection.collapsed(offset: _controller.text.length);
    setState(() => _canSend = text.trim().isNotEmpty);
    _focus.requestFocus();
  }

  void _submit() {
    final value = _controller.text.trim();
    if (value.isEmpty || widget.busy) return;
    _controller.clear();
    setState(() => _canSend = false);
    widget.onSend(value);
    _focus.requestFocus();
  }

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
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
                        return _typingBubble();
                      }
                      return _bubble(widget.messages[index], index == widget.messages.length - 1);
                    },
                  ),
          ),
          _composer(),
        ],
      ),
    );
  }

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

  Widget _typingBubble() => Align(
        alignment: Alignment.centerLeft,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 560),
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
          decoration: BoxDecoration(
            color: const Color(0xFF121216),
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(16),
              topRight: Radius.circular(16),
              bottomRight: Radius.circular(16),
              bottomLeft: Radius.circular(4),
            ),
            border: Border.all(color: Colors.white.withOpacity(.08)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox(
                width: 13,
                height: 13,
                child: CircularProgressIndicator(strokeWidth: 1.6, color: gold.withOpacity(.8)),
              ),
              const SizedBox(width: 9),
              const Text('Smartis در حال نوشتن است…', style: TextStyle(color: Colors.white38, fontSize: 11.5)),
            ],
          ),
        ),
      );

  Widget _bubble(SmartisChatMessage message, bool isLast) {
    final user = message.fromUser;
    final showConfirm = message.confirm && isLast && !widget.busy && (widget.onConfirm != null || widget.onCancel != null);
    final bubbleColor = user ? gold.withOpacity(.14) : const Color(0xFF121216);
    final borderColor = user ? gold.withOpacity(.45) : Colors.white.withOpacity(.08);
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
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
          border: Border.all(color: borderColor),
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
                if (user) ...[
                  const SizedBox(width: 7),
                  _messageAction(
                    icon: Icons.edit_rounded,
                    tooltip: 'ویرایش و ارسال دوباره',
                    onTap: widget.busy ? null : () => _editMessage(message.text),
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
            border: Border.all(color: gold.withOpacity(.18)),
          ),
          child: Row(
            children: [
              _composerIcon(
                icon: Icons.add_rounded,
                tooltip: 'گزینه‌های بیشتر',
                color: Colors.white54,
                onTap: () {
                  _focus.requestFocus();
                },
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
                  decoration: const InputDecoration(
                    isDense: true,
                    border: InputBorder.none,
                    hintText: 'پیام یا دستور بنویس…',
                    hintStyle: TextStyle(color: Colors.white30, fontSize: 11.5),
                  ),
                ),
              ),
              const SizedBox(width: 3),
              _thinkingButton(),
              if (widget.onMic != null) ...[
                const SizedBox(width: 3),
                _composerIcon(
                  icon: Icons.mic_rounded,
                  tooltip: 'بازنشانی میکروفون',
                  color: gold,
                  onTap: widget.onMic,
                ),
              ],
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
    final active = _canSend && !widget.busy;
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
          child: Transform.translate(
            offset: const Offset(-1.5, 0),
            child: Icon(Icons.arrow_upward_rounded, size: 23, color: active ? const Color(0xFF14140A) : Colors.white24),
          ),
        ),
      ),
    );
  }
}
