#!/bin/sh
# Substitute SIP credentials into pjsip.conf at startup
set -e

# Create empty extensions file if it doesn't exist
touch /etc/asterisk/pjsip_extensions.conf

# Substitute env vars into pjsip.conf from template
envsubst '${VOIPMS_SIP_USERNAME} ${VOIPMS_SIP_PASSWORD}' \
  < /etc/asterisk/pjsip.conf.template \
  > /etc/asterisk/pjsip.conf

echo "[entrypoint] pjsip.conf generated for ${VOIPMS_SIP_USERNAME}"

exec asterisk -f "$@"
