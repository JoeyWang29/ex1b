#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SecureFile PKI bootstrap
#
#   CA   -> server cert (SAN: localhost / 127.0.0.1 / sfap.local)
#        -> client cert per account (CN must equal the account name, because the
#           server binds CN to the account before accepting a login)
#
# Usage:  ./gen_certs.sh [output_dir]
# ---------------------------------------------------------------------------
set -euo pipefail

OUT="${1:-../run/certs}"
PASS="${SFAP_KEY_PASS:-}"          # empty = unencrypted keys (lab only)
DAYS=3650
SRV_DAYS=825

mkdir -p "$OUT"
cd "$OUT"

echo "[1/4] CA"
openssl genrsa -out ca-key.pem 4096 2>/dev/null
openssl req -x509 -new -key ca-key.pem -sha256 -days "$DAYS" -out ca-cert.pem \
  -subj "/C=CN/O=UCAS-SSS/OU=Software and System Security/CN=SecureFile Lab Root CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:1" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

echo "[2/4] server certificate"
openssl genrsa -out server-key.pem 2048 2>/dev/null
openssl req -new -key server-key.pem -out server.csr \
  -subj "/C=CN/O=UCAS-SSS/OU=SecureFile/CN=localhost"
cat > server.ext <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,DNS:sfap.local,IP:127.0.0.1,IP:::1
EOF
openssl x509 -req -in server.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial \
  -out server-cert.pem -days "$SRV_DAYS" -sha256 -extfile server.ext

echo "[3/4] client certificate template"
cat > client.ext <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
EOF

echo "[4/4] client certificates"
for USER in alice bob admin; do
  openssl genrsa -out "client-${USER}-key.pem" 2048 2>/dev/null
  openssl req -new -key "client-${USER}-key.pem" -out "client-${USER}.csr" \
    -subj "/C=CN/O=UCAS-SSS/OU=SecureFile/CN=${USER}"
  openssl x509 -req -in "client-${USER}.csr" -CA ca-cert.pem -CAkey ca-key.pem \
    -CAcreateserial -out "client-${USER}-cert.pem" -days "$SRV_DAYS" -sha256 -extfile client.ext
done

# Convenience symlinks for the demo account (Windows: copies).
cp "client-alice-cert.pem" client-cert.pem
cp "client-alice-key.pem"  client-key.pem

rm -f ./*.csr ./*.ext ./*.srl 2>/dev/null || true

echo
echo "done -> $(pwd)"
echo "  CA      : ca-cert.pem"
echo "  server  : server-cert.pem / server-key.pem"
echo "  clients : client-{alice,bob,admin}-{cert,key}.pem"
echo
openssl x509 -in server-cert.pem -noout -subject -issuer -ext subjectAltName
