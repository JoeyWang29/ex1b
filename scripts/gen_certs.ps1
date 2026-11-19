# ---------------------------------------------------------------------------
# SecureFile PKI bootstrap (Windows PowerShell)
# Requires OpenSSL on PATH (Git for Windows ships one at
# C:\Program Files\Git\usr\bin\openssl.exe).
#
#   .\gen_certs.ps1 [-Out ..\run\certs]
# ---------------------------------------------------------------------------
param([string]$Out = "..\run\certs")

$ErrorActionPreference = "Stop"
if (-not (Get-Command openssl -ErrorAction SilentlyContinue)) {
    throw "openssl not found. Add Git's usr\bin to PATH, or run gen_certs.sh under Git Bash."
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null
Push-Location $Out
try {
    Write-Host "[1/4] CA"
    openssl genrsa -out ca-key.pem 4096 2>$null
    openssl req -x509 -new -key ca-key.pem -sha256 -days 3650 -out ca-cert.pem `
        -subj "/C=CN/O=UCAS-SSS/OU=Software and System Security/CN=SecureFile Lab Root CA" `
        -addext "basicConstraints=critical,CA:TRUE,pathlen:1" `
        -addext "keyUsage=critical,keyCertSign,cRLSign"

    Write-Host "[2/4] server certificate"
    openssl genrsa -out server-key.pem 2048 2>$null
    openssl req -new -key server-key.pem -out server.csr `
        -subj "/C=CN/O=UCAS-SSS/OU=SecureFile/CN=localhost"
    @"
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,DNS:sfap.local,IP:127.0.0.1,IP:::1
"@ | Set-Content -Encoding ascii server.ext
    openssl x509 -req -in server.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial `
        -out server-cert.pem -days 825 -sha256 -extfile server.ext

    Write-Host "[3/4] client template"
    @"
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
"@ | Set-Content -Encoding ascii client.ext

    Write-Host "[4/4] client certificates"
    foreach ($user in @("alice", "bob", "admin")) {
        openssl genrsa -out "client-$user-key.pem" 2048 2>$null
        openssl req -new -key "client-$user-key.pem" -out "client-$user.csr" `
            -subj "/C=CN/O=UCAS-SSS/OU=SecureFile/CN=$user"
        openssl x509 -req -in "client-$user.csr" -CA ca-cert.pem -CAkey ca-key.pem `
            -CAcreateserial -out "client-$user-cert.pem" -days 825 -sha256 -extfile client.ext
    }
    Copy-Item client-alice-cert.pem client-cert.pem -Force
    Copy-Item client-alice-key.pem client-key.pem -Force
    Remove-Item *.csr, *.ext, *.srl -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "done -> $(Get-Location)"
    openssl x509 -in server-cert.pem -noout -subject -issuer -ext subjectAltName
}
finally {
    Pop-Location
}
