#!/usr/bin/env python3

import sys
import pstats

def compare_profiles(profile1_path, profile2_path, top_n=10):
    # Load both profiling snapshots
    p1 = pstats.Stats(profile1_path)
    p2 = pstats.Stats(profile2_path)

    # Extract the stats data dictionaries
    stats1 = p1.stats
    stats2 = p2.stats

    # Compare cumulative times for each function
    differences = {}
    for func in stats1:
        if func in stats2:
            # Calculate difference in cumulative time
            cumtime_diff = stats2[func][3] - stats1[func][3]  # cumulative time is at index 3
            differences[func] = cumtime_diff
        else:
            # If function only exists in one profile, note that
            differences[func] = stats1[func][3]

    # Sort by largest cumulative time difference
    sorted_diffs = sorted(differences.items(), key=lambda x: abs(x[1]), reverse=True)

    # Display the top differences
    print(f"Top {top_n} cumulative time differences between {profile1_path} and {profile2_path}:")
    for func, diff in sorted_diffs[:top_n]:  # Show top N differences
        func_name = f"{func[2]} ({func[0]}:{func[1]})"
        print(f"{func_name:<50} cumulative time difference: {diff:.5f} seconds")

if __name__ == "__main__":
    # Check if two arguments are provided
    if len(sys.argv) != 3:
        print("Usage: cmprof.py <profile1.prof> <profile2.prof>")
        sys.exit(1)

    # Get file paths from command line
    profile1_path = sys.argv[1]
    profile2_path = sys.argv[2]

    # Run the comparison
    compare_profiles(profile1_path, profile2_path)
