#!/bin/bash

# Script to generate TypeScript types from OpenAPI specification
# This script uses openapi-typescript to generate types from the OpenAPI spec

set -e

echo "Generating TypeScript types from OpenAPI specification..."

# Check if openapi-typescript is installed globally
if ! command -v openapi-typescript &> /dev/null; then
    echo "openapi-typescript not found. Installing..."
    npm install -g openapi-typescript
fi

# Create output directory if it doesn't exist
mkdir -p types

# Generate TypeScript types from OpenAPI spec
openapi-typescript openapi/v2-notifications-api-en.yaml -o types/api-types.ts

echo "TypeScript types generated successfully in types/api-types.ts"
echo ""
echo "To use the types in your application:"
echo "1. Copy the types/api-types.ts file to your project"
echo "2. Import the types you need:"
echo ""
echo "import type { components } from './api-types';"
echo ""
echo "type Report = components['schemas']['Report'];"
echo "type GetServiceReportsResponse = {"
echo "  data: Report[];"
echo "};"
echo ""
echo "// Example usage in a function"
echo "async function getReports(serviceId: string): Promise<GetServiceReportsResponse> {"
echo "  const response = await fetch(\`/service/\${serviceId}/report\`);"
echo "  return response.json();"
echo "}"
