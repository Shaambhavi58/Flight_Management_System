"""
AuthService — Handles user authentication, JWT tokens, and password hashing.
"""

import os
import bcrypt
import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv

from core.database import DatabaseManager
from models.models import UserModel
from models.schemas import UserSerializer
from services.email_service import EmailService

load_dotenv()


class AuthService:
    def __init__(self):
        self._db = DatabaseManager()
        self._email_service = EmailService()
        self._secret = os.getenv("JWT_SECRET", "flight-mgmt-secret-key-2026")
        self._algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self._expiry_hours = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

    def create_token(self, user_id: int, username: str, role: str, airport_id: int = None) -> str:
        payload = {
            "user_id": user_id,
            "username": username,
            "role": role,
            "airport_id": airport_id,
            "exp": datetime.utcnow() + timedelta(hours=self._expiry_hours),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def authenticate(self, username: str, password: str) -> dict:
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(username=username).first()

            if not user:
                return None

            if hasattr(user, "is_active") and user.is_active is False:
                return None

            if not self.verify_password(password, user.password_hash):
                return None

            token = self.create_token(user.id, user.username, user.role, user.airport_id)

            return {
                "access_token": token,
                "token_type": "bearer",
                "id": user.id,
                "role": user.role,
                "full_name": user.full_name,
                "username": user.username,
                "airport_id": user.airport_id,
            }

    def get_current_user(self, token: str) -> dict:
        payload = self.decode_token(token)

        if not payload:
            return None

        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=payload["user_id"]).first()

            if not user:
                return None

            if hasattr(user, "is_active") and user.is_active is False:
                return None

            return UserSerializer.orm_to_response(user)

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

        if role in ("staff", "viewer") and not airport_id:
            raise ValueError(f"airport_id is required when registering a '{role}' user.")

        if role == "admin":
            airport_id = None

        with self._db.session_scope() as session:
            existing = session.query(UserModel).filter_by(username=username).first()

            if existing:
                raise ValueError(f"Username '{username}' is already taken.")

            if airport_id is not None:
                from models.models import AirportModel

                airport = session.query(AirportModel).filter_by(id=airport_id).first()
                if not airport:
                    raise ValueError(f"Airport with id={airport_id} does not exist.")

            user = UserModel(
                username=username,
                password_hash=self.hash_password(password),
                email=email,
                full_name=full_name,
                role=role,
                airport_id=airport_id,
                created_by=admin_id,
            )

            session.add(user)
            session.flush()

            result = UserSerializer.orm_to_response(user)

        self._email_service.send_credentials_email(
            to_email=email,
            full_name=full_name,
            username=username,
            password=password,
            role=role,
        )

        return result

    def get_all_users(self) -> list:
        with self._db.session_scope() as session:
            users = session.query(UserModel).all()
            return [UserSerializer.orm_to_response(u) for u in users]

    def delete_user(self, user_id: int) -> bool:
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                return False

            session.delete(user)

        return True

    def update_user(self, user_id: int, data: dict, current_user_id: int) -> dict:
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            role = data.get("role")
            airport_id = data.get("airport_id")
            full_name = data.get("full_name")
            email = data.get("email")

            if full_name:
                user.full_name = full_name
            
            if email:
                user.email = email

            if role:
                if user_id == current_user_id and role != user.role:
                    raise ValueError("Admin cannot change their own role")
                user.role = role

            # Update airport ID only if specified. For admins it should be None.
            # But if a user is self-updating as admin, role is admin.
            if user.role == "admin":
                user.airport_id = None
            elif "airport_id" in data:
                user.airport_id = airport_id

        return {"message": "User updated"}

    def reset_password(self, user_id: int, password: str) -> dict:
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            user.password_hash = self.hash_password(password)

        return {"message": "Password updated"}

    def deactivate_user(self, user_id: int) -> dict:
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            user.is_active = False

        return {"message": "User deactivated"}

    def activate_user(self, user_id: int) -> dict:
        with self._db.session_scope() as session:
            user = session.query(UserModel).filter_by(id=user_id).first()

            if not user:
                raise ValueError("User not found")

            user.is_active = True

        return {"message": "User activated"}