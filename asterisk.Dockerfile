FROM andrius/asterisk:22-alpine

# Install envsubst (part of gettext)
RUN apk add --no-cache gettext

COPY asterisk/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
