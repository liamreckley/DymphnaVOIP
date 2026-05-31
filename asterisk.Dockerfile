FROM andrius/asterisk:22

# Install envsubst (gettext-base) for pjsip.conf templating at startup
RUN apt-get update && apt-get install -y gettext-base && rm -rf /var/lib/apt/lists/*

COPY asterisk/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
