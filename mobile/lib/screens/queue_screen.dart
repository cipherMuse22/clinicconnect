import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

/// Live queue position. Refreshes itself every 15 seconds.
class QueueScreen extends StatefulWidget {
  const QueueScreen({super.key});

  @override
  State<QueueScreen> createState() => _QueueScreenState();
}

class _QueueScreenState extends State<QueueScreen> {
  QueueStatus? _q;
  String? _error;
  bool _notCheckedIn = false;
  bool _loading = true;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final d = await context.read<Session>().api.get('/me/queue');
      if (!mounted) return;
      setState(() {
        _q = QueueStatus.fromJson(d as Map<String, dynamic>);
        _error = null;
        _notCheckedIn = false;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (e.statusCode == 404) {
          _notCheckedIn = true;
          _q = null;
        } else {
          _error = e.message;
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_notCheckedIn) {
      body = const EmptyView(icon: Icons.hourglass_empty, text: "You are not in a queue today. Check in when you arrive at the clinic.");
    } else if (_q == null) {
      body = ErrorView(message: _error ?? 'Could not load your queue position.', onRetry: _refresh);
    } else {
      body = _content(context, _q!);
    }
    return Scaffold(appBar: AppBar(title: const Text('Your queue')), body: body);
  }

  Widget _content(BuildContext context, QueueStatus q) {
    final called = q.status == 'called';
    final scheme = Theme.of(context).colorScheme;
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(padding: const EdgeInsets.all(24), children: [
        Text(q.branchName, textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleMedium),
        Text(q.serviceName, textAlign: TextAlign.center),
        const SizedBox(height: 24),
        Container(
          padding: const EdgeInsets.symmetric(vertical: 28),
          decoration: BoxDecoration(color: called ? Colors.orange.shade100 : scheme.primaryContainer, borderRadius: BorderRadius.circular(20)),
          child: Column(children: [
            const Text('Your number'),
            Text('${q.number}', style: Theme.of(context).textTheme.displayLarge?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            StatusChip(label: q.statusLabel, status: q.status),
          ]),
        ),
        const SizedBox(height: 24),
        if (called)
          const Card(child: ListTile(leading: Icon(Icons.campaign), title: Text('It is your turn'), subtitle: Text('Please go to the nurse now.')))
        else if (q.status == 'waiting') ...[
          Card(child: ListTile(leading: const Icon(Icons.groups), title: Text('${q.peopleAhead} ${q.peopleAhead == 1 ? 'person' : 'people'} ahead of you'))),
          Card(
            child: ListTile(
              leading: const Icon(Icons.timer_outlined),
              title: Text('About ${q.waitMinutes} minutes'),
              subtitle: q.note.isEmpty ? null : Text(q.note),
            ),
          ),
        ],
        const SizedBox(height: 8),
        Text('Reference ${q.reference}', textAlign: TextAlign.center, style: TextStyle(color: scheme.outline)),
        const SizedBox(height: 4),
        Text('Updates automatically every 15 seconds.', textAlign: TextAlign.center, style: TextStyle(color: scheme.outline, fontSize: 12)),
      ]),
    );
  }
}
