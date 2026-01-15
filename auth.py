"""
Authentication and authorization utilities for Spotified
"""

import jwt
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
from database import get_user_by_id

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'your-secret-key-change-in-production')
JWT_ALGORITHM = 'HS256'
TOKEN_EXPIRATION_HOURS = 24

def generate_token(user_id):
    """Generate JWT token for user"""
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(hours=TOKEN_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def verify_token(token):
    """Verify JWT token and return user_id if valid"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('user_id')
    except jwt.ExpiredSignatureError:
        return None  # Token expired
    except jwt.InvalidTokenError:
        return None  # Invalid token

def get_token_from_request():
    """Extract JWT token from request (header or cookie)"""
    # Check Authorization header
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    
    # Check query parameter (for file download/streaming)
    token = request.args.get('token')
    if token:
        return token
    
    # Check cookies
    token = request.cookies.get('auth_token')
    if token:
        return token
    
    return None

def require_login(f):
    """Decorator to require authentication on Flask routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # For page routes, check session
        from flask import session, redirect, url_for
        
        if 'user_id' not in session:
            return redirect(url_for('page_login'))
        
        return f(*args, **kwargs)
    return decorated_function

def require_api_token(f):
    """Decorator to require authentication on API endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_request()
        
        if not token:
            return jsonify({"error": "Authentication required", "code": "NO_TOKEN"}), 401
        
        user_id = verify_token(token)
        
        if not user_id:
            return jsonify({"error": "Invalid or expired token", "code": "INVALID_TOKEN"}), 401
        
        # Verify user still exists
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found", "code": "USER_NOT_FOUND"}), 401
        
        # Add user_id to request for use in route
        request.user_id = user_id
        request.user = user
        
        return f(*args, **kwargs)
    return decorated_function

def verify_user_ownership(resource_user_id):
    """Verify that authenticated user owns the resource"""
    if not hasattr(request, 'user_id'):
        return False
    return request.user_id == resource_user_id

def get_authenticated_user_id():
    """Get user_id from authenticated request"""
    if hasattr(request, 'user_id'):
        return request.user_id
    return None
