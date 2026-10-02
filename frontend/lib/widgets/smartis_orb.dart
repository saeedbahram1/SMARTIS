import 'dart:math' as math;
import 'package:flutter/material.dart';

enum SmartisVisualState { idle, listening, thinking, speaking }

class SmartisOrb extends StatefulWidget {
  final SmartisVisualState state;
  final double level;

  const SmartisOrb({
    super.key,
    required this.state,
    this.level = 0,
  });

  @override
  State<SmartisOrb> createState() => _SmartisOrbState();
}

class _SmartisOrbState extends State<SmartisOrb>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2600),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 390,
      height: 390,
      child: RepaintBoundary(
        child: AnimatedBuilder(
          animation: _controller,
          builder: (_, __) => CustomPaint(
            painter: _OrbPainter(
              t: _controller.value,
              state: widget.state,
              level: widget.level.clamp(0.0, 1.0).toDouble(),
            ),
          ),
        ),
      ),
    );
  }
}

class _OrbPainter extends CustomPainter {
  final double t;
  final SmartisVisualState state;
  final double level;

  static const gold = Color(0xFFFFD700);

  const _OrbPainter({
    required this.t,
    required this.state,
    required this.level,
  });

  double get phase => t * math.pi * 2;

  @override
  void paint(Canvas canvas, Size size) {
    final c = Offset(size.width / 2, size.height / 2);
    final base = size.shortestSide * .115;

    switch (state) {
      case SmartisVisualState.idle:
        _paintIdle(canvas, c, base);
      case SmartisVisualState.listening:
        _paintListening(canvas, c, base);
      case SmartisVisualState.thinking:
        _paintThinking(canvas, c, base);
      case SmartisVisualState.speaking:
        _paintSpeaking(canvas, c, base);
    }

    _paintCore(canvas, c, base);
  }

  void _paintIdle(Canvas canvas, Offset c, double r) {
    final breathe = 1 + .035 * math.sin(phase);
    _glow(canvas, c, r * 3.2, .20);
    _arcRing(canvas, c, r * 1.75 * breathe, 0, math.pi * 1.35, 1.2, .28);
    _arcRing(canvas, c, r * 2.05, phase * .25, math.pi * .72, 1.0, .20);
    _arcRing(canvas, c, r * 2.32, -phase * .18, math.pi * .52, .8, .15);
    _orbitDots(canvas, c, r * 2.28, 12, phase * .20, .12, 1.2);
  }

  void _paintListening(Canvas canvas, Offset c, double r) {
    // Keep rotation subtle; the microphone level is the dominant driver so the
    // HUD visibly follows the user's real voice instead of a fake pulse.
    final energy = math.pow(level.clamp(0.0, 1.0), .72).toDouble();
    final pulse = 1.0 + energy * .18;
    _glow(canvas, c, r * (2.9 + energy * 2.2), .20 + energy * .38);

    for (int i = 0; i < 6; i++) {
      final rr = r * (1.52 + i * .18 + energy * (i.isEven ? .17 : .10));
      final start = phase * (.26 + i * .018) + i * .95;
      final sweep = .42 + energy * 1.75 + (i % 3) * .10;
      _arcRing(
        canvas,
        c,
        rr * pulse,
        start,
        sweep,
        1.1 + energy * 1.9,
        (.16 - i * .014).clamp(.06, .16) + energy * .22,
      );
    }

    _orbitDots(
      canvas,
      c,
      r * (1.95 + energy * .62),
      18,
      -phase * .35,
      .18 + energy * .56,
      1.25 + energy * 2.5,
    );

    for (int i = 0; i < 32; i++) {
      final a = i / 32 * math.pi * 2 + phase * .05;
      // A stable per-bar shape plus real mic energy: no independent fake
      // amplitude oscillation that could look out of sync with speech.
      final shape = .30 + .70 * (math.sin(i * .91).abs());
      final len = 3.5 + energy * (10 + 26 * shape);
      final inner = r * 1.43;
      _line(
        canvas,
        c,
        a,
        inner,
        inner + len,
        .9 + energy * 1.7,
        (.12 + energy * .56).clamp(0.0, .82),
      );
    }
  }

  void _paintThinking(Canvas canvas, Offset c, double r) {
    _glow(canvas, c, r * 3.8, .30);

    // Four independent segmented rotors make "thinking" visibly different.
    for (int ring = 0; ring < 4; ring++) {
      final rr = r * (1.60 + ring * .27);
      final direction = ring.isEven ? 1.0 : -1.0;
      final start = phase * direction * (.75 + ring * .10) + ring * .8;
      for (int seg = 0; seg < 7; seg++) {
        final a = start + seg * (math.pi * 2 / 7);
        _arcRing(canvas, c, rr, a, .34 + (ring == 0 ? .08 : 0),
            1.2 + (3 - ring) * .15, (.22 - ring * .03).clamp(.06, .22));
      }
    }

    _orbitDots(canvas, c, r * 2.25, 10, phase * 1.1, .28, 1.6);
  }

  void _paintSpeaking(Canvas canvas, Offset c, double r) {
    final energy = .22 + level * .98;
    _glow(canvas, c, r * (3.0 + level * 2.0), .24 + level * .30);

    // Concentric segmented "voice spectrum" driven by playback position.
    for (int ring = 0; ring < 5; ring++) {
      final rr = r * (1.55 + ring * .24);
      final speed = ring.isEven ? 1.0 : -1.0;
      final start = phase * speed * (.35 + ring * .05);
      for (int seg = 0; seg < 12; seg++) {
        final a = start + seg * math.pi * 2 / 12;
        final wordWave =
            (.5 + .5 * math.sin(phase * (2.4 + ring * .25) + seg * 1.17));
        final sweep = .18 + energy * (.12 + wordWave * .18);
        _arcRing(canvas, c, rr, a, sweep, 1.4 + level * .9,
            (.20 + level * .20).clamp(0.0, .55));
      }
    }

    // Uneven radial bars simulate the changing intensity of spoken words.
    for (int i = 0; i < 40; i++) {
      final a = i / 40 * math.pi * 2;
      final speechShape = .25 + .75 * math.sin(i * .73).abs();
      final len = 5 + level * (9 + 27 * speechShape);
      _line(canvas, c, a, r * 1.45, r * 1.45 + len,
          1.0 + level * 1.5, (.20 + level * .46).clamp(0.0, .75));
    }

    _orbitDots(canvas, c, r * (2.0 + level * .55), 24,
        phase * .42, .35 + level * .45, 1.2 + level * 2.0);
  }

  void _paintCore(Canvas canvas, Offset c, double r) {
    final pulse = 1 + .045 * math.sin(phase * 2.0) + level * .16;
    final coreR = r * 1.22 * pulse;

    canvas.drawCircle(
      c,
      coreR * 2.4,
      Paint()
        ..shader = RadialGradient(
          colors: [
            gold.withOpacity(.30 + level * .15),
            gold.withOpacity(.08),
            Colors.transparent,
          ],
        ).createShader(Rect.fromCircle(center: c, radius: coreR * 2.4)),
    );

    canvas.drawCircle(
      c,
      coreR,
      Paint()
        ..shader = const RadialGradient(
          colors: [Colors.white, gold, Color(0xFF8A6A00), Colors.transparent],
          stops: [0, .22, .60, 1],
        ).createShader(Rect.fromCircle(center: c, radius: coreR)),
    );

    canvas.drawCircle(
      c,
      coreR * .42,
      Paint()..color = Colors.white.withOpacity(.92),
    );
  }

  void _glow(Canvas canvas, Offset c, double radius, double opacity) {
    canvas.drawCircle(
      c,
      radius,
      Paint()
        ..shader = RadialGradient(
          colors: [
            gold.withOpacity(opacity),
            gold.withOpacity(opacity * .22),
            Colors.transparent,
          ],
        ).createShader(Rect.fromCircle(center: c, radius: radius)),
    );
  }

  void _arcRing(
    Canvas canvas,
    Offset c,
    double radius,
    double start,
    double sweep,
    double width,
    double opacity,
  ) {
    final rect = Rect.fromCircle(center: c, radius: radius);
    canvas.drawArc(
      rect,
      start,
      sweep,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = width
        ..color = gold.withOpacity(opacity),
    );
  }

  void _orbitDots(
    Canvas canvas,
    Offset c,
    double radius,
    int count,
    double rotation,
    double opacity,
    double dotRadius,
  ) {
    for (int i = 0; i < count; i++) {
      final a = rotation + i / count * math.pi * 2;
      final wobble = 1 + .04 * math.sin(phase * 2 + i);
      final p = Offset(
        c.dx + math.cos(a) * radius * wobble,
        c.dy + math.sin(a) * radius * wobble,
      );
      canvas.drawCircle(
        p,
        dotRadius,
        Paint()..color = gold.withOpacity(opacity),
      );
    }
  }

  void _line(
    Canvas canvas,
    Offset c,
    double angle,
    double inner,
    double outer,
    double width,
    double opacity,
  ) {
    final a = Offset(
      c.dx + math.cos(angle) * inner,
      c.dy + math.sin(angle) * inner,
    );
    final b = Offset(
      c.dx + math.cos(angle) * outer,
      c.dy + math.sin(angle) * outer,
    );
    canvas.drawLine(
      a,
      b,
      Paint()
        ..strokeWidth = width
        ..strokeCap = StrokeCap.round
        ..color = gold.withOpacity(opacity),
    );
  }

  @override
  bool shouldRepaint(covariant _OrbPainter old) =>
      old.t != t || old.state != state || old.level != level;
}
