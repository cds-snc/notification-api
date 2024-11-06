#!/bin/bash

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <profile_results_file>"
    exit 1
fi

input_file="$1"
output_file="${input_file%.prof}.png"

gprof2dot -n 0.25 -e 0.05 -f pstats "$input_file" | dot -Tpng -o "$output_file"
