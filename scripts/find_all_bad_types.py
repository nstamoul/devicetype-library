#!/usr/bin/env python3
"""
Generic Nautobot ORM script to find all InterfaceTemplate objects with invalid 1000base-x type.
This can be run in the Nautobot Django shell.

Usage:
  # In Nautobot container:
  nautobot-server shell

  # Then paste this script or:
  exec(open('/path/to/find_all_bad_types.py').read())
"""

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
print("To fix these, run the update script: fix_bad_types.py")
print("=" * 80)
