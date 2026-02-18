import tidalapi
session = tidalapi.Session()
try:
    res = session.get_link_login()
    print(f"Type: {type(res)}")
    print(f"Value: {res}")
except Exception as e:
    print(f"Error: {e}")
