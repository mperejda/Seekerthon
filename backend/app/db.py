from supabase import create_client, Client
from app.config import get_settings
from functools import lru_cache

_settings = get_settings()


@lru_cache()
def get_supabase_admin() -> Client:
    """Admin client with service role key — bypasses RLS for server-side ops."""
    return create_client(_settings.supabase_url, _settings.supabase_service_role_key)
