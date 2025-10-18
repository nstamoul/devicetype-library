#!/usr/bin/env python3
"""
Standalone Nautobot ORM script to find all InterfaceTemplate objects with invalid 1000base-x type.

Usage:
  python find_all_bad_types_standalone.py

This version includes Django setup, so it can be run directly without needing nautobot-server shell.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nautobot.core.settings')
django.setup()

from nautobot.dcim.models import InterfaceTemplate

print("=" * 80)
print("Searching for all InterfaceTemplate objects with type='1000base-x'")
print("=" * 80)

# Find all interfaces with the broken 1000base-x type
bad_interfaces = InterfaceTemplate.objects.filter(type='1000base-x')

if not bad_interfaces.exists():
    print("\n✓ No interfaces found with type='1000base-x'")
else:
    count = bad_interfaces.count()
    print(f"\n✗ Found {count} interface(s) with type='1000base-x':\n")

    for iface in bad_interfaces:
        print(f"  ID:          {iface.id}")
        print(f"  Name:        {iface.name}")
        print(f"  Device Type: {iface.device_type}")
        print(f"  Type:        {iface.type}")
        print(f"  Created:     {iface.created}")
        print()

print("=" * 80)
print("To fix these, run: python fix_all_bad_types_standalone.py")
print("=" * 80)
