from handlers.admin import admin_router
from handlers.guest import tenant_guest_router
from handlers.inline import tenant_inline_router
from handlers.manage import manage_router
from handlers.tenant_info import tenant_info_router
from handlers.tenant_manage import tenant_manage_router
from handlers.tenant_wizard import tenant_wizard_router

__all__ = [
    "admin_router",
    "manage_router",
    "tenant_guest_router",
    "tenant_inline_router",
    "tenant_info_router",
    "tenant_manage_router",
    "tenant_wizard_router",
]
