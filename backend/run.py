"""Simple local run:  python run.py     (for live hosting use gunicorn, see README_DEPLOY.md)"""
import logging

from bizkhata import config
from bizkhata.app import create_app

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

if __name__ == '__main__':
    app = create_app()
    port = int(config.get('PORT', '3000'))
    print('BIZKHATA running on http://localhost:%d' % port)
    app.run(host=config.get('HOST', '127.0.0.1'), port=port, threaded=True)
