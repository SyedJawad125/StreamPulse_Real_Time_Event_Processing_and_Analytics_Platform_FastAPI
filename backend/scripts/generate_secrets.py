"""Print fresh random values for SECRET_KEY and API_KEY_PEPPER (paste into your .env)."""
import secrets

print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
print(f"API_KEY_PEPPER={secrets.token_urlsafe(48)}")
print("\nKeep these private. Changing API_KEY_PEPPER invalidates every existing API key.")
