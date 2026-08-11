"""Application factory.

`create_app()` builds and configures the Flask app. Keeping it in a factory
(rather than a module-level `app = Flask(...)`) means tests and scripts can
spin up an isolated instance without importing side effects.
"""

from flask import Flask

from .config import Config
from .db import close_db, init_db


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

    # Create the SQLite schema on first run.
    init_db(app)

    # Close the per-request DB connection when the request ends.
    app.teardown_appcontext(close_db)

    from .routes import bp
    app.register_blueprint(bp)

    # Expose a couple of values to every template without passing them
    # through each render_template() call.
    @app.context_processor
    def inject_globals():
        return {
            "APP_NAME": "PFAS Reporting Automation",
            "REPORTING_YEAR": Config.REPORTING_YEAR,
            "DEADLINE": Config.DEADLINE,
            "EMAIL_DRY_RUN": Config.EMAIL_DRY_RUN,
            "AI_PROVIDER": Config.AI_PROVIDER,
        }

    return app
