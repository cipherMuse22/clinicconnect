import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../models/models.dart';
import 'api_client.dart';

enum AuthState { loading, signedOut, signedIn }

/// Holds the login token and the current patient. Screens read it with context.watch<Session>().
class Session extends ChangeNotifier {
  Session() {
    api = ApiClient(tokenReader: () => _token, onUnauthorized: _expired);
  }

  static const _tokenKey = 'access_token';
  final _storage = const FlutterSecureStorage();
  late final ApiClient api;

  String? _token;
  AuthState state = AuthState.loading;
  Profile? profile;
  String? notice;

  Future<void> init() async {
    try {
      _token = await _storage.read(key: _tokenKey);
    } catch (_) {
      _token = null;
    }
    if (_token == null) {
      state = AuthState.signedOut;
    } else {
      state = AuthState.signedIn;
      await loadProfile();
    }
    notifyListeners();
  }

  Future<void> loadProfile() async {
    try {
      profile = Profile.fromJson(await api.get('/me'));
    } catch (_) {
      // A 401 already signed us out. Other errors (offline) just leave the profile empty for now.
    }
    notifyListeners();
  }

  Future<void> login(String email, String password) async {
    final data = await api.post('/auth/login', data: {'email': email.trim(), 'password': password});
    await _setToken(data['access_token'] as String);
  }

  Future<void> register(Map<String, dynamic> body) async {
    final data = await api.post('/auth/register', data: body);
    await _setToken(data['access_token'] as String);
  }

  Future<void> _setToken(String token) async {
    _token = token;
    notice = null;
    try {
      await _storage.write(key: _tokenKey, value: token);
    } catch (_) {}
    state = AuthState.signedIn;
    notifyListeners();
    await loadProfile();
  }

  Future<void> logout() async {
    _token = null;
    profile = null;
    try {
      await _storage.delete(key: _tokenKey);
    } catch (_) {}
    state = AuthState.signedOut;
    notifyListeners();
  }

  void _expired() {
    if (state != AuthState.signedIn) return;
    notice = 'Your session expired. Please sign in again.';
    logout();
  }
}
