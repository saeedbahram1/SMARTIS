import 'package:flutter/material.dart';

import 'app.dart';
import 'services/windows_window.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SmartisWindowsWindow.initialize();
  runApp(const SmartisApp());
}
