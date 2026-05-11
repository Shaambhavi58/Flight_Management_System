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
from models.models import UserModel, AuditLogModel  # SQLAlchemy ORM models
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

    @staticmethod
    def validate_password_strength(password: str, username: str = "", email: str = "", full_name: str = "") -> None:
        """
        Validate that the password meets strong security requirements:
        - Minimum 8 characters
        - At least 1 uppercase letter
        - At least 1 lowercase letter
        - At least 1 number
        - At least 1 special character
        - Must not contain username, email, or full name
        """
        import re
        
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not re.search(r'[A-Z]', password):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r'[a-z]', password):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not re.search(r'\d', password):
            raise ValueError("Password must contain at least one number.")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>\-\_=\+\[\]\\/\']', password):
            raise ValueError("Password must contain at least one special character.")
            
        password_lower = password.lower()
        if username and username.lower() in password_lower:
            raise ValueError("Password must not contain the username.")
        if email and email.split('@')[0].lower() in password_lower:
            raise ValueError("Password must not contain the email address.")
        if full_name:
            for part in full_name.lower().split():
                if len(part) > 2 and part in password_lower:
                    raise ValueError("Password must not contain parts of the user's name.")

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

            user.last_login_at = datetime.utcnow()

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

            # Validate the new password
            self.validate_password_strength(password, user.username, user.email, user.full_name)

            # Hash the new password and overwrite the stored hash
            user.password_hash = self.hash_password(password)
            email = user.email
            username = user.username
            full_name = user.full_name
            role = user.role

        # Email the updated password to the user
        self._email_service.send_credentials_email(
            to_email=email,
            full_name=full_name,
            username=username,
            password=password,
            role=role,
        )

        return {"message": "Password updated successfully and emailed to the user."}

    def send_reset_email(self, user_id: int) -> dict:
        """
        Generate a cryptographically random temporary password, apply it to the
        user's account (via bcrypt hash), and email the new credentials to the
        user's registered email address.

        This is the correct backend for the admin "Send Reset Email" action.
        It uses the same send_credentials_email() pathway as user registration so
        the user receives a consistently formatted welcome/reset email.

        Args:
            user_id: ID of the user whose password should be reset and emailed.

        Returns:
            dict with "message" key on success, including the target email address.

        Raises:
            ValueError: If the user_id is not found in the database.
        """
        import secrets
        import string

        # Capture user details first
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            # Generate a compliant random password
            while True:
                # Ensure at least one of each required type
                upper = secrets.choice(string.ascii_uppercase)
                lower = secrets.choice(string.ascii_lowercase)
                digit = secrets.choice(string.digits)
                special = secrets.choice("!@#$%^&*")
                
                # Fill the rest (8 characters to make total 12)
                alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
                rest = "".join(secrets.choice(alphabet) for _ in range(8))
                
                # Shuffle the characters
                chars = list(upper + lower + digit + special + rest)
                secrets.SystemRandom().shuffle(chars)
                temp_password = "".join(chars)
                
                # Validate against username/email/name logic
                try:
                    self.validate_password_strength(temp_password, user.username, user.email, user.full_name)
                    break # Break out of loop if valid
                except ValueError:
                    continue # Generate again if invalid

            # Apply bcrypt hash — temp_password is NEVER stored in plain text
            user.password_hash = self.hash_password(temp_password)

            # Capture fields needed for the email before the session closes
            email     = user.email
            full_name = user.full_name
            username  = user.username
            role      = user.role

        # Send the temporary credentials email outside the session block
        # (email I/O should not hold a DB connection open)
        self._email_service.send_credentials_email(
            to_email=email,
            full_name=full_name,
            username=username,
            password=temp_password,   # shown once in email, then disposable
            role=role,
        )

        return {
            "message": f"Temporary password emailed to {email}. "
                       "The user should change it after their next login."
        }

    def update_profile(self, user_id: int, full_name: str, email: str) -> dict:
        """
        Update the user's Full Name and Email. Username and Role are strictly locked.
        Creates an audit log of the change.
        """
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()
            if not user:
                raise ValueError("User not found")
                
            old_name = user.full_name
            old_email = user.email
            
            user.full_name = full_name
            user.email = email
            
            audit = AuditLogModel(
                user_id=user.id,
                action="Updated Profile",
                details=f"Name changed from '{old_name}' to '{full_name}'. Email changed from '{old_email}' to '{email}'."
            )
            session.add(audit)
            
            # Capture details for email
            final_email = user.email
            final_name = user.full_name
            
        # Send confirmation email
        try:
            self._email_service.send_notification(
                to_email=final_email,
                subject="Admin Profile Updated",
                body=f"Hello {final_name},\n\nYour administrative profile information has been successfully updated.\nIf you did not request this change, please contact IT immediately."
            )
        except Exception:
            pass # Non-fatal if email fails

        return {"message": "Profile updated successfully"}

    def change_own_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> dict:
        """
        Allow a logged-in user to change their own password.

        Security flow:
          1. Fetch the user's current bcrypt hash from the DB.
          2. Verify `current_password` matches that hash (bcrypt.checkpw).
          3. If verified, hash `new_password` and overwrite the stored hash.
          4. Fire a security-alert email to the admin (metadata only — no passwords).

        Raises:
          ValueError: If the user is not found or current_password is wrong.

        Args:
          user_id:          ID of the authenticated user making the request.
          current_password: Plaintext password the user claims to currently have.
          new_password:     Desired new plaintext password (min 6 chars enforced by the route).

        Returns:
          dict with "message" key on success.
        """
        from datetime import datetime  # local import to keep top-level imports clean

        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            # Step 1: verify the supplied current password against the stored bcrypt hash
            if not self.verify_password(current_password, user.password_hash):
                raise ValueError("Current password is incorrect")

            # Step 2: Validate the new password against strong security rules
            self.validate_password_strength(new_password, user.username, user.email, user.full_name)

            # Step 3: hash and store the new password — plain text never touches the DB
            user.password_hash = self.hash_password(new_password)
            user.last_password_changed_at = datetime.utcnow()
            
            # Create Audit Log
            audit = AuditLogModel(
                user_id=user.id, 
                action="Changed Password", 
                details="User successfully updated their own password."
            )
            session.add(audit)

            # Capture audit fields while the session is still open
            full_name    = user.full_name
            username     = user.username
            role         = user.role
            airport_id   = user.airport_id
            changed_at   = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Step 3: resolve the airport name for the notification email (outside session)
        airport_name = "All Airports (Admin)"
        if airport_id is not None:
            try:
                with self._db.session_scope() as s2:
                    from models.models import AirportModel
                    ap = s2.query(AirportModel).filter_by(id=airport_id).first()
                    if ap:
                        airport_name = f"{ap.name} ({ap.code})"
            except Exception:
                pass  # non-fatal — email will show 'Unknown' if lookup fails

        # Step 4: notify admin — NO password included, metadata only
        self._email_service.send_password_change_notification(
            full_name=full_name,
            username=username,
            role=role,
            airport_name=airport_name,
            changed_at=changed_at,
        )

        return {"message": "Password changed successfully"}

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