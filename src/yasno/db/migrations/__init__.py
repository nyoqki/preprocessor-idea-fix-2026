from importlib.resources import files

from alembic.config import Config

from yasno.config import get_settings


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(files("yasno.db") / "migrations"))
    config.set_main_option("sqlalchemy.url", str(get_settings().database_url))
    return config
