import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _form = GlobalKey<FormState>();
  final _first = TextEditingController();
  final _last = TextEditingController();
  final _idNumber = TextEditingController();
  final _dob = TextEditingController();
  final _email = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  bool _consent = false;
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [_first, _last, _idNumber, _dob, _email, _phone, _password]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _pickDob() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: DateTime(now.year - 30, 1, 1),
      firstDate: DateTime(1900),
      lastDate: now,
      helpText: 'Date of birth',
    );
    if (picked != null) _dob.text = isoDate(picked);
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    if (!_consent) {
      showMessage(context, 'Please accept the privacy notice to continue.');
      return;
    }
    setState(() => _busy = true);
    try {
      await context.read<Session>().register({
        'first_name': _first.text.trim(),
        'last_name': _last.text.trim(),
        'id_number': _idNumber.text.trim(),
        'date_of_birth': _dob.text,
        'email': _email.text.trim(),
        'phone': _phone.text.trim(),
        'password': _password.text,
        'consent': true,
      });
      if (mounted) Navigator.of(context).popUntil((r) => r.isFirst);
    } catch (e) {
      if (mounted) showMessage(context, errorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _required(String? v) => (v == null || v.trim().isEmpty) ? 'Required' : null;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Create account')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Form(
            key: _form,
            child: Column(children: [
              TextFormField(controller: _first, textCapitalization: TextCapitalization.words, decoration: const InputDecoration(labelText: 'First name'), validator: _required),
              const SizedBox(height: 12),
              TextFormField(controller: _last, textCapitalization: TextCapitalization.words, decoration: const InputDecoration(labelText: 'Last name'), validator: _required),
              const SizedBox(height: 12),
              TextFormField(controller: _idNumber, decoration: const InputDecoration(labelText: 'ID or passport number'), validator: _required),
              const SizedBox(height: 12),
              TextFormField(
                controller: _dob,
                readOnly: true,
                onTap: _pickDob,
                decoration: const InputDecoration(labelText: 'Date of birth', suffixIcon: Icon(Icons.calendar_today)),
                validator: _required,
              ),
              const SizedBox(height: 12),
              TextFormField(controller: _email, keyboardType: TextInputType.emailAddress, decoration: const InputDecoration(labelText: 'Email'), validator: (v) => (v == null || !v.contains('@')) ? 'Enter a valid email' : null),
              const SizedBox(height: 12),
              TextFormField(controller: _phone, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Cell number', hintText: '0821234567'), validator: _required),
              const SizedBox(height: 12),
              TextFormField(controller: _password, obscureText: true, decoration: const InputDecoration(labelText: 'Password (8+ characters)'), validator: (v) => (v == null || v.length < 8) ? 'At least 8 characters' : null),
              const SizedBox(height: 8),
              CheckboxListTile(
                value: _consent,
                onChanged: (v) => setState(() => _consent = v ?? false),
                controlAffinity: ListTileControlAffinity.leading,
                contentPadding: EdgeInsets.zero,
                title: const Text('I agree that ClinicConnect may store and use my personal information to manage my appointments, as described in the privacy notice (POPIA).', style: TextStyle(fontSize: 13)),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: _busy ? null : _submit,
                  child: _busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2)) : const Text('Create account'),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
