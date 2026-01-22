#!/usr/bin/env python
"""Test script to verify the service name validation logic works correctly"""

import base64


def calculate_from_address_length(service_name, email_from, sending_domain="notification.canada.ca"):
    """
    Calculate the length of the from address as it would be formatted for email sending.
    This matches the logic in get_from_address() from app/delivery/send_to_providers.py
    """
    # Base64 encode the service name
    name_b64 = base64.b64encode(service_name.encode()).decode("utf-8")

    # Format as MIME encoded-word syntax
    mime_encoded_name = f"=?utf-8?B?{name_b64}?="

    # Build the full from address
    from_address = f'"{mime_encoded_name}" <{email_from}@{sending_domain}>'

    return len(from_address)


# Test cases
print("Testing service name + email address length validation")
print("=" * 80)

# Test 1: The exact bug case from the issue
long_name_with_accents = "é" * 179  # 179 accented characters
long_email = "abc-1234-12345-1234567-1234567"
domain = "notification.canada.ca"

length = calculate_from_address_length(long_name_with_accents, long_email, domain)
print("\nTest 1: Bug reproduction case")
print(f"Service name: {'é' * 179} (179 characters)")
print(f"Email from: {long_email}")
print(f"Domain: {domain}")
print(f"From address length: {length} characters")
print(f"Exceeds 320 limit? {'YES ❌' if length > 320 else 'NO ✓'}")

# Test 2: Normal service name
normal_name = "Test Service"
normal_email = "test.service"

length2 = calculate_from_address_length(normal_name, normal_email, domain)
print("\nTest 2: Normal service name")
print(f"Service name: {normal_name}")
print(f"Email from: {normal_email}")
print(f"Domain: {domain}")
print(f"From address length: {length2} characters")
print(f"Exceeds 320 limit? {'YES ❌' if length2 > 320 else 'NO ✓'}")

# Test 3: Long but reasonable name (100 characters)
medium_name = "Service " * 14  # About 98 characters
medium_email = "medium.service"

length3 = calculate_from_address_length(medium_name.strip(), medium_email, domain)
print("\nTest 3: Medium length service name")
print(f"Service name: {medium_name.strip()[:50]}... ({len(medium_name.strip())} characters)")
print(f"Email from: {medium_email}")
print(f"Domain: {domain}")
print(f"From address length: {length3} characters")
print(f"Exceeds 320 limit? {'YES ❌' if length3 > 320 else 'NO ✓'}")

# Test 4: Find the maximum safe length for ASCII names
print("\nTest 4: Finding maximum safe ASCII name length")
for name_length in range(150, 200):
    test_name = "a" * name_length
    test_email = "test"
    test_length = calculate_from_address_length(test_name, test_email, domain)
    if test_length > 320:
        print(f"Maximum safe ASCII name length: {name_length - 1} characters")
        print(
            f"(Would result in from address length of {calculate_from_address_length('a' * (name_length - 1), test_email, domain)} characters)"
        )
        break

# Test 5: Find the maximum safe length for accented names (worst case)
print("\nTest 5: Finding maximum safe UTF-8/accented name length")
for name_length in range(100, 150):
    test_name = "é" * name_length
    test_email = "test"
    test_length = calculate_from_address_length(test_name, test_email, domain)
    if test_length > 320:
        print(f"Maximum safe accented name length: {name_length - 1} characters")
        print(
            f"(Would result in from address length of {calculate_from_address_length('é' * (name_length - 1), test_email, domain)} characters)"
        )
        break

print("\n" + "=" * 80)
print("Validation logic test complete!")
