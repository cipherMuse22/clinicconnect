import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/session.dart';
import 'screens/login_screen.dart';
import 'screens/shell.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(ChangeNotifierProvider(create: (_) => Session()..init(), child: const ClinicConnectApp()));
}

class ClinicConnectApp extends StatelessWidget {
  const ClinicConnectApp({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<Session>();
    return MaterialApp(
      title: 'ClinicConnect',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF0E7C86)),
        inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
      ),
      home: switch (auth.state) {
        AuthState.loading => const Scaffold(body: Center(child: CircularProgressIndicator())),
        AuthState.signedOut => const LoginScreen(),
        AuthState.signedIn => const Shell(),
      },
    );
  }
}
