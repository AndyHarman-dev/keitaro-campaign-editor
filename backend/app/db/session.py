from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=create_engine(database_url))
