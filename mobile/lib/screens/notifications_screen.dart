import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key, required this.onChanged});
  final VoidCallback onChanged;

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  int _version = 0;

  IconData _icon(String type) {
    if (type.contains('cancel')) return Icons.event_busy;
    if (type.contains('resched')) return Icons.edit_calendar;
    if (type.contains('reminder')) return Icons.alarm;
    if (type.contains('queue')) return Icons.campaign;
    if (type.contains('check')) return Icons.how_to_reg;
    return Icons.event_available;
  }

  @override
  Widget build(BuildContext context) {
    final api = context.read<Session>().api;
    return Scaffold(
      appBar: AppBar(title: const Text('Alerts'), actions: [
        TextButton(
          onPressed: () async {
            try {
              await api.post('/me/notifications/read-all');
              widget.onChanged();
              if (mounted) setState(() => _version++);
            } catch (e) {
              if (mounted) showMessage(context, errorText(e));
            }
          },
          child: const Text('Mark all read'),
        ),
      ]),
      body: LoadView<List<AppNotification>>(
        key: ValueKey(_version),
        load: () async => ((await api.get('/me/notifications', query: {'limit': 50})) as List).map((e) => AppNotification.fromJson(e as Map<String, dynamic>)).toList(),
        builder: (context, items, reload) {
          if (items.isEmpty) return const EmptyView(icon: Icons.notifications_none, text: 'No alerts yet. Booking confirmations and reminders show up here.');
          return RefreshIndicator(
            onRefresh: reload,
            child: ListView.separated(
              itemCount: items.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (context, i) {
                final n = items[i];
                return ListTile(
                  leading: Icon(_icon(n.type), color: n.read ? null : Theme.of(context).colorScheme.primary),
                  title: Text(n.message, style: TextStyle(fontWeight: n.read ? FontWeight.normal : FontWeight.w600)),
                  subtitle: Text(n.when),
                  onTap: n.read
                      ? null
                      : () async {
                          try {
                            await api.post('/me/notifications/${n.id}/read');
                            setState(() => n.read = true);
                            widget.onChanged();
                          } catch (_) {}
                        },
                );
              },
            ),
          );
        },
      ),
    );
  }
}
