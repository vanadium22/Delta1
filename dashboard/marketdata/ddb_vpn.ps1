param(
    [string]$ConfigPath,
    [string]$TrustPath,
    [Parameter(Mandatory=$true)][string]$DdbHost,
    [Parameter(Mandatory=$true)][int]$DdbPort,
    [ValidateSet('ensure','inspect','status','disconnect')][string]$Action='ensure',
    [ValidateRange(1,120)][int]$ConnectTimeout=45,
    [ValidateRange(1,60)][int]$DisconnectTimeout=20
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Reused from the existing dolphindb_data/sslvpn.ps1 native login implementation.
# Numeric callers use only ensure; they never invoke the legacy logout action.
# The Python owner attaches a kill-on-parent-exit job before permitting actions.
if ([Console]::ReadLine() -ne 'ready') { exit 2 }
$stage='configuration'
$gateway=$null
$localClient=$null
$script:agentToken=''
$script:lastAgentOperation=''
$script:lastAgentCode=''
$script:activeDdbConnections=$null

# This handler applies only to the explicitly configured gateway. No system CA,
# global callback, proxy setting, or other HTTPS connection is modified.
Add-Type -TypeDefinition @'
using System;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
public static class SwhyVpnTls {
  // Reachability only: reject the certificate and send no DDB credentials.
  // A TCP-accepting transparent proxy with no TLS service must return false.
  public static bool DdbTlsReachable(string host,int port) {
    bool certificateSeen=false;
    using(var tcp=new System.Net.Sockets.TcpClient()) {
      try {
        if(!tcp.ConnectAsync(host,port).Wait(1800) || !tcp.Connected) return false;
        using(var tls=new SslStream(tcp.GetStream(),false,(sender,cert,chain,errors)=> {
          certificateSeen=cert!=null;
          return false;
        })) {
          tls.ReadTimeout=1800; tls.WriteTimeout=1800;
          try { tls.AuthenticateAsClient(host); }
          catch(System.Security.Authentication.AuthenticationException) { return certificateSeen; }
          return certificateSeen;
        }
      } catch(System.IO.IOException) { return certificateSeen; }
        catch(System.Net.Sockets.SocketException) { return false; }
        catch(AggregateException) { return false; }
    }
  }
  public static string Hex(byte[] data) { return BitConverter.ToString(data).Replace("-", ""); }
  public static byte[] Unhex(string hex) {
    if (hex.Length % 2 != 0) hex="0"+hex;
    byte[] b=new byte[hex.Length/2];
    for(int i=0;i<b.Length;i++) b[i]=Convert.ToByte(hex.Substring(i*2,2),16);
    return b;
  }
  public static bool CheckCertificate(string endpoint,string pin,Uri request,
                                      X509Certificate2 cert,DateTime now) {
    Uri expected=new Uri(endpoint);
    if(cert==null || request.Scheme!="https" ||
       !String.Equals(request.Host,expected.Host,StringComparison.OrdinalIgnoreCase) ||
       request.Port!=expected.Port) return false;
    if(now<cert.NotBefore.ToUniversalTime() || now>cert.NotAfter.ToUniversalTime()) return false;
    using(SHA256 hash=SHA256.Create()) {
      return String.Equals(Hex(hash.ComputeHash(cert.RawData)),pin,StringComparison.OrdinalIgnoreCase);
    }
  }
  public static HttpClient Gateway(string endpoint,string pin) {
    Uri expected=new Uri(endpoint);
    HttpClientHandler handler=new HttpClientHandler();
    handler.UseProxy=false;
    handler.AllowAutoRedirect=false;
    handler.CookieContainer=new CookieContainer();
    handler.ServerCertificateCustomValidationCallback=(req,cert,chain,errors)=>
      CheckCertificate(endpoint,pin,req.RequestUri,cert,DateTime.UtcNow);
    HttpClient client=new HttpClient(handler);
    client.BaseAddress=expected;
    client.Timeout=TimeSpan.FromSeconds(20);
    return client;
  }
  public static string Encrypt(string text,string modulus,int exponent) {
    RSAParameters p=new RSAParameters(); p.Modulus=Unhex(modulus);
    string exp=exponent.ToString("x"); p.Exponent=Unhex(exp);
    using(RSA rsa=RSA.Create()) {
      rsa.ImportParameters(p);
      return Hex(rsa.Encrypt(System.Text.Encoding.UTF8.GetBytes(text),RSAEncryptionPadding.Pkcs1)).ToLowerInvariant();
    }
  }
}
'@

function Normalize-VpnUrl([string]$Text) {
    $value=$Text.Trim()
    if($value -match '^\[[^\]]+\]\((https://[^)]+)\)$') { $value=$Matches[1] }
    $uri=[Uri]$value
    if($uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') {
        throw 'invalid_gateway_url'
    }
    return $uri.GetLeftPart([UriPartial]::Authority)
}
function Test-DdbTcp {
    # Kept as the established function name; the SSL DDB endpoint must answer TLS.
    return [SwhyVpnTls]::DdbTlsReachable($DdbHost,$DdbPort)
}
function Request-Gateway([string]$Path,$Form=$null) {
    if($null -eq $Form) { $response=$gateway.GetAsync($Path).GetAwaiter().GetResult() }
    else {
        $pairs=[Collections.Generic.Dictionary[string,string]]::new()
        foreach($key in $Form.Keys) { $pairs.Add($key,[string]$Form[$key]) }
        $content=[Net.Http.FormUrlEncodedContent]::new($pairs)
        try { $response=$gateway.PostAsync($Path,$content).GetAwaiter().GetResult() }
        finally { $content.Dispose() }
    }
    try {
        if([int]$response.StatusCode -ne 200) { throw 'gateway_http_failed' }
        $body=$response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if($body.Length -gt 2000000) { throw 'unexpected_gateway_response_size' }
        $doc=[xml]$body
        return $doc
    } finally { $response.Dispose() }
}
function Xml-Text($Doc,[string]$Name) {
    $node=$Doc.SelectSingleNode('//*[local-name()="'+$Name+'"]')
    if($null -eq $node) { return '' }
    return [string]$node.InnerText
}
function Set-AgentToken([string]$SessionId) {
    # Native client protocol (business/session.js); this is a session authenticator,
    # not password hashing. Keep it in memory and never log it.
    $md5=[Security.Cryptography.MD5]::Create()
    try { $script:agentToken=[SwhyVpnTls]::Hex($md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($SessionId+'__md5_salt_for_ecagent_session__'))).ToLowerInvariant() }
    finally { $md5.Dispose() }
}
function Request-Agent([string]$Operation,[string[]]$Parameters=@(),[switch]$AllowAnyResult) {
    $script:lastAgentOperation=$Operation
    $query='op='+[Uri]::EscapeDataString($Operation)+'&type=WEB&callBack=swhyVpn'
    if($script:agentToken) { $query+='&token='+[Uri]::EscapeDataString($script:agentToken) }
    for($i=0;$i -lt $Parameters.Count;$i++) { $query+='&arg'+($i+1)+'='+[Uri]::EscapeDataString($Parameters[$i]) }
    $response=$localClient.GetAsync('https://127.0.0.1:54530/ECAgent/?'+$query).GetAwaiter().GetResult()
    try {
        if([int]$response.StatusCode -ne 200) { throw 'native_agent_http_failed' }
        $body=$response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if($body.Length -gt 5000000 -or $body -notmatch '^\s*swhyVpn\((.*)\);?\s*$') {
            # JSONP bodies may contain newlines.
            $matched=[regex]::Match($body,'^\s*swhyVpn\((.*)\);?\s*$',[Text.RegularExpressions.RegexOptions]::Singleline)
            if(-not $matched.Success) { throw 'invalid_native_agent_response' }
            $payload=$matched.Groups[1].Value
        } else { $payload=$Matches[1] }
        $result=$payload | ConvertFrom-Json
        if($result -is [string]) { $result=$result | ConvertFrom-Json }
        $script:lastAgentCode=if([string]$result.result -match '^-?\d{1,8}$') { [string]$result.result } else { '' }
        if(-not $AllowAnyResult -and [string]$result.result -ne '1') { throw 'native_agent_operation_failed' }
        return $result
    } finally { $response.Dispose() }
}

function Test-NativeConnectionRefused([Exception]$Exception) {
    # A stopped local agent is eligible for cold start. TLS errors, timeouts and
    # unknown failures must not be converted into permission to start/retry it.
    $refused=$false
    $current=$Exception
    for($depth=0;$null -ne $current -and $depth -lt 20;$depth++) {
        if($current -is [Security.Authentication.AuthenticationException] -or
           [string]$current.HttpRequestError -eq 'SecureConnectionError') { return $false }
        if($current -is [Net.Sockets.SocketException]) {
            if($current.SocketErrorCode -ne [Net.Sockets.SocketError]::ConnectionRefused) { return $false }
            $refused=$true
        }
        $current=$current.InnerException
    }
    if($null -ne $current) { return $false }
    return $refused
}

function Get-NativeLoginStatus($Result) {
    if([string]$Result.result -ne '1') { throw 'native_agent_operation_failed' }
    $value=$null
    if($Result.data -is [string]) {
        # Older installed client adapters use query-string data instead of an object.
        $statusItems=@($Result.data -split '&' | Where-Object { $_ -match '^status=' })
        if($statusItems.Count -eq 1) { $value=[Uri]::UnescapeDataString($statusItems[0].Substring(7)) }
    } elseif($null -ne $Result.data) {
        # A freshly started installed ECAgent answers {result:'1',data:{}}
        # before InitEcAgent. Do not invent a disconnected status: expose a
        # distinct bootstrap condition to the lease-owning connection scope.
        if($Result.data -is [pscustomobject] -and @($Result.data.PSObject.Properties).Count -eq 0) {
            throw 'native_agent_uninitialized'
        }
        $value=[string]$Result.data.status
    }
    if($value -notmatch '^[0-4]$') { throw 'invalid_native_status_response' }
    return [int]$value
}
function New-VpnStatusReport([int]$NativeStatus,[bool]$TcpReachable) {
    $state='unknown'
    if($NativeStatus -in @(0,3) -and -not $TcpReachable) { $state='disconnected' }
    elseif($NativeStatus -eq 1 -and $TcpReachable) { $state='connected' }
    elseif($NativeStatus -eq 2) { $state='connecting' }
    return @{state=$state;mode='native_status';native_status_code=$NativeStatus;tcp_verified=$TcpReachable;active_ddb_connections=$script:activeDdbConnections}
}
function Read-LocalVpnStatus {
    $response=Request-Agent 'DoQueryService' @('QUERY LOGINSTATUS')
    $nativeStatus=Get-NativeLoginStatus $response
    return New-VpnStatusReport $nativeStatus (Test-DdbTcp)
}
function Get-DdbEstablishedCount {
    # Check every established session to the configured endpoint, including clients
    # outside the Python lease manager. A failed inspection must never permit Logout.
    $targetAddresses=@([Net.Dns]::GetHostAddresses($DdbHost) | ForEach-Object { $_.MapToIPv6().ToString() })
    if(-not $targetAddresses.Count) { throw 'ddb_address_resolution_failed' }
    $connections=@(Get-NetTCPConnection -ErrorAction Stop | Where-Object {
        $_.State -eq 'Established' -and $_.RemotePort -eq $DdbPort -and
        ([Net.IPAddress]::Parse($_.RemoteAddress).MapToIPv6().ToString() -in $targetAddresses)
    })
    return $connections.Count
}
function Invoke-LocalVpnAction([string]$LocalAction,[int]$TimeoutSeconds) {
    if($LocalAction -eq 'status') { return Read-LocalVpnStatus }
    if($LocalAction -ne 'disconnect') { throw 'invalid_local_action' }
    $script:activeDdbConnections=Get-DdbEstablishedCount
    if($script:activeDdbConnections -gt 0) { throw 'active_ddb_connections' }
    $before=Read-LocalVpnStatus
    if($before.state -eq 'disconnected') { return $before }
    # api/res.js and common/request.js in the installed EasyConnect client use
    # ECAgent Logout (GET after transport adaptation), not GUI exit or StopService.
    $null=Request-Agent 'Logout'
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $after=Read-LocalVpnStatus
        if($after.state -eq 'disconnected') {
            $after.mode='native_logout'
            return $after
        }
        Start-Sleep -Milliseconds 300
    } while([DateTime]::UtcNow -lt $deadline)
    throw 'native_logout_not_verified'
}

try {
    if($Action -in @('status','disconnect')) {
        # Local-only operations do not read credentials/trust files or contact the
        # gateway. Native Logout and LOGINSTATUS were verified without a token.
        $stage='native_'+$Action
        $handler=[Net.Http.HttpClientHandler]::new(); $handler.UseProxy=$false; $handler.AllowAutoRedirect=$false
        $localClient=[Net.Http.HttpClient]::new($handler); $localClient.Timeout=[TimeSpan]::FromSeconds(10)
        $report=Invoke-LocalVpnAction $Action $DisconnectTimeout
        $report | ConvertTo-Json -Compress
        if($Action -eq 'disconnect' -and $report.state -ne 'disconnected') { exit 2 }
        exit 0
    }
    if($Action -eq 'ensure' -and (Test-DdbTcp)) {
        @{state='connected';mode='existing_tunnel';tcp_verified=$true} | ConvertTo-Json -Compress
        exit 0
    }
    $cfg=Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
    if ($cfg.protected_credentials) {
        if ($cfg.protected_credentials.scheme -ne 'windows-dpapi-current-user-v1') { throw 'invalid_vpn_configuration' }
        Add-Type -AssemblyName System.Security
        $cipher=[Convert]::FromBase64String($cfg.protected_credentials.data)
        $clear=[System.Security.Cryptography.ProtectedData]::Unprotect($cipher,$null,[System.Security.Cryptography.DataProtectionScope]::CurrentUser)
        try {
            $secret=[Text.Encoding]::UTF8.GetString($clear) | ConvertFrom-Json
            foreach($key in @('id','password')) { $cfg | Add-Member -NotePropertyName $key -NotePropertyValue $secret.$key -Force }
        } finally { [Array]::Clear($clear,0,$clear.Length); $secret=$null }
    }
    foreach($key in @('url','id','password')) { if(-not ($cfg.$key -is [string]) -or -not $cfg.$key) { throw 'invalid_vpn_configuration' } }
    $vpnUrl=Normalize-VpnUrl $cfg.url
    $trust=Get-Content -Raw -LiteralPath $TrustPath | ConvertFrom-Json
    if((Normalize-VpnUrl $trust.endpoint) -ne $vpnUrl -or $trust.certificate_sha256 -notmatch '^[A-Fa-f0-9]{64}$') { throw 'invalid_gateway_trust' }
    $gateway=[SwhyVpnTls]::Gateway($vpnUrl,$trust.certificate_sha256)
    $handler=[Net.Http.HttpClientHandler]::new(); $handler.UseProxy=$false; $handler.AllowAutoRedirect=$false
    $localClient=[Net.Http.HttpClient]::new($handler); $localClient.Timeout=[TimeSpan]::FromSeconds(20)
    $stage='gateway_tls_and_auth_configuration'
    $init=Request-Gateway '/por/login_auth.csp?apiversion=1'
    $psw=Request-Gateway '/public/psw_config?apiversion=1'
    $csrf=Xml-Text $psw 'CSRF_RAND_CODE'
    $modulus=Xml-Text $psw 'RSA_ENCRYPT_KEY'
    $exp=Xml-Text $psw 'RSA_ENCRYPT_EXP'
    $startAuth=Xml-Text $init 'StartAuth'
    if($Action -eq 'inspect') {
        @{state='inspected';tls_pin_verified=$true;start_auth=$startAuth;init_code=(Xml-Text $init 'ErrorCode');password_code=(Xml-Text $psw 'ErrorCode');captcha=(Xml-Text $psw 'USE_RAND_CODE');mitm=(Xml-Text $psw 'MID_ATK_CHECK');has_nonce=[bool]$csrf;has_rsa_key=[bool]$modulus} | ConvertTo-Json -Compress
        exit 0
    }
    if((Xml-Text $psw 'USE_RAND_CODE') -eq '1' -or $startAuth -notin @('1','')) { throw 'interactive_auth_required' }
    if(-not $csrf -or $modulus -notmatch '^[A-Fa-f0-9]+$' -or $exp -notmatch '^\d+$') { throw 'missing_anti_replay_rsa_configuration' }
    Set-AgentToken (Xml-Text $init 'TwfID')
    $stage='native_agent_detection'
    try { $null=Request-Agent 'DetectECAgent' } catch {
        if(-not (Test-NativeConnectionRefused $_.Exception)) { throw }
        $agentExe='C:\Program Files (x86)\Sangfor\SSL\ECAgent\ECAgent.exe'
        if(-not (Test-Path -LiteralPath $agentExe)) { throw 'native_agent_not_installed' }
        Start-Process -FilePath $agentExe -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 2
        $null=Request-Agent 'DetectECAgent'
    }
    $null=Request-Agent 'SelectLines' @($vpnUrl)
    $nativeUrl=[Uri]$vpnUrl
    $null=Request-Agent 'InitEcAgent' @($nativeUrl.Host+' '+$nativeUrl.Port)
    $encrypted=[SwhyVpnTls]::Encrypt($cfg.password+'_'+$csrf,$modulus,[int]$exp)
    $form=@{mitm_result='';svpn_req_randcode=$csrf;svpn_name=$cfg.id;svpn_password=$encrypted;svpn_rand_code=''}
    if((Xml-Text $psw 'MID_ATK_CHECK') -eq '1') {
        $stage='native_mitm_verification'
        $mitm=Request-Agent 'GetMITEMAttackResult' @($cfg.id,$encrypted,'')
        $form.mitm_result=[string]$mitm.data; $form.svpn_password=''
    }
    $stage='authentication'
    $auth=Request-Gateway '/por/login_psw.csp?anti_replay=1&encrypt=1&apiversion=1' $form
    $code=Xml-Text $auth 'ErrorCode'
    if($code -ne '1') {
        @{state='failed';stage=$stage;reason='authentication_or_additional_factor_required';error_code=$code} | ConvertTo-Json -Compress
        exit 2
    }
    $twfid=Xml-Text $auth 'TwfID'
    if(-not $twfid) { throw 'authenticated_without_session_id' }
    Set-AgentToken $twfid
    $stage='native_tunnel_start'
    $key=Request-Agent 'GetEncryptKey' @() -AllowAnyResult
    $encryptedSession=[SwhyVpnTls]::Encrypt($twfid,[string]$key.result,65537)
    $stage='native_set_session'
    $null=Request-Agent 'DoConfigure' @('SET TWFID '+$encryptedSession)
    $stage='native_fetch_configuration'
    $null=Request-Agent 'GetConfig' @('1')
    $null=Request-Agent 'GetConfig' @('2')
    $null=Request-Agent 'DoXmlConfigure' @('1')
    $null=Request-Agent 'DoXmlConfigure' @('2')
    $null=Request-Agent 'DoConfigure' @('SET BROWSER default')
    $stage='native_set_gateway'
    $null=Request-Agent 'DoConfigure' @('SET SERVADDR '+$nativeUrl.Host+' '+$nativeUrl.Port)
    $stage='native_start_service'
    $null=Request-Agent 'StartService'
    $stage='ddb_tcp_verification'
    $deadline=[DateTime]::UtcNow.AddSeconds($ConnectTimeout)
    do {
        if(Test-DdbTcp) { @{state='connected';mode='native_login';tcp_verified=$true;tls_pin_verified=$true} | ConvertTo-Json -Compress; exit 0 }
        Start-Sleep -Milliseconds 750
    } while([DateTime]::UtcNow -lt $deadline)
    throw 'authenticated_but_ddb_tcp_unreachable'
} catch {
    # Never serialize exception text: a URL or provider body may contain session data.
    $known=@('invalid_gateway_url','invalid_vpn_configuration','invalid_gateway_trust','gateway_http_failed','interactive_auth_required','missing_anti_replay_rsa_configuration','native_agent_not_installed','native_agent_operation_failed','invalid_native_agent_response','authenticated_without_session_id','authenticated_but_ddb_tcp_unreachable','invalid_native_status_response','native_agent_uninitialized','invalid_local_action','ddb_address_resolution_failed','active_ddb_connections','native_logout_not_verified')
    $reason=if($_.Exception.Message -in $known) { $_.Exception.Message } else { 'operation_failed' }
    if($stage -in @('native_status','native_disconnect','native_agent_detection') -and
       (Test-NativeConnectionRefused $_.Exception)) { $reason='native_agent_not_listening' }
    @{state='failed';stage=$stage;reason=$reason;exception_type=$_.Exception.GetType().Name;native_operation=$script:lastAgentOperation;native_code=$script:lastAgentCode;active_ddb_connections=$script:activeDdbConnections} | ConvertTo-Json -Compress
    exit 2
} finally {
    if($gateway) { $gateway.Dispose() }
    if($localClient) { $localClient.Dispose() }
    $cfg=$null; $form=$null; $encrypted=$null; $twfid=$null; $encryptedSession=$null; $script:agentToken=''
}
