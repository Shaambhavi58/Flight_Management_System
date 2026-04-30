"""
Auth Controller — Handles login, registration (admin only), and /me endpoint.
Exposes dependency injections: get_current_user, require_admin, require_staff_or_admin.
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from services.auth_service import AuthService
from models.schemas import LoginSchema, UserCreateSchema

router = APIRouter(prefix="/auth", tags=["Auth"])
auth_service = AuthService()


# ── Dependency Injections ───────────────────────────────────────────────

def get_current_user(authorization: str = Header(default=None)) -> dict:
    """
    Extract and validate JWT token from Authorization header.
    Returns full user dict including role and airport_id.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ")[1]
    user = auth_service.get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Ensure the current user is an admin. Raises 403 otherwise."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_staff_or_admin(user: dict = Depends(get_current_user)) -> dict:
    """Ensure the current user is admin or staff. Raises 403 otherwise."""
    if user["role"] not in ["admin", "staff"]:
        raise HTTPException(status_code=403, detail="Staff or admin access required")
    return user


# ── Routes ──────────────────────────────────────────────────────────────

@router.post("/login")
def login(credentials: LoginSchema):
    """
    Authenticate and receive a JWT token.
    Token payload includes: user_id, role, airport_id.
    """
    result = auth_service.authenticate(credentials.username, credentials.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return result


@router.post("/register", status_code=201)
def register_user(user_data: UserCreateSchema, admin: dict = Depends(require_admin)):
    """
    Register a new user (admin only).
    - staff / viewer must include airport_id
    - admin accounts will have airport_id set to NULL automatically
    Sends credentials email after registration.
    """
    try:
        result = auth_service.register_user(
            admin_id=admin["id"],
            username=user_data.username,
            password=user_data.password,
            email=user_data.email,
            full_name=user_data.full_name,
            role=user_data.role,
            airport_id=user_data.airport_id,  # None for admin (validated in service)
        )
        return {
            "message": f"User '{user_data.username}' registered successfully",
            "user": result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """Get current logged-in user info (includes role and airport_id)."""
    return user

@router.put("/users/{user_id}")
def update_user(user_id: int, data: dict, admin: dict = Depends(require_admin)):
    try:
        return auth_service.update_user(user_id, data, admin["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/users/{user_id}/reset-password")
def reset_password(user_id: int, data: dict, admin: dict = Depends(require_admin)):
    try:
        return auth_service.reset_password(user_id, data["password"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/users/{user_id}/deactivate")
def deactivate_user(user_id: int, admin: dict = Depends(require_admin)):
    if admin["id"] == user_id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    try:
        return auth_service.deactivate_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/users/{user_id}/activate")
def activate_user(user_id: int, admin: dict = Depends(require_admin)):
    try:
        return auth_service.activate_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/users/{user_id}", status_code=200)
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    """
    Delete a user by ID (admin only).
    Admin cannot delete themselves.
    """
    if admin["id"] == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    try:
        result = auth_service.delete_user(user_id)
        if not result:
            raise HTTPException(status_code=404, detail="User not found.")
        return {"message": f"User {user_id} deleted successfully."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))