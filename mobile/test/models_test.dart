import 'package:clinicconnect/models/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('trims seconds from times', () => expect(shortTime('08:30:00'), '08:30'));

  test('parses an appointment from the API', () {
    final a = Appointment.fromJson({
      'appointment_id': 1,
      'appointment_reference': 'APT-ABC12345',
      'status': 'booked',
      'branch_id': 1,
      'branch_name': 'ClinicConnect Sandton',
      'service_id': 3,
      'service_name': 'Flu vaccination',
      'slot_id': 9,
      'slot_date': '2026-11-25',
      'start_time': '09:00:00',
      'end_time': '09:15:00',
    });
    expect(a.start, '09:00');
    expect(a.isBooked, true);
    expect(a.statusLabel, 'Booked');
  });

  test('queue status labels', () {
    final q = QueueStatus.fromJson({
      'queue_number': 4,
      'queue_status': 'called',
      'branch_name': 'B',
      'service_name': 'S',
      'appointment_reference': 'R',
      'people_ahead': 0,
      'estimated_wait_minutes': 0,
    });
    expect(q.statusLabel, 'You are being called');
    expect(q.isActive, true);
  });
}
