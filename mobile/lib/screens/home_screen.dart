import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import 'appointment_detail_screen.dart';
import 'book_branch_screen.dart';
import 'check_in_screen.dart';
import 'queue_screen.dart';

class _HomeData {
  _HomeData(this.next, this.queue);
  final Appointment? next;
  final QueueStatus? queue;
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.onOpenTab});
  final void Function(int) onOpenTab;

  Future<_HomeData> _load(Session s) async {
    final list = await s.api.get('/me/appointments', query: {'scope': 'upcoming'}) as List;
    final appts = list.map((e) => Appointment.fromJson(e as Map<String, dynamic>)).where((a) => a.isBooked || a.status == 'checked_in').toList();
    appts.sort((a, b) => '${a.date} ${a.start}'.compareTo('${b.date} ${b.start}'));
    QueueStatus? q;
    try {
      q = QueueStatus.fromJson(await s.api.get('/me/queue') as Map<String, dynamic>);
      if (!q.isActive) q = null;
    } on ApiException catch (e) {
      // 404 means "not checked in", which is normal.
      if (e.statusCode != 404) rethrow;
    }
    return _HomeData(appts.isEmpty ? null : appts.first, q);
  }

  @override
  Widget build(BuildContext context) {
    final session = context.watch<Session>();
    final name = session.profile?.firstName ?? '';
    return LoadView<_HomeData>(
      load: () => _load(session),
      builder: (context, data, reload) => RefreshIndicator(
        onRefresh: reload,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          Text(name.isEmpty ? 'Welcome' : 'Hello, $name', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 16),
          if (data.queue != null) _QueueCard(q: data.queue!, onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const QueueScreen())).then((_) => reload())),
          if (data.next != null)
            Card(
              child: ListTile(
                leading: const Icon(Icons.event_available),
                title: Text(data.next!.serviceName),
                subtitle: Text('${prettyDate(data.next!.date)}, ${data.next!.start}\n${data.next!.branchName}'),
                isThreeLine: true,
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => AppointmentDetailScreen(appointment: data.next!))).then((_) => reload()),
              ),
            )
          else
            const Card(child: ListTile(leading: Icon(Icons.event_busy), title: Text('No upcoming visits'), subtitle: Text('Book one in a few taps.'))),
          const SizedBox(height: 8),
          FilledButton.icon(
            icon: const Icon(Icons.add),
            label: const Text('Book an appointment'),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const BookBranchScreen())).then((_) => reload()),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text("I'm at the clinic - check in"),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CheckInScreen())).then((_) => reload()),
          ),
          const SizedBox(height: 8),
          TextButton(onPressed: () => onOpenTab(1), child: const Text('See all my visits')),
        ]),
      ),
    );
  }
}

class _QueueCard extends StatelessWidget {
  const _QueueCard({required this.q, required this.onTap});
  final QueueStatus q;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final called = q.status == 'called';
    return Card(
      color: called ? Colors.orange.shade100 : Theme.of(context).colorScheme.primaryContainer,
      child: ListTile(
        leading: CircleAvatar(child: Text('${q.number}')),
        title: Text(q.statusLabel),
        subtitle: Text(called ? 'Please go to the nurse now' : '${q.peopleAhead} ahead of you, about ${q.waitMinutes} min'),
        trailing: const Icon(Icons.chevron_right),
        onTap: onTap,
      ),
    );
  }
}
