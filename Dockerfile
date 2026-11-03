# The bonk web server. Build and run:
#   docker build -t bonk .
#   docker run -p 8000:8000 bonk
FROM python:3.12-slim

WORKDIR /app
COPY requirements-server.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt -c constraints.txt

COPY bonk_game ./bonk_game
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000
# On SIGTERM the server finishes running matches (up to BONK_DRAIN_SECONDS)
# before exiting; give the container a stop timeout a bit longer than that.
CMD ["python", "-m", "bonk_game.server"]
