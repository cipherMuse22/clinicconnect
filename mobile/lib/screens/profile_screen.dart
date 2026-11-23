import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class _Me {
  _Me(this.membership, this.qr);
  final Membership membership;
  final Uint8List qr;
}

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = context.watch<Session>();
    final p = session.profile;
    return Scaffold(
      appBar: AppBar(title: const Text('My profile')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        if (p != null) ...[
          Text(p.fullName, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 4),
          Text(p.email),
          Text(p.phone),
        ],
        const SizedBox(height: 16),
        Text('Membership card', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        SizedBox(
          height: 330,
          child: LoadView<_Me>(
            load: () async {
              final m = Membership.fromJson(await session.api.get('/me/membership') as Map<String, dynamic>);
              final qr = await session.api.getBytes('/me/membership/qr.png');
              return _Me(m, qr);
            },
            builder: (context, me, reload) => Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(children: [
                  Container(color: Colors.white, padding: const EdgeInsets.all(8), child: Image.memory(me.qr, width: 200, height: 200)),
                  const SizedBox(height: 8),
                  Text(me.membership.number, style: Theme.of(context).textTheme.titleMedium),
                  Text('Since ${prettyDate(me.membership.issued)}  -  ${me.membership.status}'),
                  const Text('Show this at reception if you need help checking in.', style: TextStyle(fontSize: 12)),
                ]),
              ),
            ),
          ),
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          icon: const Icon(Icons.logout),
          label: const Text('Sign out'),
          onPressed: () async {
            if (await confirm(context, 'Sign out?', 'You will need to sign in again.', yes: 'Sign out', no: 'Stay')) {
              await session.logout();
            }
          },
        ),
      ]),
    );
  }
}
