import 'package:flutter/services.dart';

class SmartisWindowsWindow {
  static const MethodChannel _channel =
      MethodChannel('smartis/windows_window');

  static Future<void> initialize() async {
    try {
      await _channel.invokeMethod<void>('initialize');
    } on MissingPluginException {
      // Non-Windows platforms do not have the native runner channel.
    } on PlatformException {
      // Keep the UI usable even if the native window operation is unavailable.
    }
  }

  static Future<void> startDragging() async {
    try {
      await _channel.invokeMethod<void>('startDragging');
    } on MissingPluginException {
      // No-op outside the Windows runner.
    } on PlatformException {
      // Safe no-op if the native runner is unavailable.
    }
  }


  static Future<void> openLocationSettings() async {
    try {
      await _channel.invokeMethod<void>('openLocationSettings');
    } on MissingPluginException {
      // No-op outside Windows.
    } on PlatformException {
      // Safe no-op.
    }
  }

  static Future<void> close() async {
    try {
      await _channel.invokeMethod<void>('close');
    } on MissingPluginException {
      // No-op outside the Windows runner.
    } on PlatformException {
      // Safe no-op if the native runner is unavailable.
    }
  }
}
