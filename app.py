from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_file
from flask_cors import CORS
from flask_talisman import Talisman
from markupsafe import escape
import re
import os
import time
from werkzeug.utils import secure_filename
from tinytag import TinyTag
from metadata_extractor import get_or_create_cover_url
import sqlite3
from database import (
    init_db, get_user_by_email, get_user_by_id, verify_user_password,
    create_user, add_song, get_user_songs, get_song_by_id, delete_song,
    create_playlist, get_user_playlists, get_playlist_by_id, 
    add_song_to_playlist, remove_song_from_playlist, delete_playlist,
    get_all_user_songs, get_db
)
from auth import (
    generate_token, verify_token, get_token_from_request, require_login,
    require_api_token, verify_user_ownership, get_authenticated_user_id
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SESSION_COOKIE_SECURE'] = False  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True  # No JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB max request size
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')

max_quant_files = 300

# Create uploads folder and covers subdirectory if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'covers'), exist_ok=True)

# Initialize database
init_db()

# CORS Configuration - More restrictive
CORS(app, 
    resources={r"/api/*": {"origins": os.environ.get('ALLOWED_ORIGINS', 'http://localhost:5000').split(',')}},
    supports_credentials=True,
    allow_headers=['Content-Type', 'Authorization'],
    expose_headers=['Content-Type']
)

# Add security headers
Talisman(app, 
    force_https=False,  # Set to True in production
    strict_transport_security=True,
    content_security_policy={
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline' cdn.jsdelivr.net",
        'style-src': "'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com",
        'font-src': "'self' fonts.gstatic.com",
        'img-src': "'self' data: https:",
        'connect-src': "'self'"
    }
)

# File upload configuration
ALLOWED_AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.wav', '.ogg', '.aac'}
ALLOWED_AUDIO_MIMETYPES = {
    'audio/mpeg', 'audio/mp3',
    'audio/flac',
    'audio/mp4', 'audio/x-m4a',
    'audio/wav', 'audio/x-wav',
    'audio/ogg', 'audio/vorbis',
    'audio/aac', 'audio/x-aac'
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB per file
UPLOAD_TIMEOUT_SECONDS = 300  # 5 minutes

# Input validation and sanitization functions
def sanitize_input(input_string, max_length=255):
    """Sanitize user input to prevent XSS"""
    if not isinstance(input_string, str):
        return ""
    # Remove null bytes
    input_string = input_string.replace('\x00', '')
    # Limit length
    input_string = input_string[:max_length]
    # Escape HTML special characters
    return escape(input_string)

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password):
    """Validate password strength"""
    if len(password) < 6:
        return False, "Password must be at least 6 characters"
    if len(password) > 128:
        return False, "Password is too long"
    return True, "Valid"

@app.route("/")
@require_login
def home():
    return render_template("index.html")


@app.route("/music")
@require_login
def music():
    return render_template("music.html")


@app.route("/playlists")
@require_login
def playlists_page():
    return render_template("playlists.html")


@app.route("/profile")
@require_login
def profile():
    return render_template("profile.html")


@app.route("/search")
@require_login
def search_page():
    return render_template("search.html")


# ---------- Cover Image Serving ----------
@app.route("/uploads/covers/<path:filename>", methods=["GET"])
def serve_cover(filename):
    """Serve cover art images"""
    try:
        cover_path = os.path.join(app.config['UPLOAD_FOLDER'], 'covers', filename)
        
        # Validate filename to prevent directory traversal
        if not filename.endswith('_cover.jpg'):
            return jsonify({"error": "Invalid cover file"}), 400
        
        if os.path.exists(cover_path):
            return send_file(cover_path, mimetype='image/jpeg')
        else:
            return jsonify({"error": "Cover not found"}), 404
    except Exception as e:
        print(f"Error serving cover: {e}")
        return jsonify({"error": "Error serving cover"}), 500

# ---------- User Songs ----------
@app.route("/api/user/songs", methods=["GET"])
@require_api_token
def get_user_songs_route():
    """Get all songs for the current authenticated user"""
    try:
        user_id = get_authenticated_user_id()
        
        # Optional: allow querying other users' public songs with different endpoint
        query_user_id = request.args.get('user_id', type=int)
        
        # If querying specific user, verify it's the authenticated user
        if query_user_id and query_user_id != user_id:
            return jsonify({"error": "Unauthorized access"}), 403
        
        songs = get_user_songs(user_id)
        
        return jsonify({
            "user_id": user_id,
            "songs": songs
        })
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/user/songs/add", methods=["POST"])
@require_api_token
def add_user_song():
    """Add a new song to the current user's library (manual entry)"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid request"}), 400
        
        user_id = get_authenticated_user_id()
        title = data.get("title", "").strip()
        artist = data.get("artist", "").strip()
        duration = data.get("duration", "0:00").strip()
        album = data.get("album", "Unknown Album").strip()
        
        if not title or not artist:
            return jsonify({"error": "Title and artist required"}), 400
        
        # Verify user exists
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Sanitize inputs
        title = str(sanitize_input(title, max_length=255))
        artist = str(sanitize_input(artist, max_length=255))
        duration = str(sanitize_input(duration, max_length=10))
        album = str(sanitize_input(album, max_length=255))
        
        # Add song to database (without file since it's manually entered)
        song = add_song(
            user_id=user_id,
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            file_name="manual_entry",
            file_path="",
            size=0
        )
        
        return jsonify({
            "message": "Song added successfully",
            "song": song
        }), 201
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/all-users/songs", methods=["GET"])
def get_all_users_songs_route():
    """Get all songs from all users (for discovery/viewing)"""
    try:
        current_user_id = request.args.get('current_user_id')
        
        if current_user_id:
            current_user_id = int(current_user_id)
        
        # Get all songs from database
        all_songs = get_all_user_songs(exclude_user_id=None)
        
        return jsonify({
            "total": len(all_songs),
            "songs": all_songs
        })
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/user/songs/upload", methods=["POST"])
@require_api_token
def upload_songs():
    """Upload MP3 files with automatic metadata extraction"""
    try:
        data = request.form
        user_id = get_authenticated_user_id()
        
        # Verify user exists
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "No files selected"}), 400
        
        if len(files) > max_quant_files:
            return jsonify({"error": "Maximum 50 files per upload"}), 400
        
        uploaded_songs = []
        
        for file in files:
            if file.filename == '':
                continue
            
            # Security: Validate file extension
            filename_lower = file.filename.lower()
            file_ext = os.path.splitext(filename_lower)[1]
            
            if file_ext not in ALLOWED_AUDIO_EXTENSIONS:
                continue  # Skip invalid files
            
            # Security: Check file size before processing
            file_size = len(file.read())
            file.seek(0)  # Reset file pointer
            
            if file_size > MAX_FILE_SIZE:
                continue  # Skip oversized files
            
            try:
                # Save file with secure random name first
                secure_name = secure_filename(f"{user_id}_{int(time.time())}_{os.urandom(8).hex()}{file_ext}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                file.save(file_path)
                
                # Read metadata from saved file
                audio = TinyTag.get(file_path, tags=True)
                
                title = audio.title or file.filename.replace('.mp3', '').strip()
                artist = audio.artist or "Unknown Artist"
                duration = audio.duration or 0
                album = audio.album or "Unknown Album"
                
                # Format duration as MM:SS
                minutes = int(duration) // 60
                seconds = int(duration) % 60
                duration_str = f"{minutes}:{seconds:02d}"
                
                # Sanitize inputs
                title = str(sanitize_input(title, max_length=255))
                artist = str(sanitize_input(artist, max_length=255))
                album = str(sanitize_input(album, max_length=255))
                
                # Extract or fetch cover art (will be added to DB after song creation)
                cover_url = None
                
                # Add song to database first (to get song_id)
                song = add_song(
                    user_id=user_id,
                    title=title,
                    artist=artist,
                    album=album,
                    duration=duration_str,
                    file_name=secure_name,
                    file_path=file_path,
                    size=file_size,
                    cover_url=cover_url
                )
                
                # Now extract cover art using the song_id
                song_id = song['id']
                cover_url = get_or_create_cover_url(file_path, title, artist, song_id)
                
                # Update song with cover_url if found
                if cover_url:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute('UPDATE songs SET cover_url = ? WHERE id = ?', (cover_url, song_id))
                    conn.commit()
                    conn.close()
                    song['cover_url'] = cover_url
                
                uploaded_songs.append(song)
                
            except Exception as e:
                print(f"Error processing file {file.filename}: {str(e)}")
                continue
        
        if not uploaded_songs:
            return jsonify({"error": "No valid audio files were processed"}), 400
        
        return jsonify({
            "message": f"Successfully uploaded {len(uploaded_songs)} song(s)",
            "songs": uploaded_songs
        }), 201
        
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({"error": "An error occurred during upload"}), 500


# ---------- Search ----------
@app.route("/api/search", methods=["GET"])
@require_api_token
def search():
    """Search for songs by title or artist (user's own songs only)"""
    query = request.args.get("q", "").lower().strip()
    
    if not query:
        return jsonify({"songs": [], "playlists": []}), 200
    
    try:
        # Get authenticated user's songs only (privacy: don't search other users' songs)
        user_id = get_authenticated_user_id()
        user_songs = get_user_songs(user_id)
        
        # Filter songs by title or artist
        song_results = []
        for song in user_songs:
            if query in song.get('title', '').lower() or query in song.get('artist', '').lower():
                song_results.append(song)
        
        # Get user's playlists
        user_playlists = get_user_playlists(user_id)
        
        # Filter playlists by name
        playlist_results = []
        for playlist in user_playlists:
            if query in playlist.get('name', '').lower():
                playlist_results.append(playlist)
        
        return jsonify({
            "songs": song_results[:50],  # Limit results
            "playlists": playlist_results
        }), 200
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


# ---------- Song Streaming ----------
@app.route("/api/songs/<int:song_id>/play", methods=["GET"])
@require_api_token
def stream_song(song_id):
    """Stream a song audio file"""
    try:
        song = get_song_by_id(song_id)
        
        if not song:
            return jsonify({"error": "Song not found"}), 404
        
        file_path = song.get('file_path')
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": "Audio file not found"}), 404
        
        # Return the audio file
        return send_file(file_path, mimetype='audio/mpeg')
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


# ---------- User ----------
@app.route("/api/user", methods=["GET"])
@require_api_token
def get_user():
    """Get current authenticated user information"""
    try:
        user_id = get_authenticated_user_id()
        user = get_user_by_id(user_id)
        
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        return jsonify(user)
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


# ---------- Playlists Management ----------
@app.route("/api/user/playlists", methods=["GET"])
@require_api_token
def user_playlists():
    """Get all playlists for authenticated user"""
    try:
        user_id = get_authenticated_user_id()
        
        # Verify user exists
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        playlists_data = get_user_playlists(user_id)
        
        return jsonify(playlists_data)
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/playlists/<int:playlist_id>", methods=["GET"])
@require_api_token
def get_playlist_route(playlist_id):
    """Get a specific playlist with all its songs"""
    try:
        user_id = get_authenticated_user_id()
        playlist = get_playlist_by_id(playlist_id)
        
        if not playlist:
            return jsonify({"error": "Playlist not found"}), 404
        
        # Verify user owns the playlist
        if playlist['user_id'] != user_id:
            return jsonify({"error": "Unauthorized access"}), 403
        
        return jsonify(playlist)
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/playlists", methods=["POST"])
@require_api_token
def create_playlist_route():
    """Create a new playlist"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid request"}), 400
        
        user_id = get_authenticated_user_id()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        image = data.get('image', None)
        
        if not name:
            return jsonify({"error": "Playlist name required"}), 400
        
        # Verify user exists
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Sanitize inputs
        name = str(sanitize_input(name, max_length=255))
        description = str(sanitize_input(description, max_length=500))
        
        playlist = create_playlist(user_id, name, description, image)
        
        return jsonify({
            "message": "Playlist created successfully",
            "playlist": playlist
        }), 201
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/playlists/<int:playlist_id>/songs", methods=["POST"])
@require_api_token
def add_song_to_playlist_route(playlist_id):
    """Add a song to a playlist"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid request"}), 400
        
        user_id = get_authenticated_user_id()
        song_id = data.get('song_id')
        
        if not song_id:
            return jsonify({"error": "Song ID required"}), 400
        
        song_id = int(song_id)
        
        # Add song to playlist (verifies ownership)
        success = add_song_to_playlist(playlist_id, song_id, user_id)
        
        if not success:
            return jsonify({"error": "Could not add song to playlist or unauthorized"}), 400
        
        return jsonify({
            "message": "Song added to playlist successfully"
        }), 201
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/playlists/<int:playlist_id>/songs/<int:song_id>", methods=["DELETE"])
@require_api_token
def remove_song_from_playlist_route(playlist_id, song_id):
    """Remove a song from a playlist"""
    try:
        user_id = get_authenticated_user_id()
        
        # Remove song from playlist (verifies ownership)
        success = remove_song_from_playlist(playlist_id, song_id, user_id)
        
        if not success:
            return jsonify({"error": "Could not remove song or unauthorized"}), 400
        
        return jsonify({
            "message": "Song removed from playlist successfully"
        })
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/playlists/<int:playlist_id>", methods=["DELETE"])
@require_api_token
def delete_playlist_route(playlist_id):
    """Delete a playlist"""
    try:
        user_id = get_authenticated_user_id()
        
        # Delete playlist (verifies ownership)
        success = delete_playlist(playlist_id, user_id)
        
        if not success:
            return jsonify({"error": "Could not delete playlist or unauthorized"}), 400
        
        return jsonify({
            "message": "Playlist deleted successfully"
        })
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


# ---------- Song Management ----------
@app.route("/api/songs/<int:song_id>", methods=["DELETE"])
@require_api_token
def delete_song_route(song_id):
    """Delete a song"""
    try:
        user_id = get_authenticated_user_id()
        
        # Delete song (verifies ownership)
        success = delete_song(song_id, user_id)
        
        if not success:
            return jsonify({"error": "Could not delete song or unauthorized"}), 400
        
        return jsonify({
            "message": "Song deleted successfully"
        })
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


# ---------- Authentication ----------
@app.route("/api/login", methods=["POST"])
def login():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid request"}), 400
        
        email = data.get("email", "").lower().strip()
        password = data.get("password", "")
        
        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400
        
        # Validate email format
        if not validate_email(email):
            return jsonify({"error": "Invalid email format"}), 400
        
        # Limit password length to prevent abuse
        if len(password) > 128:
            return jsonify({"error": "Invalid credentials"}), 401
        
        # Verify user exists and password is correct
        if not verify_user_password(email, password):
            return jsonify({"error": "Invalid credentials"}), 401
        
        # Get user details
        user = get_user_by_email(email)
        
        # Generate JWT token
        token = generate_token(user["id"])
        
        # Set secure session cookie
        session['user_id'] = user['id']
        session.permanent = True
        
        return jsonify({
            "id": user["id"],
            "name": str(user["name"]),
            "email": str(user["email"]),
            "avatar": str(user.get("avatar", f"https://ui-avatars.com/api/?name={user['name']}")),
            "token": token,
            "created_at": user.get("created_at")
        })
    except Exception as e:
        print(f"Login error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/signup", methods=["POST"])
def signup():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid request"}), 400
        
        fullName = data.get("fullName", "").strip()
        email = data.get("email", "").lower().strip()
        password = data.get("password", "")
        
        if not fullName or not email or not password:
            return jsonify({"error": "Full name, email, and password required"}), 400
        
        # Sanitize inputs
        fullName = str(sanitize_input(fullName, max_length=100))
        email = str(sanitize_input(email, max_length=255))
        
        # Validate email format
        if not validate_email(email):
            return jsonify({"error": "Invalid email format"}), 400
        
        # Validate password strength
        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({"error": message}), 400
        
        # Create new user (database function handles duplicate checking)
        user = create_user(fullName, email, password)
        
        if user is None:
            return jsonify({"error": "Email already registered"}), 409
        
        # Generate JWT token
        token = generate_token(user["id"])
        
        # Set secure session cookie
        session['user_id'] = user['id']
        session.permanent = True
        
        return jsonify({
            "message": "Account created successfully",
            "user": user,
            "token": token
        }), 201
    except Exception as e:
        print(f"Signup error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/api/logout", methods=["POST"])
def logout():
    """Logout endpoint to clear session"""
    try:
        session.clear()
        return jsonify({"message": "Logged out successfully"})
    except Exception as e:
        print(f"Logout error: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500


@app.route("/login")
def page_login():
    return render_template("login.html")


@app.route("/signup")
def page_signup():
    return render_template("signup.html")


# Error Handlers
@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle 413 Request Entity Too Large error"""
    return jsonify({
        "error": "File(s) too large. Maximum total upload size is 2GB. Please upload smaller files or fewer files at once.",
        "code": "FILE_TOO_LARGE"
    }), 413


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
