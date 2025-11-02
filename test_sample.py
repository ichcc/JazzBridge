#!/usr/bin/env python3
"""
Test script to demonstrate GetMusic functionality with sample data.
This bypasses the RSS feed to test core functionality.
"""

from getmusic import AlbumFetcher, OutputGenerator

def test_with_sample_data():
    """Test with sample album data."""

    print("Testing GetMusic with sample data...\n")

    fetcher = AlbumFetcher(verbose=True)

    # Sample titles from All About Jazz format
    sample_titles = [
        "Martin Nodeland: Tributaries album review",
        "Jane Monheit: Come What May",
        "Brad Mehldau: Your Mother Should Know: Brad Mehldau Plays The Beatles",
        "Cécile McLorin Salvant: Mélusine",
    ]

    results = []

    for title in sample_titles:
        print(f"\n--- Processing: {title}")

        # Clean and parse title
        parsed = fetcher.clean_title(title)
        if not parsed:
            print(f"  ❌ Could not parse title")
            continue

        artist, album = parsed
        print(f"  ✓ Parsed: {artist} - {album}")

        # Search for album link
        album_link = fetcher.search_album_link(artist, album)

        if album_link:
            print(f"  ✓ Found: {album_link}")
            results.append((artist, album, album_link, "2025-11-02"))
        else:
            print(f"  ❌ No Album.link found")

    print(f"\n\n{'='*60}")
    print(f"RESULTS: Found {len(results)} albums with Album.link URLs")
    print(f"{'='*60}\n")

    # Generate outputs
    if results:
        OutputGenerator.generate_markdown(results, "sample_output.md")
        OutputGenerator.generate_csv(results, "sample_output.csv")

        print("\n📄 Sample Markdown output:")
        with open("sample_output.md", "r") as f:
            print(f.read())
    else:
        print("No results to output.")

if __name__ == '__main__':
    test_with_sample_data()
