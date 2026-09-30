import 'package:flutter/material.dart';

class SmartisChatMessage {
  final String text;
  final bool fromUser;
  final String time;
  final String? provider;

  const SmartisChatMessage({
    required this.text,
    required this.fromUser,
    this.time = '',
    this.provider,
  });
}

/// Typed-chat surface: message bubbles plus a Telegram-style composer.
class SmartisChatPanel extends StatefulWidget {
  final List<SmartisChatMessage> messages;
  final bool busy;
  final void Function(String text) onSend;
  final VoidCallback? onMic;

  const SmartisChatPanel({
    super.key,
    required this.messages,
    required this.onSend,
    this.busy = false,
    this.onMic,
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
    if (widget.messages.length != oldWidget.messages.length) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _toBottom());
    }
  }

  void _toBottom() {
    if (!_scroll.hasClients) return;
    _scroll.animateTo(
      _scroll.position.maxScrollExtent,
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOut,
    );
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
            child: widget.messages.isEmpty
                ? _empty()
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                    itemCount: widget.messages.length,
                    itemBuilder: (context, index) => _bubble(widget.messages[index]),
                  ),
          ),
          if (widget.busy) _typing(),
          _composer(),
        ],
      ),
    );
  }

  Widget _header() => Padding(
        padding: const EdgeInsets.fromLTRB(18, 16, 18, 10),
        child: Row(
          children: [
            Container(
              width: 34,
              height: 34,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: RadialGradient(colors: [Colors.white, gold, gold.withOpacity(.15)]),
                boxShadow: [BoxShadow(color: gold.withOpacity(.35), blurRadius: 14)],
              ),
            ),
            const SizedBox(width: 11),
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
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: const Color(0xFF2ECC71).withOpacity(.12),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: const Color(0xFF2ECC71).withOpacity(.4)),
              ),
              child: const Text('ONLINE', style: TextStyle(color: Color(0xFF2ECC71), fontSize: 9, letterSpacing: 1, fontWeight: FontWeight.w700)),
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

  Widget _typing() => Padding(
        padding: const EdgeInsets.only(left: 24, bottom: 6),
        child: Row(
          children: [
            SizedBox(
              width: 13,
              height: 13,
              child: CircularProgressIndicator(strokeWidth: 1.6, color: gold.withOpacity(.8)),
            ),
            const SizedBox(width: 9),
            const Text('Smartis در حال نوشتن...', style: TextStyle(color: Colors.white38, fontSize: 11)),
          ],
        ),
      );

  Widget _bubble(SmartisChatMessage message) {
    final user = message.fromUser;
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
              textDirection: TextDirection.rtl,
              style: const TextStyle(color: Color(0xFFEDEDEF), fontSize: 13, height: 1.65),
            ),
            const SizedBox(height: 5),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (message.provider != null && message.provider!.isNotEmpty)
                  Text(message.provider!, style: const TextStyle(color: Colors.white24, fontSize: 8.5, fontFamily: 'Consolas')),
                const SizedBox(width: 8),
                Text(message.time, style: const TextStyle(color: Colors.white24, fontSize: 9)),
                if (user) ...[
                  const SizedBox(width: 5),
                  Icon(Icons.done_all_rounded, size: 12, color: gold.withOpacity(.75)),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _composer() => Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: Row(
          children: [
            _sendButton(),
            const SizedBox(width: 9),
            Expanded(
              child: Container(
                height: 50,
                decoration: BoxDecoration(
                  color: const Color(0xFF111114),
                  borderRadius: BorderRadius.circular(26),
                  border: Border.all(color: gold.withOpacity(.20)),
                ),
                child: Row(
                  children: [
                    const SizedBox(width: 16),
                    Expanded(
                      child: TextField(
                        controller: _controller,
                        focusNode: _focus,
                        textInputAction: TextInputAction.send,
                        onSubmitted: (_) => _submit(),
                        textDirection: TextDirection.rtl,
                        style: const TextStyle(color: Colors.white, fontSize: 13),
                        decoration: const InputDecoration(
                          isDense: true,
                          border: InputBorder.none,
                          hintText: 'دستور صوتی یا متنی را تایپ کنید (مثال: گوگل رو باز کن بعد صدا رو روی ۲۰ درصد بذار)...',
                          hintStyle: TextStyle(color: Colors.white30, fontSize: 11.5),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      tooltip: 'جست‌وجو',
                      onPressed: () {},
                      icon: Icon(Icons.search_rounded, color: gold.withOpacity(.85), size: 21),
                    ),
                    const SizedBox(width: 4),
                  ],
                ),
              ),
            ),
            if (widget.onMic != null) ...[
              const SizedBox(width: 9),
              _micButton(),
            ],
          ],
        ),
      );

  /// Telegram-style circular send button with a paper-plane icon.
  Widget _sendButton() {
    final active = _canSend && !widget.busy;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      width: 50,
      height: 50,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: active
              ? const [Color(0xFFFFE55C), Color(0xFFF0B400)]
              : const [Color(0xFF1A1A1F), Color(0xFF141418)],
        ),
        border: Border.all(color: active ? Colors.transparent : gold.withOpacity(.25)),
        boxShadow: active
            ? [BoxShadow(color: gold.withOpacity(.42), blurRadius: 18, spreadRadius: 1)]
            : null,
      ),
      child: Material(
        color: Colors.transparent,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: active ? _submit : null,
          child: Transform.translate(
            offset: const Offset(-1.5, 0),
            child: Icon(
              Icons.send_rounded,
              size: 22,
              color: active ? const Color(0xFF14140A) : Colors.white24,
            ),
          ),
        ),
      ),
    );
  }

  Widget _micButton() => Container(
        width: 50,
        height: 50,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: const Color(0xFF111114),
          border: Border.all(color: gold.withOpacity(.22)),
        ),
        child: Material(
          color: Colors.transparent,
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: widget.onMic,
            child: const Icon(Icons.mic_rounded, color: gold, size: 21),
          ),
        ),
      );
}
