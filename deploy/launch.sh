#!/bin/bash
# Desktop-icon launcher (deploy/trivision.desktop). Starts the controller on demand and
# opens the touch page in a normal Firefox window (close it and nothing relaunches).
# The other controller (~/trivision2) uses port 8000 too: refuse while it holds the port.
if ! systemctl --user is-active -q trivision.service && ss -tlnH 'sport = :8000' | grep -q .; then
  zenity --error --title="Trivision" \
    --text="Port 8000 is in use - is the new controller still running?\nClose it first.\n\n$(ss -tlnpH 'sport = :8000')"
  exit 1
fi
systemctl --user start trivision.service
until (echo > /dev/tcp/127.0.0.1/8000) 2>/dev/null; do sleep 1; done
firefox --new-window "http://localhost:8000/?touch=1"
