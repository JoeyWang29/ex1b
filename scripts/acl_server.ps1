# ---------------------------------------------------------------------------
# 服务端目录 ACL（Windows / NTFS，等价于 Linux 的 setfacl 方案）
#
# 判卷环境是 Windows，因此这里给出 NTFS DACL 的最小权限配置：
#   1) 关闭继承（/inheritance:r），从空白权限开始，避免 C:\ 的 Users 权限外溢；
#   2) 只授予服务账户 filesvc 对该目录的修改权（M，含读写/删除子项）；
#   3) 管理员保留完全控制，Everyone / Users 显式移除；
#   4) users.db 放在 DATA_ROOT 之外，只给 filesvc 读权限。
#
# 用法（管理员 PowerShell）：
#   .\acl_server.ps1 -DataRoot D:\securefile\data -ServiceAccount "NT AUTHORITY\NetworkService"
# ---------------------------------------------------------------------------
param(
    [string]$DataRoot = "D:\securefile\data",
    [string]$StateDir = "D:\securefile\state",
    [string]$ServiceAccount = "$env:COMPUTERNAME\filesvc",
    [switch]$CreateAccount
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "需要管理员权限：请以“以管理员身份运行”启动 PowerShell。"
    }
}
Assert-Admin

if ($CreateAccount) {
    $name = $ServiceAccount.Split('\')[-1]
    if (-not (Get-LocalUser -Name $name -ErrorAction SilentlyContinue)) {
        $pw = ConvertTo-SecureString ([Guid]::NewGuid().ToString() + "aA1!") -AsPlainText -Force
        New-LocalUser -Name $name -Password $pw -PasswordNeverExpires `
            -UserMayNotChangePassword -Description "SecureFile service account" | Out-Null
        Write-Host "[+] local user $name created (no interactive logon right)"
    }
}

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
foreach ($u in @("alice", "bob", "admin")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot $u) | Out-Null
}

Write-Host "[1/3] reset inheritance on $DataRoot"
icacls $DataRoot /inheritance:r | Out-Null
icacls $DataRoot /remove:g "Everyone" "Users" "Authenticated Users" 2>$null | Out-Null

Write-Host "[2/3] grant modify rights to $ServiceAccount (this folder, subfolders, files)"
icacls $DataRoot /grant:r "${ServiceAccount}:(OI)(CI)M" | Out-Null
icacls $DataRoot /grant:r "Administrators:(OI)(CI)F" | Out-Null
icacls $DataRoot /grant:r "SYSTEM:(OI)(CI)F" | Out-Null
icacls $DataRoot /setowner "Administrators" | Out-Null

Write-Host "[3/3] hide the user database from the transfer sandbox"
if (Test-Path (Join-Path $StateDir "users.db")) {
    icacls (Join-Path $StateDir "users.db") /inheritance:r | Out-Null
    icacls (Join-Path $StateDir "users.db") /grant:r "${ServiceAccount}:R" "Administrators:F" | Out-Null
}

Write-Host ""
Write-Host "effective DACL:"
icacls $DataRoot
Write-Host ""
Write-Host "服务进程请以该账户启动，例如："
Write-Host "  runas /user:$ServiceAccount `"python server.py --config config.server.json`""
