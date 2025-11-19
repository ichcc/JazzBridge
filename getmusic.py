#!/usr/bin/env python3
"""
GetMusic - All About Jazz to Album.link automation

Fetches new jazz album mentions from All About Jazz RSS feed,
searches for them on Album.link, and generates a consolidated list.
"""

import feedparser
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import argparse
import csv
import sys
import re
import time
import json
import os
from datetime import datetime
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


# Global rate limiter for song.link API (10 requests/minute)
# This ensures all threads respect the same rate limit
_rate_limit_lock = threading.Lock()
_last_api_call_time = 0

def rate_limited_sleep():
    """
    Sleep to respect song.link API rate limit (10 requests/minute).
    This is thread-safe and shared across all fetchers.
    """
    global _last_api_call_time
    with _rate_limit_lock:
        current_time = time.time()
        time_since_last_call = current_time - _last_api_call_time

        # Ensure at least 6 seconds between API calls (10 req/min)
        if time_since_last_call < 6:
            sleep_time = 6 - time_since_last_call
            time.sleep(sleep_time)

        _last_api_call_time = time.time()


# Shared cache lock for thread-safe cache operations
_cache_lock = threading.Lock()


class AlbumFetcher:
    """Handles fetching and processing jazz albums from All About Jazz."""

    RSS_URL = "https://www.allaboutjazz.com/rss_reviews.xml"
    ALBUM_LINK_SEARCH = "https://album.link/search?q={}"
    CACHE_FILE = "album_cache.json"

    # Patterns to remove from titles
    REMOVE_PATTERNS = [
        r'\s*album review\s*$',
        r'\s*concert review\s*$',
        r'\s*premiere\s*$',
        r'\s*review\s*$',
    ]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        self.cache: Dict[str, Dict] = {}
        self.load_cache()

    def log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(f"[INFO] {message}")

    def normalize_cache_key(self, artist: str, album: str) -> str:
        """
        Create a normalized cache key from artist and album.

        Args:
            artist: Artist name
            album: Album title

        Returns:
            Normalized cache key
        """
        # Lowercase and strip whitespace for consistent matching
        return f"{artist.lower().strip()}||{album.lower().strip()}"

    def load_cache(self):
        """Load the album cache from disk (thread-safe)."""
        with _cache_lock:
            if os.path.exists(self.CACHE_FILE):
                try:
                    with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                        self.cache = json.load(f)
                    self.log(f"Loaded {len(self.cache)} entries from cache")
                except Exception as e:
                    self.log(f"Error loading cache: {e}")
                    self.cache = {}
            else:
                self.log("No cache file found, starting with empty cache")
                self.cache = {}

    def save_cache(self):
        """Save the album cache to disk (thread-safe)."""
        with _cache_lock:
            try:
                with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.cache, f, indent=2, ensure_ascii=False)
                self.log(f"Saved {len(self.cache)} entries to cache")
            except Exception as e:
                self.log(f"Error saving cache: {e}")

    def get_from_cache(self, artist: str, album: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
        """
        Get album links from cache if available (thread-safe).

        Args:
            artist: Artist name
            album: Album title

        Returns:
            Tuple of (album_link, apple_music_link) or None if not in cache
        """
        key = self.normalize_cache_key(artist, album)
        with _cache_lock:
            if key in self.cache:
                entry = self.cache[key]
                self.log(f"Cache hit for: {artist} - {album}")
                return (entry.get('album_link'), entry.get('apple_music_link'))
        return None

    def add_to_cache(self, artist: str, album: str, album_link: Optional[str], apple_music_link: Optional[str]):
        """
        Add or update album in cache (thread-safe).

        Args:
            artist: Artist name
            album: Album title
            album_link: Album.link URL (or None if not found)
            apple_music_link: Apple Music URL (or None if not found)
        """
        key = self.normalize_cache_key(artist, album)
        today = datetime.now().strftime('%Y-%m-%d')

        with _cache_lock:
            if key in self.cache:
                # Update existing entry
                self.cache[key]['album_link'] = album_link
                self.cache[key]['apple_music_link'] = apple_music_link
                self.cache[key]['last_checked'] = today
            else:
                # Create new entry
                self.cache[key] = {
                    'artist': artist,
                    'album': album,
                    'album_link': album_link,
                    'apple_music_link': apple_music_link,
                    'first_seen': today,
                    'last_checked': today
                }

        self.log(f"Added to cache: {artist} - {album}")

    def fetch_rss(self) -> List[dict]:
        """Fetch and parse the All About Jazz RSS feed."""
        self.log(f"Fetching RSS from {self.RSS_URL}")
        try:
            feed = feedparser.parse(self.RSS_URL)
            if feed.bozo:
                self.log(f"Warning: RSS feed parsing had errors: {feed.get('bozo_exception', 'Unknown error')}")
            self.log(f"Found {len(feed.entries)} entries")
            return feed.entries
        except Exception as e:
            self.log(f"Error fetching RSS feed: {e}")
            import traceback
            self.log(traceback.format_exc())
            return []

    def clean_title(self, title: str) -> Optional[Tuple[str, str]]:
        """
        Clean title and extract artist and album.

        Args:
            title: Raw title from RSS feed

        Returns:
            Tuple of (artist, album) or None if parsing fails
        """
        # Remove common suffixes
        cleaned = title
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()

        # Split on first colon
        if ':' not in cleaned:
            self.log(f"Skipping title without colon separator: {title}")
            return None

        parts = cleaned.split(':', 1)
        if len(parts) != 2:
            return None

        artist = parts[0].strip()
        album = parts[1].strip()

        if not artist or not album:
            return None

        return (artist, album)

    def search_apple_music(self, artist: str, album: str) -> Optional[str]:
        """
        Search Apple Music for the album and return the Apple Music album URL.

        Uses the public iTunes Search API which doesn't require authentication.

        Args:
            artist: Artist name
            album: Album title

        Returns:
            Apple Music album URL or None if not found
        """
        query = f"{artist} {album}"

        self.log(f"Searching Apple Music for: {query}")

        try:
            # iTunes Search API
            search_url = "https://itunes.apple.com/search"
            params = {
                'term': query,
                'media': 'music',
                'entity': 'album',
                'limit': 5
            }

            response = self.session.get(search_url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            results = data.get('results', [])

            if results:
                # Get the first result's collection view URL
                first_result = results[0]
                apple_url = first_result.get('collectionViewUrl')

                if apple_url:
                    self.log(f"Found Apple Music URL: {apple_url}")
                    return apple_url
                else:
                    self.log("No URL in Apple Music result")
                    return None
            else:
                self.log(f"No Apple Music results for: {query}")
                return None

        except requests.RequestException as e:
            self.log(f"Error searching Apple Music: {e}")
            return None
        except ValueError as e:
            self.log(f"Error parsing Apple Music response: {e}")
            return None

    def convert_url_to_album_link(self, music_url: str) -> Optional[str]:
        """
        Convert any music streaming URL to Album.link URL using song.link API.

        Args:
            music_url: URL from any music service (Spotify, Apple Music, etc.)

        Returns:
            Album.link URL or None if conversion fails
        """
        api_url = f"https://api.song.link/v1-alpha.1/links?url={quote(music_url)}"

        self.log(f"Converting to Album.link via API...")

        # Rate limiting: 10 requests/minute without API key
        # Use global rate limiter to coordinate across all threads
        rate_limited_sleep()

        try:
            response = self.session.get(api_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            page_url = data.get('pageUrl')

            if page_url:
                # Remove country code from URL (e.g., /us/i/ -> /i/)
                # The canonical URLs work better without country codes
                page_url = page_url.replace('/us/i/', '/i/')
                page_url = page_url.replace('/uk/i/', '/i/')
                page_url = page_url.replace('/ca/i/', '/i/')

                self.log(f"Got Album.link: {page_url}")
                return page_url
            else:
                self.log("No pageUrl in API response")
                return None

        except requests.RequestException as e:
            self.log(f"Error calling song.link API: {e}")
            return None
        except ValueError as e:
            self.log(f"Error parsing API response: {e}")
            return None

    def search_album_link(self, artist: str, album: str) -> Optional[str]:
        """
        Search for album and return Album.link URL.

        Uses a two-step process:
        1. Search Apple Music for the album
        2. Convert Apple Music URL to Album.link using song.link API

        Args:
            artist: Artist name
            album: Album title

        Returns:
            Album.link URL or None if not found
        """
        # First, try to find on Apple Music
        apple_url = self.search_apple_music(artist, album)

        if apple_url:
            # Then try to convert to Album.link
            album_link = self.convert_url_to_album_link(apple_url)
            if album_link:
                return album_link

        self.log(f"No album.link found for: {artist} - {album}")
        return None

    def process_feed(self) -> List[Tuple[str, str, str, str, str]]:
        """
        Process RSS feed and search for albums.

        Returns:
            List of tuples: (artist, album, album_link, apple_music_link, date)
        """
        entries = self.fetch_rss()
        results = []

        for entry in entries:
            title = entry.get('title', '')
            pub_date = entry.get('published', '')

            # Parse date
            date_str = ''
            if pub_date:
                try:
                    # Try RSS format first: "Fri, 08 Nov 2025 07:00:00 +0000"
                    date_obj = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z')
                    date_str = date_obj.strftime('%Y-%m-%d')
                except ValueError:
                    try:
                        # Try ISO 8601 format: "2025-11-08T07:00:00.000-08:00"
                        # Handle both with and without microseconds
                        if '.' in pub_date:
                            date_obj = datetime.strptime(pub_date, '%Y-%m-%dT%H:%M:%S.%f%z')
                        else:
                            date_obj = datetime.strptime(pub_date, '%Y-%m-%dT%H:%M:%S%z')
                        date_str = date_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        # Fallback: try to extract date from RSS format by splitting
                        try:
                            date_parts = pub_date.split(',')[1].strip().split()[0:3]
                            date_str = ' '.join(date_parts) if date_parts else pub_date
                        except (IndexError, AttributeError):
                            # Last resort: just use the raw date string
                            date_str = pub_date

            # Clean and parse title
            parsed = self.clean_title(title)
            if not parsed:
                continue

            artist, album = parsed
            self.log(f"Processing: {artist} - {album}")

            # Check cache first
            cached_result = self.get_from_cache(artist, album)
            if cached_result is not None:
                album_link, apple_url = cached_result
                self.log(f"Using cached result for: {artist} - {album}")
            else:
                # Not in cache, search Apple Music first
                apple_url = self.search_apple_music(artist, album)
                album_link = None

                if apple_url:
                    # Then get album.link URL
                    album_link = self.convert_url_to_album_link(apple_url)

                # Add to cache
                self.add_to_cache(artist, album, album_link, apple_url)

            # Add to results even if link not found (will show as placeholder)
            results.append((artist, album, album_link or '', apple_url or '', date_str))

        # Save cache after processing all entries
        self.save_cache()

        return results


class JazzProfilesFetcher(AlbumFetcher):
    """Handles fetching and processing jazz albums from Jazz Profiles blog."""

    RSS_URL = "https://jazzprofiles.blogspot.com/feeds/posts/default"

    # Jazz Profiles specific patterns (album mentions, reviews, etc.)
    REMOVE_PATTERNS = [
        r'\s*album review\s*$',
        r'\s*review\s*$',
        r'\s*-\s*album\s*$',
        r'\s*\[album\]\s*$',
    ]

    def clean_title(self, title: str) -> Optional[Tuple[str, str]]:
        """
        Clean title and extract artist and album from Jazz Profiles format.

        Jazz Profiles may use different formats:
        - "Artist - Album"
        - "Artist: Album"
        - "Album by Artist"
        - Or just descriptive titles

        Args:
            title: Raw title from RSS feed

        Returns:
            Tuple of (artist, album) or None if parsing fails
        """
        # Remove common suffixes
        cleaned = title
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()

        # Try different separator patterns
        # First try colon (like All About Jazz)
        if ':' in cleaned:
            parts = cleaned.split(':', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try hyphen separator
        if ' - ' in cleaned:
            parts = cleaned.split(' - ', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try "Album by Artist" format
        if ' by ' in cleaned.lower():
            match = re.search(r'^(.+?)\s+by\s+(.+?)$', cleaned, re.IGNORECASE)
            if match:
                album = match.group(1).strip()
                artist = match.group(2).strip()
                if artist and album:
                    return (artist, album)

        self.log(f"Skipping title - couldn't parse: {title}")
        return None


class JazzChillFetcher(AlbumFetcher):
    """Handles fetching and processing jazz albums from JazzChill blog."""

    RSS_URL = "https://jazzchill.blogspot.com/feeds/posts/default"

    # JazzChill specific patterns (album mentions, reviews, etc.)
    REMOVE_PATTERNS = [
        r'\s*album review\s*$',
        r'\s*review\s*$',
        r'\s*-\s*album\s*$',
        r'\s*\[album\]\s*$',
    ]

    def clean_title(self, title: str) -> Optional[Tuple[str, str]]:
        """
        Clean title and extract artist and album from JazzChill format.

        JazzChill may use different formats:
        - "Artist - Album"
        - "Artist: Album"
        - "Album by Artist"
        - Or just descriptive titles

        Args:
            title: Raw title from RSS feed

        Returns:
            Tuple of (artist, album) or None if parsing fails
        """
        # Remove common suffixes
        cleaned = title
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()

        # Try different separator patterns
        # First try colon (like All About Jazz)
        if ':' in cleaned:
            parts = cleaned.split(':', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try hyphen separator
        if ' - ' in cleaned:
            parts = cleaned.split(' - ', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try "Album by Artist" format
        if ' by ' in cleaned.lower():
            match = re.search(r'^(.+?)\s+by\s+(.+?)$', cleaned, re.IGNORECASE)
            if match:
                album = match.group(1).strip()
                artist = match.group(2).strip()
                if artist and album:
                    return (artist, album)

        self.log(f"Skipping title - couldn't parse: {title}")
        return None


class JazzWaxFetcher(AlbumFetcher):
    """Handles fetching and processing jazz albums from JazzWax blog."""

    RSS_URL = "https://jazzwax.com/feed/"

    # JazzWax specific patterns (album mentions, reviews, etc.)
    REMOVE_PATTERNS = [
        r'\s*album review\s*$',
        r'\s*review\s*$',
        r'\s*-\s*album\s*$',
        r'\s*\[album\]\s*$',
    ]

    def clean_title(self, title: str) -> Optional[Tuple[str, str]]:
        """
        Clean title and extract artist and album from JazzWax format.

        JazzWax may use different formats:
        - "Artist - Album"
        - "Artist: Album"
        - "Album by Artist"
        - Or just descriptive titles

        Args:
            title: Raw title from RSS feed

        Returns:
            Tuple of (artist, album) or None if parsing fails
        """
        # Remove common suffixes
        cleaned = title
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()

        # Try different separator patterns
        # First try colon (like All About Jazz)
        if ':' in cleaned:
            parts = cleaned.split(':', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try hyphen separator
        if ' - ' in cleaned:
            parts = cleaned.split(' - ', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try "Album by Artist" format
        if ' by ' in cleaned.lower():
            match = re.search(r'^(.+?)\s+by\s+(.+?)$', cleaned, re.IGNORECASE)
            if match:
                album = match.group(1).strip()
                artist = match.group(2).strip()
                if artist and album:
                    return (artist, album)

        self.log(f"Skipping title - couldn't parse: {title}")
        return None


class HardToFindVinylsFetcher(AlbumFetcher):
    """Handles fetching and processing jazz albums from Hard To Find Vinyls YouTube channel."""

    RSS_URL = "https://www.youtube.com/feeds/videos.xml?user=hardtofindvinyls"

    # YouTube video title patterns
    REMOVE_PATTERNS = [
        # Remove everything from opening parenthesis to end (country, year, etc)
        # e.g., (US, 1974), (USA, 1982), (Senegal, 1975)
        r'\s*\([^)]*\d{4}[^)]*\).*$',  # Remove (location, year) and everything after
        r'\s*\(US,?\s*\d{4}\).*$',  # Specifically handle (US, 1974) format
        r'\s*\(USA,?\s*\d{4}\).*$',  # Specifically handle (USA, 1982) format

        # Remove square brackets with any content
        r'\s*\[[^\]]+\].*$',  # Remove [Full LP], [Full Album], etc and everything after

        # Remove curly braces with genre tags
        r'\s*\{[^}]+\}.*$',  # Remove {Jazz-Funk, Soul-Jazz} and everything after

        # Remove star ratings and descriptions
        r'\s*★+[^★]*★+.*$',  # Remove ★★BANGER★★ and everything after
        r'\s*★[^★]+★.*$',  # Remove ★MASTERPIECE★ and everything after

        # Remove hashtags and everything after
        r'\s*#\w+.*$',  # Remove #vinyl and everything after

        # Original patterns (as fallback for simpler cases)
        r'\s*\(official\s+video\)\s*$',
        r'\s*\(official\s+audio\)\s*$',
        r'\s*\(full\s+album\)\s*$',
        r'\s*-\s*full\s+album\s*$',
    ]

    def clean_title(self, title: str) -> Optional[Tuple[str, str]]:
        """
        Clean title and extract artist and album from YouTube video title.

        Hard To Find Vinyls may use formats like:
        - "Artist - Album"
        - "Artist: Album"
        - "Album by Artist"
        - "Artist | Album"

        Args:
            title: Raw title from YouTube RSS feed

        Returns:
            Tuple of (artist, album) or None if parsing fails
        """
        # Remove common suffixes
        cleaned = title
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()

        # Try different separator patterns
        # First try hyphen (most common for YouTube)
        if ' - ' in cleaned:
            parts = cleaned.split(' - ', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try pipe separator
        if ' | ' in cleaned:
            parts = cleaned.split(' | ', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try colon separator
        if ':' in cleaned:
            parts = cleaned.split(':', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try "Album by Artist" format
        if ' by ' in cleaned.lower():
            match = re.search(r'^(.+?)\s+by\s+(.+?)$', cleaned, re.IGNORECASE)
            if match:
                album = match.group(1).strip()
                artist = match.group(2).strip()
                if artist and album:
                    return (artist, album)

        self.log(f"Skipping title - couldn't parse: {title}")
        return None


class JazzYouTubeFetcher(AlbumFetcher):
    """Handles fetching and processing jazz albums from YouTube channel (UCSa-MrfLJ9epUEITf3xHgKg)."""

    RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UCSa-MrfLJ9epUEITf3xHgKg"

    # YouTube video title patterns
    REMOVE_PATTERNS = [
        # Remove everything from opening parenthesis to end (country, year, etc)
        # e.g., (US, 1974), (USA, 1982), (Senegal, 1975)
        r'\s*\([^)]*\d{4}[^)]*\).*$',  # Remove (location, year) and everything after
        r'\s*\(US,?\s*\d{4}\).*$',  # Specifically handle (US, 1974) format
        r'\s*\(USA,?\s*\d{4}\).*$',  # Specifically handle (USA, 1982) format

        # Remove square brackets with any content
        r'\s*\[[^\]]+\].*$',  # Remove [Full LP], [Full Album], etc and everything after

        # Remove curly braces with genre tags
        r'\s*\{[^}]+\}.*$',  # Remove {Jazz-Funk, Soul-Jazz} and everything after

        # Remove star ratings and descriptions
        r'\s*★+[^★]*★+.*$',  # Remove ★★BANGER★★ and everything after
        r'\s*★[^★]+★.*$',  # Remove ★MASTERPIECE★ and everything after

        # Remove hashtags and everything after
        r'\s*#\w+.*$',  # Remove #vinyl and everything after

        # Original patterns (as fallback for simpler cases)
        r'\s*\(official\s+video\)\s*$',
        r'\s*\(official\s+audio\)\s*$',
        r'\s*\(full\s+album\)\s*$',
        r'\s*-\s*full\s+album\s*$',
    ]

    def clean_title(self, title: str) -> Optional[Tuple[str, str]]:
        """
        Clean title and extract artist and album from YouTube video title.

        YouTube channels may use formats like:
        - "Artist - Album"
        - "Artist: Album"
        - "Album by Artist"
        - "Artist | Album"

        Args:
            title: Raw title from YouTube RSS feed

        Returns:
            Tuple of (artist, album) or None if parsing fails
        """
        # Remove common suffixes
        cleaned = title
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.strip()

        # Try different separator patterns
        # First try hyphen (most common for YouTube)
        if ' - ' in cleaned:
            parts = cleaned.split(' - ', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try pipe separator
        if ' | ' in cleaned:
            parts = cleaned.split(' | ', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try colon separator
        if ':' in cleaned:
            parts = cleaned.split(':', 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                album = parts[1].strip()
                if artist and album:
                    return (artist, album)

        # Try "Album by Artist" format
        if ' by ' in cleaned.lower():
            match = re.search(r'^(.+?)\s+by\s+(.+?)$', cleaned, re.IGNORECASE)
            if match:
                album = match.group(1).strip()
                artist = match.group(2).strip()
                if artist and album:
                    return (artist, album)

        self.log(f"Skipping title - couldn't parse: {title}")
        return None


class OutputGenerator:
    """Handles output generation in various formats."""

    @staticmethod
    def generate_markdown(results: List[Tuple[str, str, str, str, str]], output_file: str):
        """Generate Markdown output."""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("## 🎶 New Jazz Albums\n\n")
            f.write("_Links: [All Platforms] | [Apple Music]_\n\n")
            if not results:
                f.write("No albums found.\n")
            else:
                for artist, album, album_link, apple_link, date in results:
                    f.write(f"- **{artist} — {album}** [[All]({album_link})] [[Apple]({apple_link})]")
                    if date:
                        f.write(f" _{date}_")
                    f.write("\n")
        print(f"Markdown output written to: {output_file}")

    @staticmethod
    def generate_csv(results: List[Tuple[str, str, str, str, str]], output_file: str):
        """Generate CSV output."""
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['artist', 'album', 'album_link', 'apple_music_link', 'date'])
            for row in results:
                writer.writerow(row)
        print(f"CSV output written to: {output_file}")

    @staticmethod
    def generate_html(results: List[Tuple[str, str, str, str, str]], output_file: str,
                     jazz_profiles_results: Optional[List[Tuple[str, str, str, str, str]]] = None,
                     jazz_chill_results: Optional[List[Tuple[str, str, str, str, str]]] = None,
                     jazz_wax_results: Optional[List[Tuple[str, str, str, str, str]]] = None,
                     htfv_results: Optional[List[Tuple[str, str, str, str, str]]] = None,
                     jazz_youtube_results: Optional[List[Tuple[str, str, str, str, str]]] = None):
        """Generate HTML output with embedded album.link widgets from multiple sources."""
        total_albums = len(results) + \
                      (len(jazz_profiles_results) if jazz_profiles_results else 0) + \
                      (len(jazz_chill_results) if jazz_chill_results else 0) + \
                      (len(jazz_wax_results) if jazz_wax_results else 0) + \
                      (len(htfv_results) if htfv_results else 0) + \
                      (len(jazz_youtube_results) if jazz_youtube_results else 0)

        html_content = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎷 Latest Jazz Albums</title>

    <!-- Favicon -->
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎷</text></svg>">

    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://jazzbridge.pages.dev/">
    <meta property="og:title" content="🎷 Latest Jazz Albums">
    <meta property="og:description" content="Daily updated collection of new jazz album releases with universal streaming links. Discover ''' + str(total_albums) + ''' albums from All About Jazz, Jazz Profiles, JazzChill, JazzWax, and Hard To Find Vinyls YouTube.">
    <meta property="og:image" content="https://jazzbridge.pages.dev/og-image.png">

    <!-- Twitter -->
    <meta property="twitter:card" content="summary_large_image">
    <meta property="twitter:url" content="https://jazzbridge.pages.dev/">
    <meta property="twitter:title" content="🎷 Latest Jazz Albums">
    <meta property="twitter:description" content="Daily updated collection of new jazz album releases with universal streaming links.">
    <meta property="twitter:image" content="https://jazzbridge.pages.dev/og-image.png">

    <!-- Telegram -->
    <meta name="description" content="Daily updated collection of ''' + str(total_albums) + ''' new jazz albums with universal streaming links.">

    <style>
        :root {
            /* Light theme (day) */
            --bg-primary: #f5f5f5;
            --bg-secondary: #ffffff;
            --bg-card: #ffffff;
            --text-primary: #1a1a1a;
            --text-secondary: #666;
            --text-muted: #999;
            --border-color: #e0e0e0;
            --shadow: rgba(0, 0, 0, 0.1);
        }

        body.dark-theme {
            /* Dark theme (night) */
            --bg-primary: #1a1a1a;
            --bg-secondary: #2a2a2a;
            --bg-card: #2a2a2a;
            --text-primary: #ffffff;
            --text-secondary: #888;
            --text-muted: #666;
            --border-color: #333;
            --shadow: rgba(0, 0, 0, 0.3);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            padding: 20px;
            transition: background-color 0.3s ease, color 0.3s ease;
        }

        header {
            text-align: center;
            margin-bottom: 30px;
        }

        h1 {
            font-size: 2em;
            margin-bottom: 10px;
        }

        h2 {
            font-size: 1.5em;
            margin: 40px 0 20px 0;
            text-align: center;
            color: var(--text-primary);
        }

        h2:first-of-type {
            margin-top: 0;
        }

        h2 a {
            color: var(--text-primary);
            text-decoration: none;
            transition: opacity 0.3s ease;
        }

        h2 a:hover {
            opacity: 0.7;
        }

        .update-time {
            color: var(--text-secondary);
            font-size: 0.9em;
        }

        .theme-toggle {
            position: fixed;
            top: 20px;
            right: 20px;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 50px;
            padding: 8px 16px;
            cursor: pointer;
            font-size: 1.2em;
            box-shadow: 0 2px 8px var(--shadow);
            transition: all 0.3s ease;
            z-index: 1000;
        }

        .theme-toggle:hover {
            transform: scale(1.1);
        }

        .section-container {
            max-width: 1400px;
            margin: 0 auto;
        }

        .grid-container {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            max-width: 1400px;
            margin: 0 auto;
        }

        .album-embed {
            aspect-ratio: 480/199;
            width: 100%;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 6px var(--shadow);
            background: var(--bg-card);
            transition: box-shadow 0.3s ease;
        }

        .album-embed iframe {
            width: 100%;
            height: 100%;
            border: none;
        }

        .placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
            font-size: 0.9em;
            text-align: center;
            padding: 20px;
        }

        .placeholder-icon {
            font-size: 2em;
            margin-bottom: 10px;
        }

        footer {
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid var(--border-color);
            color: var(--text-muted);
            font-size: 0.85em;
        }

        footer a {
            color: var(--text-secondary);
            text-decoration: none;
        }

        footer a:hover {
            color: var(--text-primary);
        }

        /* Responsive design */
        @media (max-width: 1200px) {
            .grid-container {
                grid-template-columns: repeat(3, 1fr);
            }
        }

        @media (max-width: 900px) {
            .grid-container {
                grid-template-columns: repeat(2, 1fr);
            }

            h1 {
                font-size: 1.5em;
            }
        }

        @media (max-width: 600px) {
            .grid-container {
                grid-template-columns: 1fr;
            }

            h1 {
                font-size: 1.2em;
            }

            .theme-toggle {
                top: 10px;
                right: 10px;
                padding: 6px 12px;
                font-size: 1em;
            }
        }
    </style>
    <script>
        // Auto theme switching based on local time
        function setThemeByTime() {
            const hour = new Date().getHours();
            // Dark theme between 6 PM (18:00) and 6 AM (6:00)
            const isDarkTime = hour >= 18 || hour < 6;

            // Check if user has manually set a preference
            const savedTheme = localStorage.getItem('theme');

            if (savedTheme) {
                // User preference takes priority
                document.body.className = savedTheme === 'dark' ? 'dark-theme' : '';
                updateThemeToggle(savedTheme === 'dark');
            } else {
                // Auto-set based on time
                document.body.className = isDarkTime ? 'dark-theme' : '';
                updateThemeToggle(isDarkTime);
            }
        }

        function toggleTheme() {
            const isDark = document.body.classList.contains('dark-theme');
            const newTheme = isDark ? 'light' : 'dark';

            document.body.className = newTheme === 'dark' ? 'dark-theme' : '';
            localStorage.setItem('theme', newTheme);
            updateThemeToggle(newTheme === 'dark');
        }

        function updateThemeToggle(isDark) {
            const toggle = document.getElementById('theme-toggle');
            if (toggle) {
                toggle.textContent = isDark ? '☀️' : '🌙';
                toggle.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
            }
        }

        // Set theme on page load
        setThemeByTime();
    </script>
</head>
<body>
    <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()" title="Toggle theme">🌙</button>
    <header>
        <h1>🎷 Latest Jazz Albums</h1>
        <p class="update-time">Updated: ''' + datetime.now().strftime('%B %d, %Y at %I:%M %p') + '''</p>
    </header>

    <div class="section-container">
        <h2><a href="https://www.allaboutjazz.com/" target="_blank">🎺 All About Jazz</a></h2>
        <div class="grid-container">
'''

        # Add All About Jazz album embeds or placeholders
        for artist, album, album_link, apple_link, date in results:
            if album_link:
                # Album found - show embed
                encoded_url = quote(album_link)
                html_content += f'''        <div class="album-embed">
            <iframe src="https://song.link/embed?url={encoded_url}"
                    frameborder="0"
                    allowtransparency
                    allowfullscreen
                    title="{artist} - {album}">
            </iframe>
        </div>
'''
            else:
                # Album not found - show placeholder with artist and album name
                html_content += f'''        <div class="album-embed placeholder">
            <div class="placeholder-icon">🎵</div>
            <div><strong>{artist}</strong></div>
            <div style="font-size: 0.85em; margin-top: 5px;">{album}</div>
            <div style="font-size: 0.75em; color: #555; margin-top: 10px;">Not available on streaming</div>
        </div>
'''

        html_content += '''        </div>
'''

        # Add Jazz Profiles section if results provided
        if jazz_profiles_results:
            html_content += '''
        <h2><a href="https://jazzprofiles.blogspot.com/" target="_blank">🎹 Jazz Profiles</a></h2>
        <div class="grid-container">
'''
            for artist, album, album_link, apple_link, date in jazz_profiles_results:
                if album_link:
                    # Album found - show embed
                    encoded_url = quote(album_link)
                    html_content += f'''        <div class="album-embed">
            <iframe src="https://song.link/embed?url={encoded_url}"
                    frameborder="0"
                    allowtransparency
                    allowfullscreen
                    title="{artist} - {album}">
            </iframe>
        </div>
'''
                else:
                    # Album not found - show placeholder
                    html_content += f'''        <div class="album-embed placeholder">
            <div class="placeholder-icon">🎵</div>
            <div><strong>{artist}</strong></div>
            <div style="font-size: 0.85em; margin-top: 5px;">{album}</div>
            <div style="font-size: 0.75em; color: #555; margin-top: 10px;">Not available on streaming</div>
        </div>
'''
            html_content += '''        </div>
'''

        # Add JazzChill section if results provided
        if jazz_chill_results:
            html_content += '''
        <h2><a href="https://jazzchill.blogspot.com/" target="_blank">🎶 JazzChill</a></h2>
        <div class="grid-container">
'''
            for artist, album, album_link, apple_link, date in jazz_chill_results:
                if album_link:
                    # Album found - show embed
                    encoded_url = quote(album_link)
                    html_content += f'''        <div class="album-embed">
            <iframe src="https://song.link/embed?url={encoded_url}"
                    frameborder="0"
                    allowtransparency
                    allowfullscreen
                    title="{artist} - {album}">
            </iframe>
        </div>
'''
                else:
                    # Album not found - show placeholder
                    html_content += f'''        <div class="album-embed placeholder">
            <div class="placeholder-icon">🎵</div>
            <div><strong>{artist}</strong></div>
            <div style="font-size: 0.85em; margin-top: 5px;">{album}</div>
            <div style="font-size: 0.75em; color: #555; margin-top: 10px;">Not available on streaming</div>
        </div>
'''
            html_content += '''        </div>
'''

        # Add JazzWax section if results provided
        if jazz_wax_results:
            html_content += '''
        <h2><a href="https://jazzwax.com/" target="_blank">🎺 JazzWax</a></h2>
        <div class="grid-container">
'''
            for artist, album, album_link, apple_link, date in jazz_wax_results:
                if album_link:
                    # Album found - show embed
                    encoded_url = quote(album_link)
                    html_content += f'''        <div class="album-embed">
            <iframe src="https://song.link/embed?url={encoded_url}"
                    frameborder="0"
                    allowtransparency
                    allowfullscreen
                    title="{artist} - {album}">
            </iframe>
        </div>
'''
                else:
                    # Album not found - show placeholder
                    html_content += f'''        <div class="album-embed placeholder">
            <div class="placeholder-icon">🎵</div>
            <div><strong>{artist}</strong></div>
            <div style="font-size: 0.85em; margin-top: 5px;">{album}</div>
            <div style="font-size: 0.75em; color: #555; margin-top: 10px;">Not available on streaming</div>
        </div>
'''
            html_content += '''        </div>
'''

        # Add Hard To Find Vinyls YouTube section if results provided
        if htfv_results:
            html_content += '''
        <h2><a href="https://www.youtube.com/@hardtofindvinyls" target="_blank">📺 Hard To Find Vinyls</a></h2>
        <div class="grid-container">
'''
            for artist, album, album_link, apple_link, date in htfv_results:
                if album_link:
                    # Album found - show embed
                    encoded_url = quote(album_link)
                    html_content += f'''        <div class="album-embed">
            <iframe src="https://song.link/embed?url={encoded_url}"
                    frameborder="0"
                    allowtransparency
                    allowfullscreen
                    title="{artist} - {album}">
            </iframe>
        </div>
'''
                else:
                    # Album not found - show placeholder
                    html_content += f'''        <div class="album-embed placeholder">
            <div class="placeholder-icon">🎵</div>
            <div><strong>{artist}</strong></div>
            <div style="font-size: 0.85em; margin-top: 5px;">{album}</div>
            <div style="font-size: 0.75em; color: #555; margin-top: 10px;">Not available on streaming</div>
        </div>
'''
            html_content += '''        </div>
'''

        # Add Jazz YouTube channel section if results provided
        if jazz_youtube_results:
            html_content += '''
        <h2><a href="https://www.youtube.com/channel/UCSa-MrfLJ9epUEITf3xHgKg" target="_blank">💿 Hard To Find Vinyls</a></h2>
        <div class="grid-container">
'''
            for artist, album, album_link, apple_link, date in jazz_youtube_results:
                if album_link:
                    # Album found - show embed
                    encoded_url = quote(album_link)
                    html_content += f'''        <div class="album-embed">
            <iframe src="https://song.link/embed?url={encoded_url}"
                    frameborder="0"
                    allowtransparency
                    allowfullscreen
                    title="{artist} - {album}">
            </iframe>
        </div>
'''
                else:
                    # Album not found - show placeholder
                    html_content += f'''        <div class="album-embed placeholder">
            <div class="placeholder-icon">🎵</div>
            <div><strong>{artist}</strong></div>
            <div style="font-size: 0.85em; margin-top: 5px;">{album}</div>
            <div style="font-size: 0.75em; color: #555; margin-top: 10px;">Not available on streaming</div>
        </div>
'''
            html_content += '''        </div>
'''

        html_content += '''    </div>

    <footer>
        <p>Data from <a href="https://www.allaboutjazz.com/" target="_blank">All About Jazz</a>'''

        if jazz_profiles_results:
            html_content += ''', <a href="https://jazzprofiles.blogspot.com/" target="_blank">Jazz Profiles</a>'''

        if jazz_chill_results:
            html_content += ''', <a href="https://jazzchill.blogspot.com/" target="_blank">JazzChill</a>'''

        if jazz_wax_results:
            html_content += ''', <a href="https://jazzwax.com/" target="_blank">JazzWax</a>'''

        if htfv_results:
            html_content += ''', <a href="https://www.youtube.com/@hardtofindvinyls" target="_blank">Hard To Find Vinyls</a>'''

        if jazz_youtube_results:
            html_content += ''', and <a href="https://www.youtube.com/channel/UCSa-MrfLJ9epUEITf3xHgKg" target="_blank">Hard To Find Vinyls</a>'''

        html_content += ''' |
           Links via <a href="https://album.link" target="_blank">Album.link</a></p>
        <p style="margin-top: 10px;">Generated by GetMusic</p>
    </footer>
</body>
</html>
'''

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # Count how many have links vs placeholders
        aaj_with_links = sum(1 for _, _, link, _, _ in results if link)
        aaj_without_links = len(results) - aaj_with_links

        print(f"HTML output written to: {output_file}")
        print(f"All About Jazz: {aaj_with_links} album embeds and {aaj_without_links} placeholders from {len(results)} total albums")

        if jazz_profiles_results:
            jp_with_links = sum(1 for _, _, link, _, _ in jazz_profiles_results if link)
            jp_without_links = len(jazz_profiles_results) - jp_with_links
            print(f"Jazz Profiles: {jp_with_links} album embeds and {jp_without_links} placeholders from {len(jazz_profiles_results)} total albums")

        if jazz_chill_results:
            jc_with_links = sum(1 for _, _, link, _, _ in jazz_chill_results if link)
            jc_without_links = len(jazz_chill_results) - jc_with_links
            print(f"JazzChill: {jc_with_links} album embeds and {jc_without_links} placeholders from {len(jazz_chill_results)} total albums")

        if jazz_wax_results:
            jw_with_links = sum(1 for _, _, link, _, _ in jazz_wax_results if link)
            jw_without_links = len(jazz_wax_results) - jw_with_links
            print(f"JazzWax: {jw_with_links} album embeds and {jw_without_links} placeholders from {len(jazz_wax_results)} total albums")

        if htfv_results:
            htfv_with_links = sum(1 for _, _, link, _, _ in htfv_results if link)
            htfv_without_links = len(htfv_results) - htfv_with_links
            print(f"Hard To Find Vinyls: {htfv_with_links} album embeds and {htfv_without_links} placeholders from {len(htfv_results)} total albums")

        if jazz_youtube_results:
            jy_with_links = sum(1 for _, _, link, _, _ in jazz_youtube_results if link)
            jy_without_links = len(jazz_youtube_results) - jy_with_links
            print(f"Hard To Find Vinyls: {jy_with_links} album embeds and {jy_without_links} placeholders from {len(jazz_youtube_results)} total albums")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Fetch jazz albums from All About Jazz, Jazz Profiles, JazzChill, JazzWax, Hard To Find Vinyls YouTube, and other YouTube channels, find them on Album.link'
    )
    parser.add_argument(
        '-o', '--output',
        default='jazz_albums.md',
        help='Output file path (default: jazz_albums.md)'
    )
    parser.add_argument(
        '-f', '--format',
        choices=['markdown', 'csv', 'html'],
        default='markdown',
        help='Output format (default: markdown)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--skip-jazz-profiles',
        action='store_true',
        help='Skip fetching from Jazz Profiles (only fetch All About Jazz)'
    )

    args = parser.parse_args()

    # Helper function to fetch from a single source
    def fetch_from_source(fetcher_class, source_name):
        """Fetch albums from a single source."""
        print(f"\n=== Fetching from {source_name} ===")
        fetcher = fetcher_class(verbose=args.verbose)
        results = fetcher.process_feed()

        # Count results
        with_links = sum(1 for _, _, link, _, _ in results if link)
        without_links = len(results) - with_links

        print(f"\n{source_name} - Processed {len(results)} albums:")
        print(f"  - {with_links} found on streaming services")
        print(f"  - {without_links} not found (will show as placeholders)")

        return source_name, results

    # Define all sources to fetch
    sources = [
        (AlbumFetcher, "All About Jazz"),
    ]

    if not args.skip_jazz_profiles:
        sources.extend([
            (JazzProfilesFetcher, "Jazz Profiles"),
            (JazzChillFetcher, "JazzChill"),
            (JazzWaxFetcher, "JazzWax"),
            (HardToFindVinylsFetcher, "Hard To Find Vinyls YouTube"),
            (JazzYouTubeFetcher, "Jazz YouTube Channel"),
        ])

    # Process all sources in parallel
    print(f"\n{'='*60}")
    print(f"Processing {len(sources)} sources in parallel...")
    print(f"{'='*60}")

    results_dict = {}
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        # Submit all fetch tasks
        future_to_source = {
            executor.submit(fetch_from_source, fetcher_class, source_name): source_name
            for fetcher_class, source_name in sources
        }

        # Collect results as they complete
        for future in as_completed(future_to_source):
            source_name = future_to_source[future]
            try:
                name, results = future.result()
                results_dict[name] = results
            except Exception as e:
                print(f"\n❌ Error fetching from {source_name}: {e}")
                results_dict[source_name] = []

    # Extract results for each source
    aaj_results = results_dict.get("All About Jazz", [])
    jp_results = results_dict.get("Jazz Profiles")
    jc_results = results_dict.get("JazzChill")
    jw_results = results_dict.get("JazzWax")
    htfv_results = results_dict.get("Hard To Find Vinyls YouTube")
    jy_results = results_dict.get("Jazz YouTube Channel")

    # Generate output
    if args.format == 'markdown':
        OutputGenerator.generate_markdown(aaj_results, args.output)
        print("\nNote: Markdown format only includes All About Jazz results")
    elif args.format == 'csv':
        OutputGenerator.generate_csv(aaj_results, args.output)
        print("\nNote: CSV format only includes All About Jazz results")
    elif args.format == 'html':
        OutputGenerator.generate_html(aaj_results, args.output,
                                      jazz_profiles_results=jp_results,
                                      jazz_chill_results=jc_results,
                                      jazz_wax_results=jw_results,
                                      htfv_results=htfv_results,
                                      jazz_youtube_results=jy_results)
        print()

    print(f"✓ Successfully completed - output written to {args.output}")


if __name__ == '__main__':
    try:
        main()
        print("✓ Script completed successfully (exit code 0)")
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
