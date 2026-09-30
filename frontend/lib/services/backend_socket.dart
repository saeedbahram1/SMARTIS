import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

class BackendSocket {
  static const String baseUrl = 'http://127.0.0.1:8765';
  static const String wsUrl = 'ws://127.0.0.1:8765/ws';

  WebSocketChannel? _channel;
  Timer? _reconnectTimer;
  bool _disposed = false;
  bool _connecting = false;

  void Function(Map<String, dynamic>)? _onMessage;
  void Function(Object)? _onError;

  void connect({
    required void Function(Map<String, dynamic>) onMessage,
    required void Function(Object) onError,
  }) {
    _onMessage = onMessage;
    _onError = onError;
    _disposed = false;
    unawaited(_open());
  }

  Future<void> _open() async {
    if (_disposed || _connecting) return;
    _connecting = true;
    _reconnectTimer?.cancel();

    try {
      final channel = WebSocketChannel.connect(Uri.parse(wsUrl));
      await channel.ready;
      if (_disposed) {
        await channel.sink.close();
        return;
      }

      _channel?.sink.close();
      _channel = channel;

      channel.stream.listen(
        (data) {
          try {
            final decoded = jsonDecode(data.toString());
            if (decoded is Map<String, dynamic>) {
              _onMessage?.call(decoded);
            }
          } catch (_) {
            // Ignore malformed backend frames instead of killing the UI loop.
          }
        },
        onError: (Object error) {
          _onError?.call(error);
          _scheduleReconnect();
        },
        onDone: _scheduleReconnect,
        cancelOnError: true,
      );
    } catch (error) {
      _onError?.call(error);
      _scheduleReconnect();
    } finally {
      _connecting = false;
    }
  }

  void _scheduleReconnect() {
    if (_disposed || _reconnectTimer?.isActive == true) return;
    _channel = null;
    _reconnectTimer = Timer(const Duration(seconds: 2), () {
      unawaited(_open());
    });
  }

  void sendAction(String action, [Map<String, dynamic>? data]) {
    final payload = <String, dynamic>{
      'action': action,
      ...?data,
    };
    try {
      _channel?.sink.add(jsonEncode(payload));
    } catch (_) {
      // Reconnect loop will restore the channel.
    }
  }

  void pauseListening() => sendAction('mic_pause');

  void resumeListening() => sendAction('mic_resume');

  void restartMicrophone() => sendAction('mic_restart');

  Future<Map<String, dynamic>> _json(http.Response response) async {
    final body = response.body;
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Backend ${response.statusCode}: $body');
    }
    final decoded = jsonDecode(body);
    if (decoded is Map<String, dynamic>) return decoded;
    throw Exception('Invalid backend response');
  }

  Future<Map<String, dynamic>> speak(
    String text,
    String? language,
  ) async {
    return _json(
      await http.post(
        Uri.parse('$baseUrl/speak'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'text': text, 'language': language}),
      ),
    );
  }

  Future<Map<String, dynamic>> command(
    String text,
    String? language,
  ) async {
    return _json(
      await http.post(
        Uri.parse('$baseUrl/command'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'text': text, 'language': language}),
      ),
    );
  }

  Future<Map<String, dynamic>> plan(
    String text,
    String? language,
  ) async {
    return _json(
      await http.post(
        Uri.parse('$baseUrl/agent/plan'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'text': text, 'language': language}),
      ),
    );
  }

  Future<Map<String, dynamic>> execute(
    Map<String, dynamic> plan, {
    bool confirmed = false,
  }) async {
    return _json(
      await http.post(
        Uri.parse('$baseUrl/agent/execute'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'plan': plan, 'confirmed': confirmed}),
      ),
    );
  }


  Future<Map<String, dynamic>> dashboard() async {
    return _json(await http.get(Uri.parse('$baseUrl/dashboard')));
  }

  Future<Map<String, dynamic>> setVoice(String language, String gender) async {
    return _json(await http.post(Uri.parse('$baseUrl/voice/settings'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'language': language, 'gender': gender})));
  }
  void dispose() {
    _disposed = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    try {
      _channel?.sink.close();
    } catch (_) {}
    _channel = null;
  }
}
