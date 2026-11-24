from __future__ import annotations

from typing import Any

from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request


class IsStaffOrReadOnly(BasePermission):
    """Anyone may read; changing data needs a staff account (session or token)."""

    def has_permission(self, request: Request, view: Any) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)
