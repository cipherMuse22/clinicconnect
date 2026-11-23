import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

/// Pick a day and a time. Used for new bookings and, when [rescheduleId] is set, to move an existing one.
class BookSlotScreen extends StatefulWidget {
  const BookSlotScreen({super.key, required this.branchId, required this.branchName, required this.service, this.rescheduleId});
  final int branchId;
  final String branchName;
  final ClinicService service;
  final int? rescheduleId;

  @override
  State<BookSlotScreen> createState() => _BookSlotScreenState();
}

class _BookSlotScreenState extends State<BookSlotScreen> {
  static const _daysAhead = 14;
  late final List<DateTime> _dates;
  late DateTime _selected;
  Future<List<Slot>>? _slots;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final today = DateTime.now();
    _dates = List.generate(_daysAhead, (i) => DateTime(today.year, today.month, today.day + i));
    _selected = _dates.first;
    _fetch();
  }

  void _fetch() {
    final api = context.read<Session>().api;
    _slots = api
        .get('/branches/${widget.branchId}/services/${widget.service.id}/slots', query: {'date': isoDate(_selected)})
        .then((d) => (d as List).map((e) => Slot.fromJson(e as Map<String, dynamic>)).toList());
  }

  Future<void> _choose(Slot slot) async {
    final moving = widget.rescheduleId != null;
    final ok = await confirm(
      context,
      moving ? 'Move your visit?' : 'Book this visit?',
      '${widget.service.name}\n${widget.branchName}\n${prettyDate(slot.date)}, ${slot.start}',
      yes: moving ? 'Move it' : 'Book it',
      no: 'Back',
    );
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    final api = context.read<Session>().api;
    try {
      if (moving) {
        await api.post('/me/appointments/${widget.rescheduleId}/reschedule', data: {'new_slot_id': slot.id});
      } else {
        await api.post('/me/appointments', data: {'slot_id': slot.id});
      }
      if (!mounted) return;
      final messenger = ScaffoldMessenger.of(context);
      Navigator.of(context).popUntil((r) => r.isFirst);
      messenger.showSnackBar(SnackBar(content: Text(moving ? 'Visit moved to ${prettyDate(slot.date)}, ${slot.start}.' : 'Booked for ${prettyDate(slot.date)}, ${slot.start}.')));
    } catch (e) {
      if (!mounted) return;
      showMessage(context, errorText(e));
      setState(_fetch); // the slot may have just filled up, so refresh the list
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.rescheduleId != null ? 'Choose a new time' : widget.service.name)),
      body: Column(children: [
        SizedBox(
          height: 78,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.all(12),
            itemCount: _dates.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (context, i) {
              final d = _dates[i];
              return ChoiceChip(
                selected: d == _selected,
                label: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Text(DateFormat('EEE').format(d), style: const TextStyle(fontSize: 11)),
                  Text(DateFormat('d MMM').format(d), style: const TextStyle(fontWeight: FontWeight.bold)),
                ]),
                onSelected: _busy
                    ? null
                    : (_) => setState(() {
                          _selected = d;
                          _fetch();
                        }),
              );
            },
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: FutureBuilder<List<Slot>>(
            future: _slots,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
              if (snap.hasError) return ErrorView(message: errorText(snap.error!), onRetry: () => setState(_fetch));
              final slots = snap.data ?? [];
              if (slots.isEmpty) return const EmptyView(icon: Icons.event_busy, text: 'No times on this day. Try another date.');
              return SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Wrap(spacing: 10, runSpacing: 10, children: [
                  for (final s in slots)
                    ActionChip(
                      label: Text(s.available ? s.start : '${s.start} full'),
                      onPressed: (s.available && !_busy) ? () => _choose(s) : null,
                    ),
                ]),
              );
            },
          ),
        ),
      ]),
    );
  }
}
