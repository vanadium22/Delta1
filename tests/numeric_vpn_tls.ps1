# No network, no imported trust roots. The fixture certificate exists in memory only.
$ErrorActionPreference='Stop'
$source=Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot '../dashboard/marketdata/ddb_vpn.ps1')
$match=[regex]::Match($source,"(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@")
if(-not $match.Success) { throw 'Cannot locate production TLS validator' }
Add-Type -TypeDefinition $match.Groups[1].Value
$rsa=[Security.Cryptography.RSA]::Create(2048)
$request=[Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=test-only',$rsa,[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1)
$now=[DateTime]::UtcNow
$cert=$request.CreateSelfSigned([DateTimeOffset]$now.AddMinutes(-5),[DateTimeOffset]$now.AddMinutes(5))
$hash=[Security.Cryptography.SHA256]::Create()
try {
    $pin=[SwhyVpnTls]::Hex($hash.ComputeHash($cert.RawData))
    $url='https://vpn.example:10443'
    $cases=@(
        @{Name='exact pinned host';Url=$url;Pin=$pin;Now=$now;Expected=$true},
        @{Name='different host';Url='https://other.example:10443';Pin=$pin;Now=$now;Expected=$false},
        @{Name='different port';Url='https://vpn.example:443';Pin=$pin;Now=$now;Expected=$false},
        @{Name='HTTP downgrade';Url='http://vpn.example:10443';Pin=$pin;Now=$now;Expected=$false},
        @{Name='changed fingerprint';Url=$url;Pin=('0'*64);Now=$now;Expected=$false},
        @{Name='expired certificate';Url=$url;Pin=$pin;Now=$now.AddHours(1);Expected=$false},
        @{Name='not yet valid';Url=$url;Pin=$pin;Now=$now.AddHours(-1);Expected=$false}
    )
    foreach($case in $cases) {
        $actual=[SwhyVpnTls]::CheckCertificate($url,$case.Pin,[Uri]$case.Url,$cert,$case.Now)
        if($actual -ne $case.Expected) { throw ('TLS pin check failed: '+$case.Name) }
    }
    Write-Output ('TLS certificate checks passed: '+$cases.Count)
} finally { $cert.Dispose();$rsa.Dispose();$hash.Dispose() }
