import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import 'book_slot_screen.dart';
import 'check_in_screen.dart';

class AppointmentDetailScreen extends StatefulWidget {
  const AppointmentDetailScreen({super.key, required this.appointment});
  final Appointment appointment;

  @override
  State<AppointmentDetailScreen> createState() => _AppointmentDetailScreenState();
}

class _AppointmentDetailScreenState extends State<AppointmentDetailScreen> {
  bool _busy = false;

  Future<void> _cancel() async {
    final ok = await confirm(context, 'Cancel this visit?', 'You can book again at any time. Visits can only be cancelled up to 2 hours before they start.', yes: 'Cancel visit', no: 'Keep it');
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    try {
      await context.read<Session>().api.post('/me/appointments/${widget.appointment.id}/cancel');
      if (!mounted) return;
      final messenger = ScaffoldMessenger.of(context);
      Navigator.pop(context);
      messenger.showSnackBar(const SnackBar(content: Text('Visit cancelled.')));
    } catch (e) {
      if (mounted) showMessage(context, errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.appointment;
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Visit details')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Expanded(child: Text(a.serviceName, style: Theme.of(context).textTheme.titleLarge)),
          StatusChip(label: a.statusLabel, status: a.status),
        ]),
        const SizedBox(height: 16),
        _row(Icons.event, '${prettyDate(a.date)}, ${a.start} - ${a.end}'),
        _row(Icons.local_hospital, a.branchName),
        _row(Icons.confirmation_number, 'Reference ${a.reference}'),
        const SizedBox(height: 24),
        if (a.isBooked) ...[
          if (a.isToday)
            FilledButton.icon(
              icon: const Icon(Icons.qr_code_scanner),
              label: const Text('Check in'),
              onPressed: _busy ? null : () => Navigator.push(context, MaterialPageRoute(builder: (_) => CheckInScreen(appointmentReference: a.reference))),
            ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.edit_calendar),
            label: const Text('Change time'),
            onPressed: _busy
                ? null
                : () => Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => BookSlotScreen(
                          branchId: a.branchId,
                          branchName: a.branchName,
                          rescheduleId: a.id,
                          service: ClinicService(id: a.serviceId, name: a.serviceName, minutes: 0, available: true, inStock: true),
                        ),
                      ),
                    ),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            icon: Icon(Icons.cancel_outlined, color: scheme.error),
            label: Text('Cancel visit', style: TextStyle(color: scheme.error)),
            onPressed: _busy ? null : _cancel,
          ),
        ],
      ]),
    );
  }

  Widget _row(IconData icon, String text) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [Icon(icon, size: 20), const SizedBox(width: 12), Expanded(child: Text(text))]),
      );
}
