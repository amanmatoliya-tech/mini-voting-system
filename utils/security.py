from werkzeug.security import generate_password_hash, check_password_hash

def hash_password(password: str) -> str:
    """Returns a secure password hash."""
    return generate_password_hash(password)

def verify_password(password_hash: str, password: str) -> bool:
    """Checks if password matches the hash."""
    return check_password_hash(password_hash, password)
