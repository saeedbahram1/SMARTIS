import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';
import 'app.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();
  const options = WindowOptions(
    size: Size(520, 610),
    minimumSize: Size(460, 560),
    center: true,
    backgroundColor: Colors.transparent,
    skipTaskbar: false,
    titleBarStyle: TitleBarStyle.hidden,
    title: 'Smartis',
  );
  await windowManager.waitUntilReadyToShow(options, () async {
    await windowManager.setAsFrameless();
    await windowManager.setHasShadow(false);
    await windowManager.setBackgroundColor(Colors.transparent);
    await windowManager.show();
    await windowManager.focus();
  });
  runApp(const SmartisApp());
}
