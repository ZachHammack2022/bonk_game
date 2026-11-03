"""The multiplayer web server (issue #23).

The server runs every match: physics, scoring and rounds, using the same
code as the desktop game. Browsers send their player's buttons and draw
the state they get back. Run it with `python -m bonk_game.server`.

- scene.py: turns the world into shapes and numbers for the browser
- match.py: one match (env, countdown/rounds/results, bots)
- room.py: rooms, members, the host's settings, running matches
- web.py: HTTP routes and the WebSocket protocol
- static/: the browser client
"""
