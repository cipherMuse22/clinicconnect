import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import 'appointment_detail_screen.dart';
import 'book_branch_screen.dart';

class AppointmentsScreen extends StatelessWidget {
  const AppointmentsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('My visits'),
          bottom: const TabBar(tabs: [Tab(text: 'Upcoming'), Tab(text: 'Past')]),
        ),
        floatingActionButton: FloatingActionButton.extended(
          icon: const Icon(Icons.add),
          label: const Text('Book'),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const BookBranchScreen())),
        ),
        body: const TabBarView(children: [_List(scope: 'upcoming'), _List(scope: 'past')]),
      ),
    );
  }
}

class _List extends StatelessWidget {
  const _List({required this.scope});
  final String scope;

  @override
  Widget build(BuildContext context) {
    final api = context.read<Session>().api;
    return LoadView<List<Appointment>>(
      load: () async => ((await api.get('/me/appointments', query: {'scope': scope})) as List).map((e) => Appointment.fromJson(e as Map<String, dynamic>)).toList(),
      builder: (context, items, reload) {
        if (items.isEmpty) return EmptyView(icon: Icons.event_busy, text: scope == 'upcoming' ? 'No upcoming visits.' : 'No past visits yet.');
        return RefreshIndicator(
          onRefresh: reload,
          child: ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 88),
            itemCount: items.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, i) {
              final a = items[i];
              return Card(
                child: ListTile(
                  title: Text(a.serviceName),
                  subtitle: Text('${prettyDate(a.date)}, ${a.start}\n${a.branchName}'),
                  isThreeLine: true,
                  trailing: StatusChip(label: a.statusLabel, status: a.status),
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => AppointmentDetailScreen(appointment: a))).then((_) => reload()),
                ),
              );
            },
          ),
        );
      },
    );
  }
}
