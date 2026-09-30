import 'package:flutter/material.dart';


class SmartisLogPanel extends StatelessWidget {
  final List<String> entries;

  const SmartisLogPanel({
    super.key,
    required this.entries,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 125,
      margin: const EdgeInsets.symmetric(horizontal: 30),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: const Color(0xFFFFD700).withOpacity(.16),
        ),
        color: Colors.black.withOpacity(.24),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'LIVE LOG',
            style: TextStyle(
              color: Color(0xFFFFD700),
              fontSize: 9,
              letterSpacing: 1.8,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 6),
          Expanded(
            child: ListView.builder(
              reverse: true,
              itemCount: entries.length,
              itemBuilder: (_, index) {
                final item = entries[entries.length - 1 - index];
                return Text(
                  item,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: Colors.white54,
                    fontSize: 9.5,
                    fontFamily: 'Consolas',
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
