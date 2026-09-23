import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';

/// Manages the real-time WebSocket connection to the Python backend's
/// dedicated voice session endpoint (ws://127.0.0.1:8765/voice).
///
/// Controls the backend's PyAudio microphone session (wake word & command capture)
/// without recording WAV files on the Flutter side.
class GoogleVoiceSessionClient {
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  bool _isConnected = false;
  bool _isDisposed = false;

  void Function(Map<String, dynamic>)? _onEvent;
  void Function(Object)? _onError;
  void Function()? _onDone;

  bool get isConnected => _isConnected;

  void connect({
    required void Function(Map<String, dynamic>) onEvent,
    required void Function(Object) onError,
    void Function()? onDone,
  }) {
    _onEvent = onEvent;
    _onError = onError;
    _onDone = onDone;
    _isDisposed = false;
    _open();
  }

  void _open() {
    if (_isDisposed) return;
    try {
      final uri = Uri.parse('ws://127.0.0.1:8765/voice');
      _channel = WebSocketChannel.connect(uri);

      _subscription = _channel!.stream.listen(
        (data) {
          _isConnected = true;
          try {
            final parsed = jsonDecode(data.toString());
            if (parsed is Map<String, dynamic>) {
              _onEvent?.call(parsed);
            }
          } catch (_) {}
        },
        onError: (err) {
          _isConnected = false;
          _onError?.call(err);
        },
        onDone: () {
          _isConnected = false;
          _onDone?.call();
        },
      );
    } catch (e) {
      _isConnected = false;
      _onError?.call(e);
    }
  }

  void startWake({String language = 'fa'}) {
    _send({
      'action': 'start',
      'mode': 'wake',
      'language': language,
    });
  }

  void startCommand({String language = 'fa'}) {
    _send({
      'action': 'start',
      'mode': 'command',
      'language': language,
    });
  }

  void stop() {
    _send({'action': 'stop'});
  }

  void ping() {
    _send({'action': 'ping'});
  }

  void _send(Map<String, dynamic> message) {
    try {
      _channel?.sink.add(jsonEncode(message));
    } catch (_) {}
  }

  void dispose() {
    _isDisposed = true;
    _isConnected = false;
    try {
      stop();
      _subscription?.cancel();
      _channel?.sink.close();
    } catch (_) {}
  }
}
