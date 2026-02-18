import tidalapi
session = tidalapi.Session()
try:
    login = session.get_link_login()
    print(f"Dir: {dir(login)}")
    # Common attributes for device flow
    print(f"Verification URL: {getattr(login, 'verification_uri', 'N/A')}")
    print(f"Verification URL Complete: {getattr(login, 'verification_uri_complete', 'N/A')}")
    print(f"User Code: {getattr(login, 'user_code', 'N/A')}")
    print(f"Device Code: {getattr(login, 'device_code', 'N/A')}")
except Exception as e:
    print(f"Error: {e}")
