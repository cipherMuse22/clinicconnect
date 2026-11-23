import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../widgets/common.dart';
import 'queue_screen.dart';

const _prefix = 'clinicconnect://checkin/';

/// Scan the QR code at the clinic desk. The code holds a short-lived token that proves you are at that branch.
class CheckInScreen extends StatefulWidget {
  const CheckInScreen({super.key, this.appointmentReference});
  final String? appointmentReference;

  @override
  State<CheckInScreen> createState() => _CheckInScreenState();
}

class _CheckInScreenState extends State<CheckInScreen> {
  final _manual = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _manual.dispose();
    super.dispose();
  }

  String _tokenFrom(String raw) {
    final t = raw.trim();
    return t.startsWith(_prefix) ? t.substring(_prefix.length) : t;
  }

  Future<void> _checkIn(String raw) async {
    if (_busy) return;
    final token = _tokenFrom(raw);
    if (token.isEmpty) return;
    setState(() => _busy = true);
    try {
      await context.read<Session>().api.post('/me/check-in', data: {
        'branch_token': token,
        if (widget.appointmentReference != null) 'appointment_reference': widget.appointmentReference,
      });
      if (!mounted) return;
      Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const QueueScreen()));
    } catch (e) {
      if (!mounted) return;
      showMessage(context, errorText(e));
      // Wait a moment so the same QR code is not submitted again straight away.
      await Future<void>.delayed(const Duration(seconds: 2));
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Check in')),
      body: Column(children: [
        Expanded(
          child: Stack(children: [
            MobileScanner(
              onDetect: (capture) {
                for (final b in capture.barcodes) {
                  final v = b.rawValue;
                  if (v != null && v.startsWith(_prefix)) {
                    _checkIn(v);
                    break;
                  }
                }
              },
            ),
            if (_busy) const Center(child: CircularProgressIndicator()),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('Point your camera at the QR code at the reception desk.', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: TextField(controller: _manual, decoration: const InputDecoration(labelText: 'Or paste the clinic code', isDense: true))),
              const SizedBox(width: 8),
              FilledButton(onPressed: _busy ? null : () => _checkIn(_manual.text), child: const Text('Go')),
            ]),
          ]),
        ),
      ]),
    );
  }
}
