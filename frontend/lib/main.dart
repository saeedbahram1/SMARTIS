import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';
import 'app.dart';
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();
  const options=WindowOptions(
    size:Size(620,780),
    minimumSize:Size(480,620),
    center:true,
    backgroundColor:Colors.transparent,
    skipTaskbar:false,
    // TitleBarStyle.hidden alone still leaves Windows drawing its normal
    // frame/border around the window (that's the stray colored outline
    // around the app). setAsFrameless() below removes that native chrome
    // entirely so only the transparent Flutter surface is visible.
    titleBarStyle:TitleBarStyle.hidden,
    title:'Smartis',
  );
  await windowManager.waitUntilReadyToShow(options,()async{
    await windowManager.setAsFrameless();
    await windowManager.setHasShadow(false);
    await windowManager.setBackgroundColor(Colors.transparent);
    await windowManager.show();
    await windowManager.focus();
  });
  runApp(const SmartisApp());
}
