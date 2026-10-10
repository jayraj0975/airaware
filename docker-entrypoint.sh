#!/bin/sh
# Fills an empty data volume with the starting data, makes it writable, then runs the server as the unprivileged
# airaware user with every capability dropped and no way to regain privileges. Root is used only for these steps,
# because a fresh Railway volume is owned by root.
set -e
[ -f data/daily.csv ] || cp -a seed/. data/   # seed files belong to airaware already
if [ "$(id -u)" = 0 ]; then
  # Only a volume that is not ours yet; -P -h never follow links, so nothing outside the volume changes owner.
  [ "$(stat -c %U data)" = airaware ] || chown -R -P -h airaware:airaware data
  exec setpriv --reuid=airaware --regid=airaware --init-groups --no-new-privs --inh-caps=-all --bounding-set=-all "$@"
fi
exec "$@"
