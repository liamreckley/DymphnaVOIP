#!/bin/sh
# Generate runtime config from templates at startup, then run Asterisk.
set -e

# Per-extension PJSIP config lives in a directory-mounted volume. (Mounting a named
# volume onto a single FILE path turns it into a directory and breaks the #include.)
mkdir -p /etc/asterisk/pjsip_ext
touch /etc/asterisk/pjsip_ext/pjsip_extensions.conf

# pjsip.conf  ← inject the voip.ms SIP trunk credentials
envsubst '${VOIPMS_SIP_USERNAME} ${VOIPMS_SIP_PASSWORD}' \
  < /etc/asterisk/pjsip.conf.template \
  > /etc/asterisk/pjsip.conf

# manager.conf ← inject the AMI secret (shared with the voip-api service)
envsubst '${ASTERISK_SECRET}' \
  < /etc/asterisk/manager.conf.template \
  > /etc/asterisk/manager.conf

echo "[entrypoint] pjsip.conf + manager.conf generated"

exec asterisk -f "$@"
