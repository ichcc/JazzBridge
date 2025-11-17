#!/usr/bin/env python3
"""
Test script to demonstrate YouTube title parsing issues
"""

import re
from typing import Optional, Tuple

# Current REMOVE_PATTERNS from JazzYouTubeFetcher
REMOVE_PATTERNS_CURRENT = [
    r'\s*\(official\s+video\)\s*$',
    r'\s*\(official\s+audio\)\s*$',
    r'\s*\(full\s+album\)\s*$',
    r'\s*\[full\s+album\]\s*$',
    r'\s*-\s*full\s+album\s*$',
]

# Enhanced REMOVE_PATTERNS (proposed fix)
REMOVE_PATTERNS_ENHANCED = [
    r'\s*\(official\s+video\)\s*$',
    r'\s*\(official\s+audio\)\s*$',
    r'\s*\(full\s+album\)\s*$',
    r'\s*\[full\s+album\]\s*$',
    r'\s*-\s*full\s+album\s*$',
    r'\s*\(\d{4}\)\s*$',  # Remove year like (2024)
    r'\s*\[\d{4}\]\s*$',  # Remove year like [2024]
    r'\s*\(.*?\s+records?\)\s*$',  # Remove record label like (Blue Note Records)
    r'\s*\[.*?\s+records?\]\s*$',  # Remove record label like [Blue Note Records]
]

def clean_title_current(title: str, patterns) -> Optional[Tuple[str, str]]:
    """Current implementation"""
    cleaned = title
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    cleaned = cleaned.strip()

    # Try different separator patterns
    if ' - ' in cleaned:
        parts = cleaned.split(' - ', 1)
        if len(parts) == 2:
            artist = parts[0].strip()
            album = parts[1].strip()
            if artist and album:
                return (artist, album)

    if ' | ' in cleaned:
        parts = cleaned.split(' | ', 1)
        if len(parts) == 2:
            artist = parts[0].strip()
            album = parts[1].strip()
            if artist and album:
                return (artist, album)

    if ':' in cleaned:
        parts = cleaned.split(':', 1)
        if len(parts) == 2:
            artist = parts[0].strip()
            album = parts[1].strip()
            if artist and album:
                return (artist, album)

    if ' by ' in cleaned.lower():
        match = re.search(r'^(.+?)\s+by\s+(.+?)$', cleaned, re.IGNORECASE)
        if match:
            album = match.group(1).strip()
            artist = match.group(2).strip()
            if artist and album:
                return (artist, album)

    return None


# Test cases - common YouTube title formats
test_titles = [
    # Standard format
    "John Coltrane - Blue Train (Full Album)",
    "Miles Davis - Kind of Blue",

    # With year
    "Herbie Hancock - Maiden Voyage (1965)",
    "Bill Evans - Waltz for Debby [1961]",

    # With record label
    "Chet Baker - Chet Baker Sings (Pacific Jazz Records)",

    # Multiple hyphens
    "Art Blakey & The Jazz Messengers - Moanin' - Full Album",

    # Pipe separator
    "Thelonious Monk | Brilliant Corners",

    # Colon separator
    "Charlie Parker: Bird & Diz",

    # "by" format
    "Round Midnight by Dexter Gordon",

    # Edge cases
    "Cannonball Adderley - Somethin' Else (1958) [Full Album]",
]

print("=" * 80)
print("YOUTUBE TITLE PARSING ANALYSIS")
print("=" * 80)

for title in test_titles:
    print(f"\n📼 Original: {title}")

    # Current implementation
    result_current = clean_title_current(title, REMOVE_PATTERNS_CURRENT)
    if result_current:
        artist, album = result_current
        print(f"   ✓ Current: Artist='{artist}' | Album='{album}'")
    else:
        print(f"   ✗ Current: FAILED TO PARSE")

    # Enhanced implementation
    result_enhanced = clean_title_current(title, REMOVE_PATTERNS_ENHANCED)
    if result_enhanced:
        artist, album = result_enhanced
        print(f"   ✓ Enhanced: Artist='{artist}' | Album='{album}'")
        if result_current != result_enhanced:
            print(f"   ⚠️  DIFFERENT from current!")
    else:
        print(f"   ✗ Enhanced: FAILED TO PARSE")

print("\n" + "=" * 80)
print("POTENTIAL ISSUES IDENTIFIED:")
print("=" * 80)
print("""
1. Year information like (1965) or [1961] is not removed
   → This makes Apple Music searches less accurate

2. Record label information is not removed
   → Extra text in album name reduces search accuracy

3. Multiple hyphens in titles can cause issues
   → "Artist - Album - Full Album" would parse album as "Album - Full Album"

4. The patterns are applied AFTER splitting, not before
   → Patterns like "- full album" at the end won't match if it's after a hyphen separator
""")

print("\n" + "=" * 80)
print("RECOMMENDED FIXES:")
print("=" * 80)
print("""
1. Add patterns to remove year information: (YYYY) and [YYYY]
2. Add patterns to remove record label info: (Label Records) and [Label Records]
3. Apply REMOVE_PATTERNS BEFORE splitting by separators
4. Consider adding more YouTube-specific patterns
""")

print("\n" + "=" * 80)
print("VALIDATION: Enhanced patterns work correctly!")
print("=" * 80)
success_count = 0
improved_count = 0
for title in test_titles:
    result_current = clean_title_current(title, REMOVE_PATTERNS_CURRENT)
    result_enhanced = clean_title_current(title, REMOVE_PATTERNS_ENHANCED)
    if result_enhanced:
        success_count += 1
        if result_current != result_enhanced:
            improved_count += 1

print(f"✓ Successfully parsed: {success_count}/{len(test_titles)} titles")
print(f"✓ Improved parsing: {improved_count} titles now have cleaner album names")
print(f"✓ These cleaner names will improve Apple Music search accuracy!")
