"""Flask application factory for MobileTrace."""
from __future__ import annotations

import atexit
import logging
import tempfile
from pathlib import Path

from flask import Flask, jsonify

from .config import load_config

logging.basicConfig(level=logging.INFO)


def create_app(config_path: str = "config.yaml", testing: bool = False) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    if testing:
        app.config["TESTING"] = True
        cfg = load_config(config_path)
        # Use temp dirs for testing to avoid polluting project data/
        _tmp = tempfile.mkdtemp()
        cfg["server"]["database_path"] = str(Path(_tmp) / "mobiletrace.db")
        cfg["server"]["cases_dir"] = str(Path(_tmp) / "cases")
    else:
        cfg = load_config(config_path)

    app.config["MT_CONFIG"] = cfg

    # Ensure data dirs exist
    db_path = Path(cfg["server"]["database_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cases_dir = Path(cfg["server"]["cases_dir"] or "data/cases")
    cases_dir.mkdir(parents=True, exist_ok=True)

    # Database
    from .database import init_db, close_db
    init_db(str(db_path))
    if not testing:
        atexit.register(close_db)

    # Blueprints
    from .routes.cases import bp_cases
    from .routes.analysis import bp_analysis
    from .routes.chat import bp_chat
    from .routes.reports import bp_reports
    app.register_blueprint(bp_cases)
    app.register_blueprint(bp_analysis)
    app.register_blueprint(bp_chat)
    app.register_blueprint(bp_reports)

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "app": "mobiletrace"})

    return app
