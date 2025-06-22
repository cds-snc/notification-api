#!/bin/bash

# Script to regenerate type_definitions.py from Marshmallow schemas.
# This eliminates duplication and keeps types in sync.

echo "Regenerating TypedDict definitions from Marshmallow schemas..."

# Generate the new type definitions
python /workspace/scripts/generate_types.py > /workspace/app/type_definitions_new.py

# Replace the old file
mv /workspace/app/type_definitions_new.py /workspace/app/type_definitions.py

echo "✅ Updated app/type_definitions.py with auto-generated types"
echo "Types are now automatically synced with ReportSchema"
