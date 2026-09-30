import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// One structured technical-log entry shown in the Smartis log panel.
class SmartisLogEntry {
  final String category;
  final String message;
  final String? detail;
  final String time;
  final bool userAction;

  const SmartisLogEntry({
    required this.category,
    required this.message,
    this.detail,
    this.time = '',
    this.userAction = false,
  });

  static const List<String> categories = <String>[
    'SYSTEM',
    'MEDIA',
    'EXECUTOR',
    'FAST_PATH',
    'PLANNER',
    'STT',
    'CONFIRMATION',
  ];

  static Color colorFor(String category) {
    switch (category.toUpperCase()) {
      case 'SYSTEM':
        return const Color(0xFF39C0ED);
      case 'MEDIA':
        return const Color(0xFFB388FF);
      case 'EXECUTOR':
        return const Color(0xFF4CE07A);
      case 'FAST_PATH':
        return const Color(0xFFFFA726);
      case 'PLANNER':
        return const Color(0xFFFF5FA2);
      case 'STT':
        return const Color(0xFF64B5F6);
      case 'CONFIRMATION':
        return const Color(0xFFFFC400);
      default:
        return const Color(0xFFFFD700);
    }
  }
}

/// Advanced technical-log panel: category filters, structured cards,
/// expandable payloads, copy-to-clipboard and a live connection footer.
class SmartisLogPanel extends StatefulWidget {
  final List<SmartisLogEntry> entries;
  final bool connected;

  const SmartisLogPanel({
    super.key,
    required this.entries,
    this.connected = true,
  });

  @override
  State<SmartisLogPanel> createState() => _SmartisLogPanelState();
}

class _SmartisLogPanelState extends State<SmartisLogPanel> {
  static const gold = Color(0xFFFFD700);
  final ScrollController _scroll = ScrollController();
  String _filter = 'ALL';
  int? _expandedId;

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  List<SmartisLogEntry> get _visible {
    final list = widget.entries;
    if (_filter == 'ALL') return list.reversed.toList();
    return list.where((e) => e.category.toUpperCase() == _filter).toList().reversed.toList();
  }

  void _copy(SmartisLogEntry entry) {
    final buffer = StringBuffer()
      ..writeln('[${entry.time}] [${entry.category}] ${entry.message}');
    if (entry.detail != null && entry.detail!.isNotEmpty) {
      buffer.writeln(entry.detail);
    }
    Clipboard.setData(ClipboardData(text: buffer.toString()));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('کپی شد', style: TextStyle(fontSize: 12)),
        duration: Duration(milliseconds: 900),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final visible = _visible;
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF070709),
        borderRadius: BorderRadius.circular(26),
        border: Border.all(color: gold.withOpacity(.16)),
      ),
      child: Column(
        children: [
          _header(),
          _filters(),
          Expanded(
            child: visible.isEmpty
                ? Center(
                    child: Text(
                      'هنوز رویدادی ثبت نشده است.',
                      style: TextStyle(color: Colors.white.withOpacity(.28), fontSize: 12),
                    ),
                  )
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
                    itemCount: visible.length,
                    itemBuilder: (context, index) {
                      final entry = visible[index];
                      final id = widget.entries.length - index;
                      return _card(entry, id, _expandedId == id);
                    },
                  ),
          ),
          _footer(),
        ],
      ),
    );
  }

  Widget _header() => Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 12, 8),
        child: Row(
          children: [
            const Icon(Icons.insights_rounded, color: gold, size: 20),
            const SizedBox(width: 9),
            const Expanded(
              child: Text(
                'پنل لاگ‌های فنی (Technical Logs)',
                textAlign: TextAlign.right,
                style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13.5),
              ),
            ),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
              decoration: BoxDecoration(
                color: gold.withOpacity(.10),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: gold.withOpacity(.25)),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('${widget.entries.length}',
                      style: const TextStyle(color: gold, fontSize: 11, fontWeight: FontWeight.w700)),
                  const SizedBox(width: 5),
                  const Text('رویداد', style: TextStyle(color: Colors.white54, fontSize: 10)),
                ],
              ),
            ),
            IconButton(
              tooltip: 'پاک کردن لاگ‌ها',
              visualDensity: VisualDensity.compact,
              onPressed: () => setState(() {
                widget.entries.clear();
                _expandedId = null;
              }),
              icon: const Icon(Icons.delete_outline_rounded, color: Colors.white38, size: 18),
            ),
          ],
        ),
      );

  Widget _filters() {
    final chips = <String>['ALL', ...SmartisLogEntry.categories];
    return SizedBox(
      height: 38,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        reverse: true,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        itemCount: chips.length,
        separatorBuilder: (_, __) => const SizedBox(width: 7),
        itemBuilder: (context, index) {
          final name = chips[index];
          final selected = _filter == name;
          final color = name == 'ALL' ? gold : SmartisLogEntry.colorFor(name);
          return Center(
            child: GestureDetector(
              onTap: () => setState(() => _filter = name),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 160),
                padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 6),
                decoration: BoxDecoration(
                  color: selected ? color.withOpacity(.16) : const Color(0xFF111114),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: selected ? color.withOpacity(.75) : Colors.white.withOpacity(.07)),
                ),
                child: Text(
                  name,
                  style: TextStyle(
                    color: selected ? color : Colors.white54,
                    fontSize: 10,
                    fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                    letterSpacing: .6,
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _card(SmartisLogEntry entry, int id, bool expanded) {
    final color = SmartisLogEntry.colorFor(entry.category);
    final hasDetail = entry.detail != null && entry.detail!.trim().isNotEmpty;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xFF0C0C10),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: color.withOpacity(.22)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 11, 12, 8),
              child: Row(
                children: [
                  const Spacer(),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
                        decoration: BoxDecoration(
                          color: color.withOpacity(.18),
                          borderRadius: BorderRadius.circular(20),
                          border: Border.all(color: color.withOpacity(.55)),
                        ),
                        child: Text(
                          entry.category,
                          style: TextStyle(
                            color: color,
                            fontSize: 9,
                            fontWeight: FontWeight.w800,
                            letterSpacing: .8,
                          ),
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        entry.time.isEmpty ? '--:--:--' : entry.time,
                        style: const TextStyle(color: Colors.white30, fontSize: 9, fontFamily: 'Consolas'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
              child: Text(
                entry.message,
                textAlign: TextAlign.right,
                textDirection: TextDirection.rtl,
                style: const TextStyle(color: Color(0xFFE8E8EA), fontSize: 12.5, height: 1.55),
              ),
            ),
            if (hasDetail)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
                child: GestureDetector(
                  onTap: () => setState(() => _expandedId = expanded ? null : id),
                  child: Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(.55),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: Colors.white.withOpacity(.06)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          entry.detail!,
                          maxLines: expanded ? 40 : 4,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Color(0xFF8FE39A),
                            fontSize: 10.5,
                            height: 1.5,
                            fontFamily: 'Consolas',
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          expanded ? '▲ بستن' : '▼ نمایش کامل',
                          style: TextStyle(color: gold.withOpacity(.7), fontSize: 9),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(6, 0, 6, 4),
              child: Row(
                children: [
                  IconButton(
                    tooltip: 'کپی',
                    visualDensity: VisualDensity.compact,
                    onPressed: () => _copy(entry),
                    icon: const Icon(Icons.copy_rounded, color: Colors.white30, size: 15),
                  ),
                  const Spacer(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _footer() => Container(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
        decoration: BoxDecoration(
          border: Border(top: BorderSide(color: Colors.white.withOpacity(.06))),
        ),
        child: Row(
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: widget.connected ? const Color(0xFF2ECC71) : const Color(0xFFE74C3C),
                boxShadow: [
                  BoxShadow(
                    color: (widget.connected ? const Color(0xFF2ECC71) : const Color(0xFFE74C3C)).withOpacity(.6),
                    blurRadius: 8,
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                widget.connected
                    ? 'FastAPI WebSocket: Connected (127.0.0.1:8765)'
                    : 'FastAPI WebSocket: Disconnected',
                style: const TextStyle(color: Colors.white54, fontSize: 10.5, fontFamily: 'Consolas'),
              ),
            ),
            Text(
              '${_visible.length} رویداد',
              style: const TextStyle(color: Colors.white38, fontSize: 10.5),
            ),
          ],
        ),
      );
}
