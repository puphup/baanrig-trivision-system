#!/bin/bash
# One-time root steps for the touch-screen PC. Run once:  sudo bash ~/trivision/deploy/root-setup.sh
# Everything else (service, kiosk autostart) is installed as the bannrig user, no root needed.
set -e
USER_NAME=bannrig

apt-get install -y python3.14-venv

# GDM auto-login so the kiosk autostart entry runs at boot without a password prompt.
CONF=/etc/gdm3/custom.conf
sed -i -e '/^#\?AutomaticLoginEnable/d' -e '/^#\?AutomaticLogin\s*=/d' "$CONF"
sed -i "s/^\[daemon\]/[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=$USER_NAME/" "$CONF"

# Start the user's systemd services at boot even before the desktop session is up.
loginctl enable-linger "$USER_NAME"

echo "root-setup done"
