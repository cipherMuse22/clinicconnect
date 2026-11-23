import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';

class AppConfig {
  /// Override with: flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000/api/v1
  static const String _override = String.fromEnvironment('API_BASE_URL');

  static String get apiBaseUrl {
    if (_override.isNotEmpty) return _override;
    // The Android emulator reaches your PC at 10.0.2.2. Everything else (Windows, web, iOS simulator) uses localhost.
    if (!kIsWeb && Platform.isAndroid) return 'http://10.0.2.2:8000/api/v1';
    return 'http://localhost:8000/api/v1';
  }
}
