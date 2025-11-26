#!/bin/bash

# Script to append +16135550123 to a file with auto-incrementing filename
# Usage: ./append_phone_numbers.sh [base_filename] [count]

# Default base filename if none provided
BASE_FILENAME="${1:-phone_numbers}"
PHONE_NUMBER="+16135550123"
# Default count if none provided, otherwise use second argument
COUNT="${2:-10000}"

# Function to find next available filename with timestamp
find_next_filename() {
    local base="$1"
    local timestamp=$(date +"%Y%m%d_%H%M")
    local counter=1
    local filename
    
    # First try with timestamp
    filename="${base}_${timestamp}.csv"
    if [[ ! -f "$filename" ]]; then
        echo "$filename"
        return
    fi
    
    # Then try with incrementing numbers if timestamp file exists
    while true; do
        filename="${base}_${timestamp}_${counter}.csv"
        if [[ ! -f "$filename" ]]; then
            echo "$filename"
            return
        fi
        ((counter++))
    done
}

# Get the next available filename
FILENAME=$(find_next_filename "$BASE_FILENAME")

# Validate that count is a positive number
if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [ "$COUNT" -le 0 ]; then
    echo "Error: Count must be a positive integer"
    echo "Usage: $0 [base_filename] [count]"
    echo "Example: $0 sms 50000"
    exit 1
fi

echo "Using filename: $FILENAME"
echo "Appending $PHONE_NUMBER to $FILENAME $COUNT times..."

# Add CSV header if file doesn't exist
if [[ ! -f "$FILENAME" ]]; then
    echo "phone number" > "$FILENAME"
fi

# Use a for loop to append the phone number specified number of times
for ((i=1; i<=COUNT; i++)); do
    echo "$PHONE_NUMBER" >> "$FILENAME"
    
    # Show progress every 10% or every 10,000 iterations, whichever is smaller
    progress_interval=$((COUNT / 10))
    if [ "$progress_interval" -gt 10000 ]; then
        progress_interval=10000
    elif [ "$progress_interval" -lt 1000 ]; then
        progress_interval=1000
    fi
    
    if ((i % progress_interval == 0)); then
        echo "Progress: $i/$COUNT"
    fi
done

echo "Completed! Added $COUNT entries to $FILENAME"
echo "File size: $(wc -l < "$FILENAME") lines"
