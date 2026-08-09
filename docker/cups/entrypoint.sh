#!/bin/sh
set -eu

admin_user="${CUPS_ADMIN_USER:-printadmin}"
admin_password="${CUPS_ADMIN_PASSWORD:?CUPS_ADMIN_PASSWORD must be set}"
allowed_networks="${CUPS_ALLOWED_NETWORKS:-100.64.0.0/10}"

case "$admin_user" in
  *[!A-Za-z0-9_-]*|'') echo "CUPS_ADMIN_USER contains invalid characters" >&2; exit 1 ;;
esac
if [ "${#admin_password}" -lt 12 ]; then
  echo "CUPS_ADMIN_PASSWORD must contain at least 12 characters" >&2
  exit 1
fi
case "$allowed_networks" in
  *[!0-9A-Fa-f:.,/' ']*) echo "CUPS_ALLOWED_NETWORKS must contain only IP addresses or CIDRs" >&2; exit 1 ;;
esac

if ! id "$admin_user" >/dev/null 2>&1; then
  useradd --create-home --groups lpadmin "$admin_user"
else
  usermod -a -G lpadmin "$admin_user"
fi
printf '%s:%s\n' "$admin_user" "$admin_password" | chpasswd

umask 022
config=/etc/cups/cupsd.conf
cat >"$config" <<'EOF'
LogLevel warn
PageLogFormat
MaxLogSize 0
Listen 0.0.0.0:631
Browsing Yes
BrowseLocalProtocols dnssd
DefaultAuthType Basic
WebInterface Yes
ServerAlias *
PreserveJobHistory Yes
PreserveJobFiles No

<Location />
  Order allow,deny
  Allow from 127.0.0.1
  Allow from 172.30.0.0/24
EOF

old_ifs=$IFS
IFS=','
for network in $allowed_networks; do
  network=$(printf '%s' "$network" | tr -d ' ')
  [ -n "$network" ] && printf '  Allow from %s\n' "$network" >>"$config"
done
IFS=$old_ifs

cat >>"$config" <<'EOF'
</Location>

<Location /admin>
  AuthType Basic
  Require user @SYSTEM
  Order allow,deny
  Allow from 127.0.0.1
  Allow from 172.30.0.0/24
EOF

IFS=','
for network in $allowed_networks; do
  network=$(printf '%s' "$network" | tr -d ' ')
  [ -n "$network" ] && printf '  Allow from %s\n' "$network" >>"$config"
done
IFS=$old_ifs

cat >>"$config" <<'EOF'
</Location>

<Location /admin/conf>
  AuthType Basic
  Require user @SYSTEM
  Order allow,deny
  Allow from 127.0.0.1
  Allow from 172.30.0.0/24
EOF

IFS=','
for network in $allowed_networks; do
  network=$(printf '%s' "$network" | tr -d ' ')
  [ -n "$network" ] && printf '  Allow from %s\n' "$network" >>"$config"
done
IFS=$old_ifs

cat >>"$config" <<'EOF'
</Location>

<Policy default>
  <Limit Create-Job Print-Job Print-URI Validate-Job Send-Document Send-URI Get-Printer-Attributes Get-Jobs Get-Job-Attributes CUPS-Get-Printers>
    Order allow,deny
    Allow from 127.0.0.1
    Allow from 172.30.0.0/24
EOF

IFS=','
for network in $allowed_networks; do
  network=$(printf '%s' "$network" | tr -d ' ')
  [ -n "$network" ] && printf '    Allow from %s\n' "$network" >>"$config"
done
IFS=$old_ifs

cat >>"$config" <<'EOF'
  </Limit>
  <Limit CUPS-Add-Modify-Printer CUPS-Delete-Printer CUPS-Add-Modify-Class CUPS-Delete-Class CUPS-Set-Default>
    AuthType Basic
    Require user @SYSTEM
    Order allow,deny
    Allow from 127.0.0.1
    Allow from 172.30.0.0/24
EOF

IFS=','
for network in $allowed_networks; do
  network=$(printf '%s' "$network" | tr -d ' ')
  [ -n "$network" ] && printf '    Allow from %s\n' "$network" >>"$config"
done
IFS=$old_ifs

cat >>"$config" <<'EOF'
  </Limit>
  <Limit Hold-Job Release-Job Restart-Job Purge-Jobs Set-Job-Attributes Cancel-Job CUPS-Move-Job>
    AuthType Basic
    Require user @OWNER @SYSTEM
    Order allow,deny
    Allow from 127.0.0.1
    Allow from 172.30.0.0/24
EOF

IFS=','
for network in $allowed_networks; do
  network=$(printf '%s' "$network" | tr -d ' ')
  [ -n "$network" ] && printf '    Allow from %s\n' "$network" >>"$config"
done
IFS=$old_ifs

cat >>"$config" <<'EOF'
  </Limit>
  <Limit All>
    Order deny,allow
  </Limit>
</Policy>
EOF

mkdir -p /run/cups /var/spool/cups /var/cache/cups
rm -f /run/cups/cupsd.pid
ulimit -n 65535

cupsd -f &
cups_pid=$!
trap 'kill "$cups_pid"' TERM INT

attempt=0
while ! lpstat -r >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -ge 30 ] && break
  sleep 1
done

printer_ip="${CUPS_PRINTER_IP:-}"
printer_name="${CUPS_PRINTER_NAME:-printer}"
if [ -n "$printer_ip" ]; then
  if ! lpstat -p "$printer_name" >/dev/null 2>&1; then
    echo "adding IPP queue ${printer_name}: ipp://${printer_ip}/ipp/print"
    lpadmin -p "$printer_name" -E -v "ipp://${printer_ip}/ipp/print" -m everywhere
  fi
  lpadmin -d "$printer_name"
  lpoptions -p "$printer_name" -o sides=two-sided-long-edge >/dev/null
fi

wait "$cups_pid"
exit $?
