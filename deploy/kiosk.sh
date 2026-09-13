#!/bin/bash
# Launched by ~/.config/autostart/trivision-kiosk.desktop after GNOME auto-login.
# ponytail: waits for the controller port, then keeps Firefox in kiosk mode; if someone
# closes it (Alt+F4) it comes back in 2 s. To get out: ssh in and `pkill -f kiosk.sh`.
until (echo > /dev/tcp/127.0.0.1/8000) 2>/dev/null; do sleep 1; done
while true; do
  firefox --kiosk "http://localhost:8000/?touch=1"
  sleep 2
done
