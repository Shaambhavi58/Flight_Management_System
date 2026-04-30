"""
services/auth_service.py
=========================
AuthService — All authentication and user management business logic.
Handles: password hashing, JWT creation/decoding, user registration,
login verification, profile updates, password reset, and deactivation.
"""

import os
import bcrypt                         # for secure password hashing (adaptive bcrypt)
import jwt                            # PyJWT — encodes/decodes signed JWT tokens
from datetime import datetime, timedelta
from dotenv import load_dotenv

from core.database import DatabaseManager  # singleton DB engine and session factory
from models.models import UserModel         # SQLAlchemy ORM model for the users table
from models.schemas import UserSerializer   # converts ORM objects to plain response dicts
from services.email_service import EmailService  # sends credential emails after registration

# Load environment variables from .env file
load_dotenv()


class AuthService:
    """
    Handles all authentication and user management operations.
    Uses bcrypt for password security and PyJWT for stateless session tokens.
    """

    def __init__(self):
        self._db            = DatabaseManager()   # shared DB manager (singleton)
        self._email_service = EmailService()      # used to send credential emails

        # Load JWT configuration from environment — never hardcode these in production
        self._secret       = os.getenv("JWT_SECRET", "flight-mgmt-secret-key-2026")
        self._algorithm    = os.getenv("JWT_ALGORITHM", "HS256")
        self._expiry_hours = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

    # ── Password Utilities ─────────────────────────────────────────────────────

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a plaintext password using bcrypt with a random salt.
        bcrypt automatically embeds the salt in the resulting hash string.
        Never store plaintext passwords — always call this before saving.
        """
        return bcrypt.hashpw(
            password.encode("utf-8"),   # encode to bytes before hashing
            bcrypt.gensalt()            # generate a new random salt each time
        ).decode("utf-8")               # decode back to string for DB storage

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """
        Verify a plaintext password against a stored bcrypt hash.
        bcrypt.checkpw() extracts the embedded salt from `hashed` and re-hashes
        the candidate password for constant-time comparison.
        """
        return bcrypt.checkpw(
            password.encode("utf-8"),   # encode candidate password to bytes
            hashed.encode("utf-8")      # encode stored hash to bytes
        )

    # ── JWT Utilities ──────────────────────────────────────────────────────────

    def create_token(self, user_id: int, username: str, role: str, airport_id: int = None) -> str:
        """
        Create a signed JWT token for a successfully authenticated user.
        The payload embeds user_id, role, and airport_id so downstream
        dependencies don't need to re-query the DB on every request.
        """
        payload = {
            "user_id":    user_id,                                       # DB primary key
            "username":   username,                                      # display name
            "role":       role,                                          # admin / staff / viewer
            "airport_id": airport_id,                                    # None for admin
            "exp":        datetime.utcnow() + timedelta(hours=self._expiry_hours),  # expiry timestamp
            "iat":        datetime.utcnow(),                             # issued-at timestamp
        }
        # Sign and encode the payload — returns a compact JWT string
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict:
        """
        Decode and verify a JWT token.
        Returns the payload dict on success, or None if the token is
        expired or has been tampered with.
        """
        try:
            return jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError:
            return None  # token lifetime exceeded — user must log in again
        except jwt.InvalidTokenError:
            return None  # signature invalid or payload malformed

    # ── Authentication ─────────────────────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> dict:
        """
        Verify credentials and return an access token + user info if valid.
        Returns None on any failure (wrong password, user not found, deactivated).
        Returning None instead of raising exceptions prevents timing attacks
        that could reveal whether a username exists.
        """
        with self._db.session_scope() as session:
            # Look up user by username (case-sensitive)
            user = session.query(UserModel).filter_by(username=username).first()

            if not user:
                return None  # username does not exist — return generic failure

            # Block deactivated accounts even if the password is correct
            if hasattr(user, "is_active") and user.is_active is False:
                return None

            # Verify the provided password against the stored bcrypt hash
            if not self.verify_password(password, user.password_hash):
                return None  # wrong password

            # All checks passed — generate a signed JWT for this session
            token = self.create_token(user.id, user.username, user.role, user.airport_id)

            return {
                "access_token": token,          # client stores this and sends in Authorization header
                "token_type":   "bearer",
                "id":           user.id,
                "role":         user.role,
                "full_name":    user.full_name,
                "username":     user.username,
                "airport_id":   user.airport_id,  # None for admin
            }

    def get_current_user(self, token: str) -> dict:
        """
        Validate a JWT and return the live user record from the database.
        Called on every authenticated request via the get_current_user dependency.
        Queries the DB (not just the token) so deactivated users are blocked immediately
        without waiting for the token to expire.
        """
        payload = self.decode_token(token)  # returns None if token is invalid/expired

        if not payload:
            return None  # invalid token — caller raises HTTP 401

        with self._db.session_scope() as session:
            # Re-query DB to catch accounts that were deactivated after token was issued
            user = session.query(UserModel).filter_by(id=payload["user_id"]).first()

            if not user:
                return None  # user was deleted after token was issued

            # Enforce deactivation — is_active=False blocks even valid tokens
            if hasattr(user, "is_active") and user.is_active is False:
                return None

            # Return serialized user dict (id, username, role, airport_id, etc.)
            return UserSerializer.orm_to_response(user)

    # ── User Management ────────────────────────────────────────────────────────

    def register_user(
        self,
        admin_id: int,
        username: str,
        password: str,
        email: str,
        full_name: str,
        role: str,
        airport_id: int = None,
    ) -> dict:
        """
        Register a new user in the database and send them their credentials by email.
        Raises ValueError for:
          - Missing airport_id for staff/viewer roles
          - Duplicate username
          - Non-existent airport_id
        """
        # Staff and viewers are scoped to a specific airport — airport_id is mandatory
        if role in ("staff", "viewer") and not airport_id:
            raise ValueError(f"airport_id is required when registering a '{role}' user.")

        # Admin accounts are never tied to an airport — clear any accidentally provided value
        if role == "admin":
            airport_id = None

        with self._db.session_scope() as session:
            # Check for username uniqueness before attempting insertion
            existing = session.query(UserModel).filter_by(username=username).first()

            if existing:
                raise ValueError(f"Username '{username}' is already taken.")

            # Validate that the provided airport_id actually exists in the airports table
            if airport_id is not None:
                from models.models import AirportModel

                airport = session.query(AirportModel).filter_by(id=airport_id).first()
                if not airport:
                    raise ValueError(f"Airport with id={airport_id} does not exist.")

            # Build the ORM user object — password is hashed here, never stored plaintext
            user = UserModel(
                username=username,
                password_hash=self.hash_password(password),  # bcrypt hash
                email=email,
                full_name=full_name,
                role=role,
                airport_id=airport_id,   # None for admin
                created_by=admin_id,     # audit trail — who created this account
            )

            session.add(user)   # stage the INSERT
            session.flush()     # flush to get the auto-generated user.id before commit

            # Serialize while still inside the session (ORM object expires after commit)
            result = UserSerializer.orm_to_response(user)

        # Send welcome email with credentials OUTSIDE the session block
        # (email sending should not hold a DB connection open)
        self._email_service.send_credentials_email(
            to_email=email,
            full_name=full_name,
            username=username,
            password=password,   # plaintext — only sent once in the welcome email
            role=role,
        )

        return result  # serialized user dict for the API response

    def get_all_users(self) -> list:
        """Return all users in the system (admin-only utility)."""
        with self._db.session_scope() as session:
            users = session.query(UserModel).all()
            # Serialize each ORM object to a dict before the session closes
            return [UserSerializer.orm_to_response(u) for u in users]

    def delete_user(self, user_id: int) -> bool:
        """
        Permanently delete a user by ID.
        Returns True if deleted, False if user not found.
        """
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                return False  # nothing to delete

            session.delete(user)  # marks the row for DELETE on commit

        return True

    def update_user(self, user_id: int, data: dict, current_user_id: int) -> dict:
        """
        Update a user's profile fields.
        Enforces: admin cannot change their own role to prevent privilege escalation lockout.
        Only fields present in `data` are updated — missing fields are left unchanged.
        """
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            # Extract individual fields from the update payload
            role       = data.get("role")
            airport_id = data.get("airport_id")
            full_name  = data.get("full_name")
            email      = data.get("email")

            # Apply updates only for fields that were actually provided
            if full_name:
                user.full_name = full_name  # update display name

            if email:
                user.email = email  # update contact email

            if role:
                # Prevent admin from accidentally changing their own role
                if user_id == current_user_id and role != user.role:
                    raise ValueError("Admin cannot change their own role")
                user.role = role

            # airport_id logic:
            # - admin users always have airport_id=None regardless of what was sent
            # - for staff/viewer, only update if the key was explicitly included in data
            if user.role == "admin":
                user.airport_id = None          # admins are not scoped to any airport
            elif "airport_id" in data:
                user.airport_id = airport_id    # update staff/viewer airport assignment

        return {"message": "User updated"}

    def reset_password(self, user_id: int, password: str) -> dict:
        """
        Replace a user's password with a new bcrypt hash.
        The plaintext `password` is hashed before storage — never saved raw.
        """
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            # Hash the new password and overwrite the stored hash
            user.password_hash = self.hash_password(password)

        return {"message": "Password updated"}

    def deactivate_user(self, user_id: int) -> dict:
        """
        Soft-delete a user by setting is_active=False.
        The account remains in the DB for audit purposes but login is blocked.
        """
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            user.is_active = False  # blocks authentication without deleting the record

        return {"message": "User deactivated"}

    def activate_user(self, user_id: int) -> dict:
        """Re-enable a previously deactivated user account."""
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            user.is_active = True  # restores login capability

        return {"message": "User activated"}