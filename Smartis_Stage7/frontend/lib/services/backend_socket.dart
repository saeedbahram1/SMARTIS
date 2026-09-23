import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
class BackendSocket {
  WebSocketChannel? _channel;
  static const baseUrl='http://127.0.0.1:8765';
  void connect({required void Function(Map<String,dynamic>) onMessage,required void Function(Object) onError}){
    try{
      _channel=WebSocketChannel.connect(Uri.parse('ws://127.0.0.1:8765/ws'));
      _channel!.stream.listen((data){try{final x=jsonDecode(data.toString());if(x is Map<String,dynamic>) onMessage(x);}catch(_){ }},onError:onError,onDone:()=>onError(Exception('Backend disconnected')));
    }catch(e){onError(e);}
  }
  Future<Map<String,dynamic>> _json(http.Response r) async { final x=jsonDecode(r.body); if(x is Map<String,dynamic>) return x; throw Exception('Invalid backend response'); }
  Future<Map<String,dynamic>> transcribe(String path,{String? languageHint}) async {
    final req=http.MultipartRequest('POST',Uri.parse('$baseUrl/transcribe')); req.files.add(await http.MultipartFile.fromPath('audio',path)); if(languageHint?.isNotEmpty==true) req.fields['language_hint']=languageHint!; final res=await req.send(); final body=await res.stream.bytesToString(); if(res.statusCode<200||res.statusCode>=300) throw Exception('Transcription failed: ${res.statusCode} $body'); final x=jsonDecode(body); if(x is Map<String,dynamic>) return x; throw Exception('Invalid transcription response');
  }
  Future<Map<String,dynamic>> wakeAudio(String path) async {
    final req=http.MultipartRequest('POST',Uri.parse('$baseUrl/wake_audio')); req.files.add(await http.MultipartFile.fromPath('audio',path)); final res=await req.send(); final body=await res.stream.bytesToString(); if(res.statusCode<200||res.statusCode>=300) throw Exception('Wake recognition failed: ${res.statusCode} $body'); final x=jsonDecode(body); if(x is Map<String,dynamic>) return x; throw Exception('Invalid wake response');
  }
  Future<Map<String,dynamic>> speak(String text,String? language) async=>_json(await http.post(Uri.parse('$baseUrl/speak'),headers:{'Content-Type':'application/json'},body:jsonEncode({'text':text,'language':language})));
  Future<Map<String,dynamic>> plan(String text,String? language) async=>_json(await http.post(Uri.parse('$baseUrl/agent/plan'),headers:{'Content-Type':'application/json'},body:jsonEncode({'text':text,'language':language})));
  Future<Map<String,dynamic>> execute(Map<String,dynamic> plan,{bool confirmed=false}) async=>_json(await http.post(Uri.parse('$baseUrl/agent/execute'),headers:{'Content-Type':'application/json'},body:jsonEncode({'plan':plan,'confirmed':confirmed})));
  void ping()=>_channel?.sink.add(jsonEncode({'action':'ping'}));
  void dispose()=>_channel?.sink.close();
}
