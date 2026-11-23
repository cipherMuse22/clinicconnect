import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import 'book_slot_screen.dart';

class BookServiceScreen extends StatelessWidget {
  const BookServiceScreen({super.key, required this.branch});
  final Branch branch;

  @override
  Widget build(BuildContext context) {
    final api = context.read<Session>().api;
    return Scaffold(
      appBar: AppBar(title: Text(branch.name)),
      body: LoadView<List<ClinicService>>(
        load: () async => ((await api.get('/branches/${branch.id}/services')) as List).map((e) => ClinicService.fromJson(e as Map<String, dynamic>)).toList(),
        builder: (context, services, reload) {
          if (services.isEmpty) return const EmptyView(icon: Icons.medical_services, text: 'This clinic has no services listed yet.');
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: services.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, i) {
                final s = services[i];
                final why = !s.available ? 'Currently unavailable' : (!s.inStock ? 'Temporarily out of supplies' : null);
                return Card(
                  child: ListTile(
                    enabled: s.bookable,
                    leading: const Icon(Icons.medical_services_outlined),
                    title: Text(s.name),
                    subtitle: Text([if (s.description != null && s.description!.isNotEmpty) s.description!, '${s.minutes} min', if (why != null) why].join('\n')),
                    isThreeLine: true,
                    trailing: s.bookable ? const Icon(Icons.chevron_right) : null,
                    onTap: s.bookable ? () => Navigator.push(context, MaterialPageRoute(builder: (_) => BookSlotScreen(branchId: branch.id, branchName: branch.name, service: s))) : null,
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
