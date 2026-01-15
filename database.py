import sqlite3
import os
from datetime import datetime
import hashlib
import re

DB_PATH = os.path.join(os.path.dirname(__file__), 'spotified.db')

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn

def init_db():
    """Initialize the database with tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            avatar TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Songs table (uploaded by users)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT,
            duration TEXT,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            size INTEGER,
            cover_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # Add cover_url column if it doesn't exist (for existing databases)
    try:
        cursor.execute('ALTER TABLE songs ADD COLUMN cover_url TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Playlists table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            image TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # Playlist-Song relationship (many-to-many)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playlist_songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            song_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
            FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE,
            UNIQUE(playlist_id, song_id)
        )
    ''')
    
    # User preferences/settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            theme TEXT DEFAULT 'dark',
            notifications BOOLEAN DEFAULT 1,
            private_account BOOLEAN DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    conn.close()

# User functions
def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(name, email, password):
    """Create a new user"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        hashed_password = hash_password(password)
        avatar = f"https://ui-avatars.com/api/?name={name.replace(' ', '+')}"
        
        cursor.execute('''
            INSERT INTO users (name, email, password, avatar)
            VALUES (?, ?, ?, ?)
        ''', (name, email, hashed_password, avatar))
        
        user_id = cursor.lastrowid
        
        # Create user settings entry
        cursor.execute('''
            INSERT INTO user_settings (user_id)
            VALUES (?)
        ''', (user_id,))
        
        conn.commit()
        
        create_playlist(user_id, "My Favorites", "A playlist of my favorite songs")
        create_playlist(user_id, "All Songs", "All the songs uploaded")
        
        return {
            "id": user_id,
            "name": name,
            "email": email,
            "avatar": avatar
        }
    except sqlite3.IntegrityError as e:
        conn.close()
        if "UNIQUE constraint failed: users.email" in str(e):
            return None  # Email already exists
        raise
    finally:
        conn.close()

def get_user_by_email(email):
    """Get user by email"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def get_user_by_id(user_id):
    """Get user by ID"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, name, email, avatar, created_at FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def verify_user_password(email, password):
    """Verify user password"""
    user = get_user_by_email(email)
    if user:
        hashed = hash_password(password)
        return user['password'] == hashed
    return False

# Song functions
def add_song(user_id, title, artist, album, duration, file_name, file_path, size, cover_url=None):
    """Add a new song to the database"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO songs (user_id, title, artist, album, duration, file_name, file_path, size, cover_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, title, artist, album, duration, file_name, file_path, size, cover_url))
        
        song_id = cursor.lastrowid
        
        conn.commit()
        
        add_song_to_playlist(get_user_playlists(user_id)[1]['id'], song_id, user_id)
        
        return {
            "id": song_id,
            "user_id": user_id,
            "title": title,
            "artist": artist,
            "album": album,
            "duration": duration,
            "file_name": file_name,
            "file_path": file_path,
            "size": size,
            "cover_url": cover_url
        }
    finally:
        conn.close()

def get_user_songs(user_id):
    """Get all songs for a specific user"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_id, title, artist, album, duration, file_name, file_path, size, cover_url, created_at
        FROM songs
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_song_by_id(song_id):
    """Get a specific song by ID"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM songs WHERE id = ?
    ''', (song_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def get_all_user_songs(exclude_user_id=None):
    """Get all songs from all users (for discovery)"""
    conn = get_db()
    cursor = conn.cursor()
    
    if exclude_user_id:
        cursor.execute('''
            SELECT id, user_id, title, artist, album, duration, created_at
            FROM songs
            WHERE user_id != ?
            ORDER BY created_at DESC
        ''', (exclude_user_id,))
    else:
        cursor.execute('''
            SELECT id, user_id, title, artist, album, duration, created_at
            FROM songs
            ORDER BY created_at DESC
        ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def delete_song(song_id, user_id):
    """Delete a song (only if user owns it)"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Verify ownership
    cursor.execute('SELECT file_path FROM songs WHERE id = ? AND user_id = ?', (song_id, user_id))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return False
    
    file_path = row[0]
    
    # Delete from database
    cursor.execute('DELETE FROM songs WHERE id = ? AND user_id = ?', (song_id, user_id))
    conn.commit()
    conn.close()
    
    # Delete file from disk
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")
    
    return True

# Playlist functions
def create_playlist(user_id, name, description="", image=None):
    """Create a new playlist"""
    conn = get_db()
    cursor = conn.cursor()
    
    if image is None:
        image = f"https://ui-avatars.com/api/?name={name.replace(' ', '+')}&size=36&background=random"
    
    cursor.execute('''
        INSERT INTO playlists (user_id, name, description, image)
        VALUES (?, ?, ?, ?)
    ''', (user_id, name, description, image))
    
    playlist_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return {
        "id": playlist_id,
        "user_id": user_id,
        "name": name,
        "description": description,
        "image": image
    }

def get_user_playlists(user_id):
    """Get all playlists for a user"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_id, name, description, image, created_at
        FROM playlists
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_playlist_by_id(playlist_id):
    """Get a specific playlist with its songs"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_id, name, description, image, created_at
        FROM playlists
        WHERE id = ?
    ''', (playlist_id,))
    
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return None
    
    playlist = dict(row)
    
    # Get songs in this playlist
    cursor.execute('''
        SELECT s.id, s.user_id, s.title, s.artist, s.album, s.duration, s.file_name, s.file_path, s.size, s.cover_url, s.created_at
        FROM songs s
        JOIN playlist_songs ps ON s.id = ps.song_id
        WHERE ps.playlist_id = ?
        ORDER BY ps.added_at DESC
    ''', (playlist_id,))
    
    songs = [dict(row) for row in cursor.fetchall()]
    playlist['songs'] = songs
    
    conn.close()
    return playlist

def add_song_to_playlist(playlist_id, song_id, user_id):
    """Add a song to a playlist (verify user owns playlist)"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Verify user owns the playlist
    cursor.execute('SELECT user_id FROM playlists WHERE id = ?', (playlist_id,))
    row = cursor.fetchone()
    
    if not row or row[0] != user_id:
        conn.close()
        return False
    
    try:
        cursor.execute('''
            INSERT INTO playlist_songs (playlist_id, song_id)
            VALUES (?, ?)
        ''', (playlist_id, song_id))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # Song already in playlist
        conn.close()
        return False

def remove_song_from_playlist(playlist_id, song_id, user_id):
    """Remove a song from a playlist (verify user owns playlist)"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Verify user owns the playlist
    cursor.execute('SELECT user_id FROM playlists WHERE id = ?', (playlist_id,))
    row = cursor.fetchone()
    
    if not row or row[0] != user_id:
        conn.close()
        return False
    
    cursor.execute('''
        DELETE FROM playlist_songs
        WHERE playlist_id = ? AND song_id = ?
    ''', (playlist_id, song_id))
    
    conn.commit()
    conn.close()
    return True

def delete_playlist(playlist_id, user_id):
    """Delete a playlist (only if user owns it)"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM playlists
        WHERE id = ? AND user_id = ?
    ''', (playlist_id, user_id))
    
    conn.commit()
    conn.close()
    return cursor.rowcount > 0

# Initialize database on import
if not os.path.exists(DB_PATH):
    init_db()
