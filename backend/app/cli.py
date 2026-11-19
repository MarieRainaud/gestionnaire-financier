import argparse
import getpass
import os
from sqlalchemy import select, delete
from pwdlib import PasswordHash
from .db import Base, engine, SessionLocal, User, LoginSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create-user", "change-password"])
    parser.add_argument("email")
    args = parser.parse_args()
    if os.environ.get("APP_MODE") != "private":
        raise SystemExit("Cette commande est réservée à APP_MODE=private")
    password = getpass.getpass("Mot de passe (16 caractères minimum) ")
    if not 16 <= len(password) <= 1024:
        raise SystemExit("Mot de passe de 16 à 1 024 caractères attendu")
    if password != getpass.getpass("Confirmation "):
        raise SystemExit("Les deux saisies diffèrent")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.casefold()))
        if args.command == "create-user":
            if user:
                raise SystemExit("Compte déjà présent")
            user = User(
                email=args.email.casefold(),
                password=PasswordHash.recommended().hash(password),
                demo=False,
            )
            db.add(user)
        else:
            if not user or user.demo:
                raise SystemExit("Compte privé introuvable")
            user.password = PasswordHash.recommended().hash(password)
            db.execute(delete(LoginSession).where(LoginSession.owner_id == user.id))
        db.commit()
    print("Compte privé mis à jour")


if __name__ == "__main__":
    main()
