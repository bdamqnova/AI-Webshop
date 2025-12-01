import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

def show_users():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, email FROM users")
        users = c.fetchall()

        if not users:
            print("No users found in the database.")
            return

        print("\n--- Users in Database ---")
        for user in users:
            print(f"ID: {user[0]}, Email: {user[1]}")
        print("-------------------------\n")

if __name__ == "__main__":
    show_users()

