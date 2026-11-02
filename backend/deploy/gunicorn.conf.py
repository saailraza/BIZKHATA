# gunicorn -c deploy/gunicorn.conf.py wsgi:application
bind = "127.0.0.1:8000"
workers = 3
threads = 4
timeout = 60
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
preload_app = False
