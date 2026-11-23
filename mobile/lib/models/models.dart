import 'package:intl/intl.dart';

String _s(dynamic v) => v?.toString() ?? '';

/// "08:30:00" -> "08:30"
String shortTime(String t) => t.length >= 5 ? t.substring(0, 5) : t;

/// "2026-11-25" -> "Wed 25 Nov 2026"
String prettyDate(String iso) {
  final d = DateTime.tryParse(iso);
  return d == null ? iso : DateFormat('EEE d MMM yyyy').format(d);
}

String isoDate(DateTime d) => DateFormat('yyyy-MM-dd').format(d);

class Profile {
  Profile({required this.id, required this.firstName, required this.lastName, required this.email, required this.phone});
  final int id;
  final String firstName, lastName, email, phone;

  factory Profile.fromJson(Map<String, dynamic> j) => Profile(
        id: j['patient_id'] as int,
        firstName: _s(j['first_name']),
        lastName: _s(j['last_name']),
        email: _s(j['email']),
        phone: _s(j['phone']),
      );

  String get fullName => '$firstName $lastName';
}

class Membership {
  Membership({required this.number, required this.status, required this.issued});
  final String number, status, issued;

  factory Membership.fromJson(Map<String, dynamic> j) =>
      Membership(number: _s(j['membership_number']), status: _s(j['status']), issued: _s(j['issued_date']));
}

class Branch {
  Branch({required this.id, required this.name, this.address, this.phone, required this.active, required this.hours});
  final int id;
  final String name;
  final String? address, phone;
  final bool active;
  final List<OpeningHours> hours;

  factory Branch.fromJson(Map<String, dynamic> j) => Branch(
        id: j['branch_id'] as int,
        name: _s(j['branch_name']),
        address: j['address'] as String?,
        phone: j['phone'] as String?,
        active: j['status'] == 'active',
        hours: ((j['hours'] ?? []) as List).map((h) => OpeningHours.fromJson(h as Map<String, dynamic>)).toList(),
      );
}

class OpeningHours {
  OpeningHours({required this.day, required this.open, required this.close});
  final int day; // 0 = Monday ... 6 = Sunday
  final String open, close;

  factory OpeningHours.fromJson(Map<String, dynamic> j) =>
      OpeningHours(day: j['day_of_week'] as int, open: _s(j['open_time']), close: _s(j['close_time']));
}

class ClinicService {
  ClinicService({required this.id, required this.name, this.description, required this.minutes, required this.available, required this.inStock});
  final int id;
  final String name;
  final String? description;
  final int minutes;
  final bool available, inStock;

  factory ClinicService.fromJson(Map<String, dynamic> j) => ClinicService(
        id: j['service_id'] as int,
        name: _s(j['service_name']),
        description: j['description'] as String?,
        minutes: (j['estimated_duration_min'] ?? 0) as int,
        available: j['available'] == true,
        inStock: j['in_stock'] != false,
      );

  bool get bookable => available && inStock;
}

class Slot {
  Slot({required this.id, required this.date, required this.start, required this.end, required this.spotsLeft, required this.available});
  final int id;
  final String date, start, end;
  final int spotsLeft;
  final bool available;

  factory Slot.fromJson(Map<String, dynamic> j) => Slot(
        id: j['slot_id'] as int,
        date: _s(j['slot_date']),
        start: shortTime(_s(j['start_time'])),
        end: shortTime(_s(j['end_time'])),
        spotsLeft: (j['spots_left'] ?? 0) as int,
        available: j['available'] == true,
      );
}

class Appointment {
  Appointment({
    required this.id,
    required this.reference,
    required this.status,
    required this.branchId,
    required this.branchName,
    required this.serviceId,
    required this.serviceName,
    required this.date,
    required this.start,
    required this.end,
  });
  final int id, branchId, serviceId;
  final String reference, status, branchName, serviceName, date, start, end;

  factory Appointment.fromJson(Map<String, dynamic> j) => Appointment(
        id: j['appointment_id'] as int,
        reference: _s(j['appointment_reference']),
        status: _s(j['status']),
        branchId: j['branch_id'] as int,
        branchName: _s(j['branch_name']),
        serviceId: j['service_id'] as int,
        serviceName: _s(j['service_name']),
        date: _s(j['slot_date']),
        start: shortTime(_s(j['start_time'])),
        end: shortTime(_s(j['end_time'])),
      );

  bool get isBooked => status == 'booked';
  bool get isToday => date == isoDate(DateTime.now());

  String get statusLabel => switch (status) {
        'booked' => 'Booked',
        'checked_in' => 'Checked in',
        'in_progress' => 'In progress',
        'completed' => 'Completed',
        'cancelled' => 'Cancelled',
        'no_show' => 'Missed',
        _ => status,
      };
}

class QueueStatus {
  QueueStatus({
    required this.number,
    required this.status,
    required this.branchName,
    required this.serviceName,
    required this.reference,
    required this.peopleAhead,
    required this.waitMinutes,
    required this.note,
  });
  final int number, peopleAhead, waitMinutes;
  final String status, branchName, serviceName, reference, note;

  factory QueueStatus.fromJson(Map<String, dynamic> j) => QueueStatus(
        number: j['queue_number'] as int,
        status: _s(j['queue_status']),
        branchName: _s(j['branch_name']),
        serviceName: _s(j['service_name']),
        reference: _s(j['appointment_reference']),
        peopleAhead: (j['people_ahead'] ?? 0) as int,
        waitMinutes: (j['estimated_wait_minutes'] ?? 0) as int,
        note: _s(j['estimate_note']),
      );

  String get statusLabel => switch (status) {
        'waiting' => 'Waiting',
        'called' => 'You are being called',
        'in_service' => 'With the nurse',
        'completed' => 'Visit complete',
        'skipped' => 'Skipped',
        'cancelled' => 'Cancelled',
        _ => status,
      };

  bool get isActive => status == 'waiting' || status == 'called' || status == 'in_service';
}

class AppNotification {
  AppNotification({required this.id, required this.type, required this.message, required this.sentAt, required this.read});
  final int id;
  final String type, message, sentAt;
  bool read;

  factory AppNotification.fromJson(Map<String, dynamic> j) => AppNotification(
        id: j['notification_id'] as int,
        type: _s(j['notification_type']),
        message: _s(j['message']),
        sentAt: _s(j['sent_at']),
        read: j['read'] == true,
      );

  String get when {
    final d = DateTime.tryParse(sentAt);
    return d == null ? '' : DateFormat('d MMM, HH:mm').format(d.toLocal());
  }
}
