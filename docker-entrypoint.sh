#!/bin/sh
# Fills an empty data volume with the starting data, makes it writable, then runs the server as the unprivileged
# airaware user. Root is used only for these two steps: a fresh Railway volume is owned by root.
set -e
[ -f data/daily.csv ] || cp -a seed/. data/
if [ "$(id -u)" = 0 ]; then
  chown -R airaware:airaware data
  exec setpriv --reuid=airaware --regid=airaware --init-groups "$@"
fi
exec "$@"
