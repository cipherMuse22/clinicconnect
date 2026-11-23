import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import 'book_service_screen.dart';

const _days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

String hoursSummary(List<OpeningHours> hours) {
  if (hours.isEmpty) return 'Opening hours not set';
  final sorted = [...hours]..sort((a, b) => a.day.compareTo(b.day));
  return sorted.map((h) => '${_days[h.day % 7]} ${shortTime(h.open)}-${shortTime(h.close)}').join('  ');
}

class BookBranchScreen extends StatelessWidget {
  const BookBranchScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final api = context.read<Session>().api;
    return Scaffold(
      appBar: AppBar(title: const Text('Choose a clinic')),
      body: LoadView<List<Branch>>(
        load: () async => ((await api.get('/branches')) as List).map((e) => Branch.fromJson(e as Map<String, dynamic>)).where((b) => b.active).toList(),
        builder: (context, branches, reload) {
          if (branches.isEmpty) return const EmptyView(icon: Icons.local_hospital, text: 'No clinics are open for booking right now.');
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: branches.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, i) {
                final b = branches[i];
                return Card(
                  child: ListTile(
                    leading: const Icon(Icons.local_hospital),
                    title: Text(b.name),
                    subtitle: Text([if (b.address != null) b.address!, hoursSummary(b.hours)].join('\n')),
                    isThreeLine: true,
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => BookServiceScreen(branch: b))),
                  ),
                );
              },
            ),
          );
        },
      ),
    );
  }
}
