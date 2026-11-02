"""Entry point for gunicorn / uWSGI / Passenger:   gunicorn wsgi:application"""
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
from bizkhata.app import create_app  # noqa: E402

application = app = create_app()
