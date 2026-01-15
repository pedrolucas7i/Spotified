"""
Metadata and cover art extraction from audio files
"""

import os
import base64
import requests
from pathlib import Path

def extract_cover_from_file(file_path):
    """
    Extract cover art from audio file.
    Supports: MP3, FLAC, M4A, OGG
    """
    try:
        from mutagen.mp3 import MP3
        from mutagen.flac import FLAC
        from mutagen.mp4 import MP4
        from mutagen.oggvorbis import OggVorbis
    except ImportError:
        print("Warning: mutagen not installed. Install with: pip install mutagen")
        return None
    
    file_ext = Path(file_path).suffix.lower()
    
    try:
        if file_ext == '.mp3':
            audio = MP3(file_path)
            # Look for APIC frames (attached picture)
            for tag in audio.keys():
                if tag.startswith('APIC'):
                    return audio[tag].data
        
        elif file_ext == '.flac':
            audio = FLAC(file_path)
            if audio.pictures:
                return audio.pictures[0].data
        
        elif file_ext in ['.m4a', '.mp4']:
            audio = MP4(file_path)
            if 'covr' in audio:
                return audio['covr'][0]
        
        elif file_ext in ['.ogg', '.oga']:
            audio = OggVorbis(file_path)
            if 'metadata_block_picture' in audio:
                # OGG stores pictures as base64-encoded FLAC metadata blocks
                return audio['metadata_block_picture'][0]
    
    except Exception as e:
        print(f"Error extracting cover from {file_path}: {e}")
    
    return None


def save_cover_art(cover_data, song_id):
    """
    Save extracted cover art to uploads folder and return the path
    """
    if not cover_data:
        return None
    
    try:
        upload_folder = os.path.join(os.path.dirname(__file__), 'uploads', 'covers')
        os.makedirs(upload_folder, exist_ok=True)
        
        cover_path = os.path.join(upload_folder, f'{song_id}_cover.jpg')
        
        with open(cover_path, 'wb') as f:
            f.write(cover_data)
        
        # Return relative URL path for web access
        return f'/uploads/covers/{song_id}_cover.jpg'
    except Exception as e:
        print(f"Error saving cover art: {e}")
        return None


def fetch_cover_from_internet(title, artist):
    """
    Fetch album cover from external service if not found locally
    Uses Last.fm API (free, no key required for basic search)
    """
    try:
        # Using Last.fm API (no API key required for album.search)
        url = 'https://www.last.fm/music/search'
        params = {
            'q': f'{artist} {title}',
            'type': 'album'
        }
        
        # Alternative: Use a public album art API
        # Try iTunes API first (simple, no key required)
        itunes_url = 'https://itunes.apple.com/search'
        itunes_params = {
            'term': f'{artist} {title}',
            'entity': 'album',
            'limit': 1
        }
        
        response = requests.get(itunes_url, params=itunes_params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('results') and len(data['results']) > 0:
                # Get the album artwork URL
                artwork_url = data['results'][0].get('artworkUrl100')
                if artwork_url:
                    # Replace size parameter to get larger image
                    artwork_url = artwork_url.replace('100x100', '500x500')
                    return artwork_url
        
        return None
    
    except Exception as e:
        print(f"Error fetching cover from internet: {e}")
        return None


def get_or_create_cover_url(file_path, title, artist, song_id):
    """
    Get cover URL: first try to extract from file, then fetch from internet
    """
    # Try to extract from file
    cover_data = extract_cover_from_file(file_path)
    if cover_data:
        cover_url = save_cover_art(cover_data, song_id)
        if cover_url:
            return cover_url
    
    # If no local cover, try to fetch from internet
    cover_url = fetch_cover_from_internet(title, artist)
    return cover_url


def extract_metadata(file_path):
    """
    Extract all metadata from audio file (title, artist, album, duration)
    """
    try:
        from tinytag import TinyTag
        tag = TinyTag.get(file_path, tags=True, duration=True)
        
        return {
            'title': tag.title or 'Unknown Title',
            'artist': tag.artist or 'Unknown Artist',
            'album': tag.album or 'Unknown Album',
            'duration': str(int(tag.duration)) if tag.duration else '0'
        }
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return {
            'title': 'Unknown Title',
            'artist': 'Unknown Artist',
            'album': 'Unknown Album',
            'duration': '0'
        }
