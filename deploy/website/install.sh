#!/usr/bin/env bash
# MINTRO website: install or update it on a Debian/Ubuntu server (a Google Cloud e2-micro VM is plenty).
#
#   sudo bash install.sh your-domain.com you@example.com   # the site, with free HTTPS from Let's Encrypt
#   sudo bash install.sh your-domain.com                   # the site over plain HTTP (add HTTPS later)
#
# Run it again with a newer package to update the site. The web server settings and the HTTPS certificate
# are kept; only the site's files are replaced, all at once, so visitors never see a half-updated page.
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
SITE_ROOT=/var/www/mintro
NGINX_SITE=/etc/nginx/sites-available/mintro
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run it with sudo:  sudo bash install.sh your-domain.com you@example.com"
[[ -n "$DOMAIN" ]] || die "Say which domain:  sudo bash install.sh your-domain.com you@example.com"
# Accept what people paste: "HTTPS://WWW.Example.com/" becomes "example.com"
DOMAIN="${DOMAIN,,}"
DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"; DOMAIN="${DOMAIN#www.}"
[[ "$DOMAIN" =~ ^([a-z0-9-]+\.)+[a-z]{2,}$ ]] || die "\"$DOMAIN\" doesn't look like a domain name."
[[ -z "$EMAIL" || "$EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || die "\"$EMAIL\" doesn't look like an email address."
[[ -f "$HERE/site/index.html" ]] || die "No site/ folder next to this script. Unzip the whole package first."
command -v apt-get >/dev/null || die "This script needs a Debian or Ubuntu server (apt-get)."

# ---- web server ------------------------------------------------------------------------------------------
if ! command -v nginx >/dev/null; then
  say "Installing the nginx web server"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx >/dev/null
fi

# ---- the site --------------------------------------------------------------------------------------------
say "Copying the website to $SITE_ROOT"
NEW="$SITE_ROOT.new"
rm -rf "$NEW"
mkdir -p "$NEW"
cp -a "$HERE/site/." "$NEW/"
# Share previews and search engines need this site's full address
find "$NEW" -type f \( -name '*.html' -o -name '*.webmanifest' \) -exec sed -i "s#https://__MINTRO_DOMAIN__#https://$DOMAIN#g" {} +
cat > "$NEW/robots.txt" <<EOF
User-agent: *
Allow: /
Sitemap: https://$DOMAIN/sitemap.xml
EOF
cat > "$NEW/sitemap.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://$DOMAIN/</loc><lastmod>$(date -u +%F)</lastmod></url>
</urlset>
EOF
# Compressed copies made once here, so the small VM doesn't compress on every request
find "$NEW" -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.svg' -o -name '*.webmanifest' \
  -o -name '*.xml' -o -name '*.txt' \) -exec gzip -9 -k -f {} \;
chmod -R a+rX "$NEW"
if [[ -d "$SITE_ROOT" ]]; then
  rm -rf "$SITE_ROOT.old"
  mv "$SITE_ROOT" "$SITE_ROOT.old"
fi
mv "$NEW" "$SITE_ROOT"
rm -rf "$SITE_ROOT.old"

# ---- nginx settings (first install only; later runs keep them, and the HTTPS lines certbot adds) -------
mkdir -p /etc/nginx/snippets
cat > /etc/nginx/snippets/mintro-headers.conf <<'EOF'
# Sent with every MINTRO page (written by install.sh)
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), interest-cohort=()" always;
EOF
if [[ ! -f "$NGINX_SITE" ]]; then
  say "Setting up nginx for $DOMAIN"
  cat > "$NGINX_SITE" <<EOF
# MINTRO website, written by install.sh. certbot adds the HTTPS lines below when you turn HTTPS on.
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;

    root $SITE_ROOT;
    index index.html;
    server_tokens off;

    gzip on;
    gzip_static on;
    gzip_vary on;
    gzip_types text/css application/javascript image/svg+xml application/manifest+json application/xml text/plain;

    error_page 404 /404.html;

    location / {
        try_files \$uri \$uri/ =404;
        include snippets/mintro-headers.conf;
        add_header Cache-Control "no-cache" always;
    }
    location /assets/ {
        try_files \$uri =404;
        include snippets/mintro-headers.conf;
        add_header Cache-Control "public, max-age=86400" always;
    }
    location = /site.webmanifest {
        default_type application/manifest+json;
        include snippets/mintro-headers.conf;
        add_header Cache-Control "public, max-age=86400" always;
    }
}
EOF
  ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/mintro
  rm -f /etc/nginx/sites-enabled/default
fi
nginx -t >/dev/null 2>&1 || { nginx -t; die "nginx didn't accept its settings (see above)."; }
systemctl enable --now nginx >/dev/null 2>&1 || true
systemctl reload nginx 2>/dev/null || systemctl restart nginx

# ---- HTTPS -----------------------------------------------------------------------------------------------
SCHEME=http
if [[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
  SCHEME=https
  say "HTTPS is already set up; the certificate renews by itself"
elif [[ -n "$EMAIL" ]]; then
  # Let's Encrypt can only issue a certificate if the domain already points at this server
  MY_IP="$(curl -fs -m 3 -H 'Metadata-Flavor: Google' \
    http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip \
    || curl -fs -m 5 https://api.ipify.org || true)"
  DNS_IP="$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}' || true)"
  if [[ -n "$MY_IP" && "$DNS_IP" != "$MY_IP" ]]; then
    warn "$DOMAIN points to '${DNS_IP:-nowhere}', but this server is $MY_IP."
    warn "Add an A record for $DOMAIN -> $MY_IP at your domain registrar, wait a few minutes, then run this again."
  else
    say "Getting a free HTTPS certificate from Let's Encrypt"
    if ! command -v certbot >/dev/null; then
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
    fi
    NAMES=(-d "$DOMAIN")
    WWW_IP="$(getent ahostsv4 "www.$DOMAIN" | awk 'NR==1 {print $1}' || true)"
    if [[ -n "$WWW_IP" && ( -z "$MY_IP" || "$WWW_IP" == "$MY_IP" ) ]]; then
      NAMES+=(-d "www.$DOMAIN")
    else
      warn "www.$DOMAIN doesn't point here, so the certificate covers $DOMAIN only (fine; add www later by running this again)."
    fi
    if certbot --nginx "${NAMES[@]}" --redirect --agree-tos -m "$EMAIL" --non-interactive --keep-until-expiring; then
      SCHEME=https
      # HTTP/2 makes the page's many small files load faster
      sed -i -E 's/listen (\[::\]:)?443 ssl;/listen \1443 ssl http2;/; s/listen \[::\]:443 ssl ipv6only=on;/listen [::]:443 ssl http2 ipv6only=on;/' "$NGINX_SITE"
      if ! nginx -t >/dev/null 2>&1; then
        sed -i 's/ ssl http2/ ssl/' "$NGINX_SITE"
      fi
      systemctl reload nginx
    else
      warn "Let's Encrypt didn't issue a certificate (see above). The site works over http:// meanwhile."
    fi
  fi
else
  warn "No email given, so no HTTPS yet. For HTTPS run:  sudo bash install.sh $DOMAIN you@example.com"
fi

say "Done. MINTRO's website is live at $SCHEME://$DOMAIN/"
echo "    Files: $SITE_ROOT    Web server settings: $NGINX_SITE"
echo "    To update later: upload a newer package, unzip it, and run this same command again."
