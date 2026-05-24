from flask import Flask
from threading import Thread
import logging

# Reduce flask logging noise
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run():
    # Run the Flask app on port 8080 (standard Replit web port)
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    """Starts the Flask web server in a background thread."""
    t = Thread(target=run)
    t.daemon = True
    t.start()
