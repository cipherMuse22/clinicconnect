import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'config.dart';

class ApiException implements Exception {
  ApiException(this.message, [this.statusCode]);
  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({required this.tokenReader, required this.onUnauthorized})
      : _dio = Dio(BaseOptions(
          baseUrl: AppConfig.apiBaseUrl,
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 20),
          headers: {'accept': 'application/json'},
        )) {
    _dio.interceptors.add(InterceptorsWrapper(onRequest: (options, handler) {
      final token = tokenReader();
      if (token != null) options.headers['authorization'] = 'Bearer $token';
      handler.next(options);
    }));
  }

  final Dio _dio;
  final String? Function() tokenReader;
  final void Function() onUnauthorized;

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _send(() => _dio.get(path, queryParameters: query));

  Future<dynamic> post(String path, {Object? data}) => _send(() => _dio.post(path, data: data));

  /// Used for images such as the membership QR code.
  Future<Uint8List> getBytes(String path) async {
    final res = await _send(() => _dio.get<List<int>>(path, options: Options(responseType: ResponseType.bytes)));
    return Uint8List.fromList(List<int>.from(res as List));
  }

  Future<dynamic> _send(Future<Response<dynamic>> Function() call) async {
    try {
      final res = await call();
      return res.data;
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status == 401 && tokenReader() != null) onUnauthorized();
      if (status == null) {
        throw ApiException('Cannot reach the server. Check your internet connection and that the API is running.');
      }
      throw ApiException(_detail(e.response?.data) ?? 'Something went wrong ($status)', status);
    }
  }

  /// FastAPI errors look like {"detail": "text"} or {"detail": [{"msg": "..."}]}.
  String? _detail(dynamic body) {
    if (body is Map && body['detail'] != null) {
      final d = body['detail'];
      if (d is String) return d;
      if (d is List && d.isNotEmpty) {
        return d.map((x) {
          if (x is Map && x['msg'] != null) {
            final msg = x['msg'].toString().replaceFirst('Value error, ', '');
            final loc = x['loc'];
            final field = (loc is List && loc.length > 1) ? '${loc.last}: ' : '';
            return '$field$msg';
          }
          return x.toString();
        }).join('\n');
      }
    }
    return null;
  }
}
