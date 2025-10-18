#!/usr/bin/env python3
"""
Generic Nautobot ORM script to fix all InterfaceTemplate objects with invalid 1000base-x type.
This updates them to the valid 1000base-x-sfp type.

Usage:
  # In Nautobot container:
  nautobot-server shell

  # Then paste this script or:
  exec(open('/path/to/fix_all_bad_types.py').read())
"""

from nautobot.dcim.models import InterfaceTemplate

print("=" * 80)
print("Finding all InterfaceTemplate objects with type='1000base-x'")
print("=" * 80)

# Find all interfaces with the broken 1000base-x type
bad_interfaces = InterfaceTemplate.objects.filter(type='1000base-x')

if not bad_interfaces.exists():
    print("\n✓ No interfaces to fix. All interfaces have valid types.")
else:
    count = bad_interfaces.count()
    print(f"\nFound {count} interface(s) to fix.\n")
    print("Updating all interfaces from type='1000base-x' to type='1000base-x-sfp'...\n")

    fixed_count = 0
    for iface in bad_interfaces:
        try:
            print(f"  Updating: {iface.device_type.model} - {iface.name}")
            iface.type = '1000base-x-sfp'
            iface.save()
            fixed_count += 1
            print(f"    ✓ Successfully updated\n")
        except Exception as e:
            print(f"    ✗ Error updating: {e}\n")

    print("=" * 80)
    print(f"Results: {fixed_count}/{count} interfaces successfully updated")
    print("=" * 80)

    # Verify the fixes
    print("\nVerifying fixes...")
    remaining_bad = InterfaceTemplate.objects.filter(type='1000base-x')
    if remaining_bad.exists():
        print(f"✗ Warning: {remaining_bad.count()} interfaces still have type='1000base-x'")
    else:
        print("✓ All interfaces have been successfully fixed!")
