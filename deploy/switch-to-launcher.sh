#!/bin/bash
# Run ON the kiosk as bannrig:  bash ~/trivision/deploy/switch-to-launcher.sh
# Stops booting straight into our app (another controller is used day to day):
# removes the kiosk autostart, disables the service at boot, puts a Trivision icon
# on the desktop that starts the service + page on demand, then reboots.
set -e
D=~/trivision/deploy
rm -f ~/.config/autostart/trivision-kiosk.desktop
systemctl --user disable --now trivision.service || true
pkill -f kiosk.sh || true
pkill -x firefox || true
chmod +x "$D/launch.sh"
install -m 755 "$D/trivision.desktop" ~/Desktop/trivision.desktop
# GNOME shows an untrusted-launcher warning until this is set.
gio set ~/Desktop/trivision.desktop metadata::trusted true 2>/dev/null || true
echo "launcher installed; rebooting"
# No sudo over ssh: try logind first, then ask the running GNOME session.
systemctl reboot 2>/dev/null || \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus gdbus call --session \
  --dest org.gnome.SessionManager --object-path /org/gnome/SessionManager \
  --method org.gnome.SessionManager.RequestReboot
