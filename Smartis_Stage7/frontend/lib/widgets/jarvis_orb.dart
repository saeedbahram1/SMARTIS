import 'dart:math' as math;
import 'package:flutter/material.dart';

class JarvisOrb extends StatefulWidget {
  final bool active;
  const JarvisOrb({super.key, this.active = false});

  @override
  State<JarvisOrb> createState() => _JarvisOrbState();
}

class _JarvisOrbState extends State<JarvisOrb>
    with SingleTickerProviderStateMixin {
  late final AnimationController controller;

  @override
  void initState() {
    super.initState();
    controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 8),
    )..repeat();
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 310,
      height: 310,
      child: AnimatedBuilder(
        animation: controller,
        builder: (_, __) {
          return CustomPaint(
            painter: _OrbPainter(controller.value, widget.active),
          );
        },
      ),
    );
  }
}

class _OrbPainter extends CustomPainter {
  final double t;
  final bool active;

  _OrbPainter(this.t, this.active);

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = math.min(size.width, size.height) * .31;

    final glow = Paint()
      ..shader = RadialGradient(
        colors: [
          (active ? const Color(0xFFFFD700) : Colors.cyanAccent).withOpacity(.34),
          (active ? const Color(0xFFFFD700) : Colors.cyan).withOpacity(.10),
          Colors.transparent,
        ],
      ).createShader(Rect.fromCircle(center: c, radius: r * 2.2));

    canvas.drawCircle(c, r * 2.1, glow);

    final core = Paint()
      ..shader = RadialGradient(
        colors: [
          Colors.white.withOpacity(.98),
          (active ? const Color(0xFFFFD700) : Colors.cyanAccent).withOpacity(.9),
          (active ? const Color(0xFFFFD700) : Colors.cyan).withOpacity(.18),
          Colors.transparent,
        ],
        stops: const [.0, .18, .55, 1],
      ).createShader(Rect.fromCircle(center: c, radius: r * 1.15));

    canvas.drawCircle(c, r * 1.15, core);

    for (int ring = 0; ring < 4; ring++) {
      final radius = r + ring * 18.0;
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.3
        ..color = (active ? const Color(0xFFFFD700) : Colors.cyanAccent).withOpacity(.20 - ring * .025);

      final rect = Rect.fromCircle(center: c, radius: radius);

      canvas.save();
      canvas.translate(c.dx, c.dy);
      canvas.rotate((t * 2 * math.pi) * (ring.isEven ? 1 : -1));
      canvas.translate(-c.dx, -c.dy);

      final path = Path();
      const pieces = 32;
      for (int i = 0; i < pieces; i++) {
        final a1 = (i / pieces) * 2 * math.pi;
        final a2 = a1 + .075 + ((ring + 1) % 3) * .02;
        path.addArc(rect, a1, a2 - a1);
      }
      canvas.drawPath(path, paint);
      canvas.restore();
    }

    final spokePaint = Paint()
      ..color = (active ? const Color(0xFFFFD700) : Colors.cyanAccent).withOpacity(.22)
      ..strokeWidth = 1;

    for (int i = 0; i < 12; i++) {
      final a = t * 2 * math.pi + i * math.pi / 6;
      final p1 = Offset(
        c.dx + math.cos(a) * r * .72,
        c.dy + math.sin(a) * r * .72,
      );
      final p2 = Offset(
        c.dx + math.cos(a) * r * 1.55,
        c.dy + math.sin(a) * r * 1.55,
      );
      canvas.drawLine(p1, p2, spokePaint);
    }
  }

  @override
  bool shouldRepaint(covariant _OrbPainter oldDelegate) => oldDelegate.t != t;
}
