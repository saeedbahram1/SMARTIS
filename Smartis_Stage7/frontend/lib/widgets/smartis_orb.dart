import 'dart:math' as math;
import 'package:flutter/material.dart';
enum SmartisVisualState{idle,listening,thinking,speaking}
class SmartisOrb extends StatefulWidget{final SmartisVisualState state;final double level;const SmartisOrb({super.key,required this.state,this.level=0});@override State<SmartisOrb> createState()=>_SmartisOrbState();}
class _SmartisOrbState extends State<SmartisOrb> with SingleTickerProviderStateMixin{
 late final AnimationController controller;
 // A longer base cycle + the eased curve below is what makes the motion read
 // as calm/fluid (Iron-Man-HUD-like) instead of nervous/jittery. The old
 // 1700ms linear cycle was simply spinning too fast for the eye to read as
 // "breathing" rather than "glitching".
 @override void initState(){super.initState();controller=AnimationController(vsync:this,duration:const Duration(milliseconds:6000))..repeat();}
 @override void dispose(){controller.dispose();super.dispose();}
 @override Widget build(BuildContext context)=>SizedBox(width:360,height:360,child:AnimatedBuilder(animation:controller,builder:(_,__)=>CustomPaint(painter:_OrbPainter(controller.value,widget.state,widget.level))));
}
class _OrbPainter extends CustomPainter{
 final double t;final SmartisVisualState state;final double level;const _OrbPainter(this.t,this.state,this.level);static const gold=Color(0xFFFFD700);
 double get intensity=>switch(state){SmartisVisualState.idle=>.26,SmartisVisualState.listening=>.5+level*.65,SmartisVisualState.thinking=>.75,SmartisVisualState.speaking=>.66+.34*math.sin(t*math.pi*2)};
 @override void paint(Canvas c,Size s){
  final center=Offset(s.width/2,s.height/2),phase=t*math.pi*2;
  final pulse=switch(state){SmartisVisualState.idle=>1+.02*math.sin(phase),SmartisVisualState.listening=>1+.06*math.sin(phase*1.4)+.09*level,SmartisVisualState.thinking=>1+.05*math.sin(phase*1.4),SmartisVisualState.speaking=>1+.09*math.sin(phase*2)};
  final radius=s.shortestSide*.22*pulse;
  c.drawCircle(center,radius*3,Paint()..shader=RadialGradient(colors:[gold.withOpacity(.45*intensity),gold.withOpacity(.14*intensity),Colors.transparent]).createShader(Rect.fromCircle(center:center,radius:radius*3)));
  c.drawCircle(center,radius*1.35,Paint()..shader=RadialGradient(colors:[Colors.white.withOpacity(.98),gold.withOpacity(.96),gold.withOpacity(.2),Colors.transparent],stops:const[0,.22,.58,1]).createShader(Rect.fromCircle(center:center,radius:radius*1.35)));
  for(int ring=0;ring<6;ring++){
    final motion=switch(state){SmartisVisualState.idle=>math.sin(phase+ring)*1.5,SmartisVisualState.listening=>math.sin(phase*1.2+ring)*(3+level*10),SmartisVisualState.thinking=>math.sin(phase*1.5+ring)*5,SmartisVisualState.speaking=>math.sin(phase*2.1+ring)*(6+intensity*4)};
    final rr=radius*1.42+ring*17+motion;final paint=Paint()..style=PaintingStyle.stroke..strokeWidth=switch(state){SmartisVisualState.speaking=>2.1,SmartisVisualState.listening=>1.6,_=>1.2}..color=gold.withOpacity(((.24-ring*.028).clamp(.05,.24))*intensity);
    final rect=Rect.fromCircle(center:center,radius:rr);final dir=ring.isEven?1.0:-1.0;final speed=switch(state){SmartisVisualState.speaking=>.95,SmartisVisualState.thinking=>.7,_=>.48};
    c.save();c.translate(center.dx,center.dy);c.rotate(phase*speed*dir);c.translate(-center.dx,-center.dy);final path=Path();const parts=30;for(int i=0;i<parts;i++){final a=i/parts*math.pi*2;path.addArc(rect,a,switch(state){SmartisVisualState.thinking=>.16,SmartisVisualState.speaking=>.13,SmartisVisualState.listening=>.105,_=>.085});}c.drawPath(path,paint);c.restore();
  }
  for(int i=0;i<22;i++){final a=phase*.55+i*math.pi/11;final wave=switch(state){SmartisVisualState.listening=>math.sin(phase*1.7+i)*(3+level*10),SmartisVisualState.thinking=>math.sin(phase*1.4+i)*5,SmartisVisualState.speaking=>math.sin(phase*2.3+i)*6,_=>math.sin(phase*.7+i)*1.5};final inner=radius*1.4,outer=radius*2+wave;c.drawLine(Offset(center.dx+math.cos(a)*inner,center.dy+math.sin(a)*inner),Offset(center.dx+math.cos(a)*outer,center.dy+math.sin(a)*outer),Paint()..color=gold.withOpacity(.12*intensity)..strokeWidth=i.isEven?1.5:.8);}
  if(state==SmartisVisualState.listening){for(int i=0;i<26;i++){final a=i/26*math.pi*2+phase*.7;final rr=radius*(1.78+level*.45)+math.sin(phase*1.5+i)*4;c.drawCircle(Offset(center.dx+math.cos(a)*rr,center.dy+math.sin(a)*rr),1.2+level*2.7,Paint()..color=gold.withOpacity(.72));}}
  if(state==SmartisVisualState.speaking){for(int i=0;i<28;i++){final a=i/28*math.pi*2;final wave=6+8*(.5+.5*math.sin(phase*2+i*.7));final inner=radius*1.44;final outer=inner+wave;c.drawLine(Offset(center.dx+math.cos(a)*inner,center.dy+math.sin(a)*inner),Offset(center.dx+math.cos(a)*outer,center.dy+math.sin(a)*outer),Paint()..color=gold.withOpacity(.58)..strokeWidth=2);}}
 }
 @override bool shouldRepaint(covariant _OrbPainter old)=>old.t!=t||old.state!=state||old.level!=level;
}
