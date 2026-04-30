"""
controllers/auth_controller.py
================================
Handles HTTP authentication endpoints and exposes reusable FastAPI
dependency injections for RBAC enforcement across all controllers.

Routes:
  POST /auth/login              → get JWT token
  POST /auth/register           → create user (admin only)
  GET  /auth/me                 → current user info
  PUT  /auth/users/{id}         → update user profile
  PUT  /auth/users/{id}/reset-password
  PUT  /auth/users/{id}/deactivate
  PUT  /auth/users/{id}/activate
  DELETE /auth/users/{id}       → delete user (admin only)
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from services.auth_service import AuthService      # business logic for auth operations
from models.schemas import LoginSchema, UserCreateSchema  # Pydantic request validation schemas

# Register all routes under the /auth prefix, grouped under "Auth" in Swagger docs
router = APIRouter(prefix="/auth", tags=["Auth"])

# Single shared AuthService instance — reused by all route functions in this module
auth_service = AuthService()


# ── Dependency Injections ──────────────────────────────────────────────────────
# These functions are used as FastAPI dependencies via Depends().
# They run before the route handler and inject the resolved user dict.

def get_current_user(authorization: str = Header(default=None)) -> dict:
    """
    Extract and validate JWT token from the Authorization header.
    Returns the full user dict (id, role, airport_id, username).
    Called automatically by FastAPI whenever a route declares:
        user: dict = Depends(get_current_user)
    """
    # Reject requests missing the Authorization header or wrong format
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Strip the "Bearer " prefix to get the raw token string
    token = authorization.split(" ")[1]

    # Decode the JWT and look up the user in the DB
    user = auth_service.get_current_user(token)

    # Reject expired or tampered tokens
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user  # passed to the route handler as the `user` argument


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    FastAPI dependency — ensures only admin users can access the route.
    Raises HTTP 403 Forbidden for staff and viewer roles.
    """
    if user["role"] != "admin":  # check the role field from the decoded JWT
        raise HTTPException(status_code=403, detail="Admin access required")
    return user  # return unchanged for use in route handler


def require_staff_or_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    FastAPI dependency — allows admin and staff roles, blocks viewers.
    Used on flight creation endpoints where staff need write access.
    """
    if user["role"] not in ["admin", "staff"]:  # viewers are explicitly excluded
        raise HTTPException(status_code=403, detail="Staff or admin access required")
    return user


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login")
def login(credentials: LoginSchema):
    """
    Authenticate with username + password and receive a JWT access token.
    Token payload contains: user_id, role, airport_id — used by all subsequent requests.
    """
    # Delegate credential verification + token generation to the service layer
    result = auth_service.authenticate(credentials.username, credentials.password)

    # Return 401 if username not found, password wrong, or account is deactivated
    if not result:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return result  # returns {"access_token": ..., "role": ..., "airport_id": ...}


@router.post("/register", status_code=201)
def register_user(user_data: UserCreateSchema, admin: dict = Depends(require_admin)):
    """
    Register a new user. Only admins can call this endpoint.
    - Staff and Viewer accounts must include airport_id
    - Admin accounts have airport_id set to NULL automatically
    After registration, an email with login credentials is sent to the new user.
    """
    try:
        # Pass all validated fields to the service layer for hashing and DB insertion
        result = auth_service.register_user(
            admin_id=admin["id"],          # record which admin created this user
            username=user_data.username,
            password=user_data.password,   # service will hash this before storage
            email=user_data.email,
            full_name=user_data.full_name,
            role=user_data.role,
            airport_id=user_data.airport_id,  # None for admin — enforced in service
        )
        return {
            "message": f"User '{user_data.username}' registered successfully",
            "user": result  # serialized user dict returned from service
        }
    except ValueError as e:
        # Service raises ValueError for duplicate usernames, missing airport_id, etc.
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """
    Return the currently authenticated user's profile.
    Used by the frontend on every page load to restore session state.
    """
    return user  # already resolved by get_current_user dependency


@router.put("/users/{user_id}")
def update_user(user_id: int, data: dict, admin: dict = Depends(require_admin)):
    """
    Update a user's profile fields (full_name, email, role, airport_id).
    Admin only. An admin cannot change their own role.
    """
    try:
        # Delegate field validation and DB update to the service layer
        return auth_service.update_user(user_id, data, admin["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/users/{user_id}/reset-password")
def reset_password(user_id: int, data: dict, admin: dict = Depends(require_admin)):
    """
    Reset a user's password to the value provided in the request body.
    The new password is bcrypt-hashed before storage.
    """
    try:
        # Extract the new plaintext password from the JSON body {"password": "..."}
        return auth_service.reset_password(user_id, data["password"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/users/{user_id}/deactivate")
def deactivate_user(user_id: int, admin: dict = Depends(require_admin)):
    """
    Soft-deactivate a user account (sets is_active=False in DB).
    Deactivated users cannot log in even with correct credentials.
    Admin cannot deactivate their own account.
    """
    # Safety guard — admin cannot lock themselves out
    if admin["id"] == user_id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    try:
        return auth_service.deactivate_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/users/{user_id}/activate")
def activate_user(user_id: int, admin: dict = Depends(require_admin)):
    """
    Re-activate a previously deactivated user account (sets is_active=True).
    """
    try:
        return auth_service.activate_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/users/{user_id}", status_code=200)
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    """
    Permanently delete a user from the database (admin only).
    Admin cannot delete their own account to prevent accidental lockout.
    """
    # Prevent the admin from deleting themselves
    if admin["id"] == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    try:
        result = auth_service.delete_user(user_id)  # returns True if deleted, False if not found

        if not result:
            raise HTTPException(status_code=404, detail="User not found.")

        return {"message": f"User {user_id} deleted successfully."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))