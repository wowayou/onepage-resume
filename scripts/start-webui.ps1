#requires -Version 5.1
# Foreground controller. stdin stays open as the Python launcher's lifeline.
param(
    [switch]$NoOpen,
    [ValidateRange(2, 30)][int]$StartupTimeoutSeconds = 30
)

function ConvertTo-NativeArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -gt 0 -and -not [regex]::IsMatch($Value, '[\s"]')) {
        return $Value
    }
    # Windows argv quoting, not shell quoting. Double trailing backslashes and
    # backslashes before a quote. Simple distro names stay unquoted for WSL.
    $quoted = New-Object System.Text.StringBuilder
    [void]$quoted.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]92) {
            $backslashes++
            continue
        }
        if ($character -eq [char]34) {
            [void]$quoted.Append(('\' * (2 * $backslashes + 1)))
        } else {
            [void]$quoted.Append(('\' * $backslashes))
        }
        [void]$quoted.Append($character)
        $backslashes = 0
    }
    [void]$quoted.Append(('\' * (2 * $backslashes)))
    [void]$quoted.Append('"')
    return $quoted.ToString()
}

function Join-NativeArguments {
    param([string[]]$Values)
    $quoted = @(foreach ($value in $Values) { ConvertTo-NativeArgument $value })
    return [string]::Join(' ', [string[]]$quoted)
}

function Get-WebUiArguments {
    param(
        [string]$Base, [string]$Distro, [string]$LinuxDirectory,
        [ValidateRange(1, 65535)][int]$Port,
        [ValidatePattern('(?-i)\A[0-9a-f]{32}\z')][string]$LauncherId
    )
    if ([string]::IsNullOrEmpty($Base)) { throw 'BASE is missing.' }
    $prefix = @()
    $directory = $Base
    if (-not [string]::IsNullOrEmpty($Distro)) {
        if ([string]::IsNullOrEmpty($LinuxDirectory)) { throw 'LINUXDIR is missing.' }
        $prefix = @('-d', $Distro)
        $directory = $LinuxDirectory
    }
    return $prefix + @(
        '--cd', $directory, '-e', '.venv/bin/python', '-u', '-X', 'utf8',
        'webui.py', '--host', '127.0.0.1', '--port',
        $Port.ToString([System.Globalization.CultureInfo]::InvariantCulture),
        '--no-open', '--launcher-id', $LauncherId
    )
}

function New-OutputDrain {
    param([System.IO.StreamReader]$Reader, [System.IO.TextWriter]$Writer)
    $buffer = New-Object char[] 4096
    return [pscustomobject]@{
        Reader = $Reader; Writer = $Writer; Buffer = $buffer; Closed = $false
        Pending = $Reader.ReadAsync($buffer, 0, $buffer.Length)
    }
}

function Write-ProcessOutput {
    param([object[]]$Drains)
    $progress = $false
    $failure = $null
    foreach ($drain in $Drains) {
        try {
            # Bound each pass so neither pipe, HTTP nor keyboard can starve.
            for ($block = 0; $block -lt 4; $block++) {
                if ($drain.Closed -or -not $drain.Pending.IsCompleted) { break }
                $count = $drain.Pending.GetAwaiter().GetResult()
                $progress = $true
                if ($count -eq 0) {
                    $drain.Writer.Flush()
                    $drain.Closed = $true
                    $drain.Pending = $null
                    break
                }
                # Write exact chunks, including a final fragment without LF.
                # Console writers auto-flush bytes, but do not flush the UTF-8
                # encoder mid-chunk: a surrogate pair may cross this boundary.
                $drain.Writer.Write($drain.Buffer, 0, $count)
                $drain.Pending = $drain.Reader.ReadAsync($drain.Buffer, 0, $drain.Buffer.Length)
            }
        } catch {
            $drain.Closed = $true
            $drain.Pending = $null
            $failure = $_.Exception.GetBaseException().Message
        }
    }
    if ($null -ne $failure) { throw "Cannot drain child output: $failure" }
    return $progress
}

function New-ReadinessRequest {
    param([string]$Uri, [ValidateRange(1, 1000)][int]$TimeoutMilliseconds)
    $request = [System.Net.HttpWebRequest][System.Net.WebRequest]::Create($Uri)
    $request.Method = 'HEAD'
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.KeepAlive = $false
    $request.MaximumResponseHeadersLength = 16
    $request.CachePolicy = New-Object System.Net.Cache.RequestCachePolicy -ArgumentList (
        [System.Net.Cache.RequestCacheLevel]::NoCacheNoStore
    )
    $request.Headers['Cache-Control'] = 'no-cache, no-store'
    $request.Headers['Pragma'] = 'no-cache'
    $request.Timeout = $TimeoutMilliseconds
    $request.ReadWriteTimeout = $TimeoutMilliseconds
    return $request
}

function Test-ReadyResponse {
    param($Response, [string]$ExpectedHeader)
    return ($Response.StatusCode -eq [System.Net.HttpStatusCode]::OK -and
        [string]::Equals($Response.Headers['X-Onepage-Resume-Ready'],
            $ExpectedHeader, [System.StringComparison]::Ordinal))
}

function Test-StopRequested {
    param([bool]$Enabled)
    if (-not $Enabled) { return $false }
    for ($keyCount = 0; $keyCount -lt 16 -and [Console]::KeyAvailable; $keyCount++) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq [ConsoleKey]::Q -or $key.KeyChar -eq [char]3 -or
            ($key.Key -eq [ConsoleKey]::C -and
             ($key.Modifiers -band [ConsoleModifiers]::Control) -ne 0)) {
            return $true
        }
    }
    return $false
}

function Stop-WebUiChild {
    param(
        [System.Diagnostics.Process]$Process, [object[]]$Drains,
        [System.Net.HttpWebRequest]$Request, [int]$BudgetMilliseconds
    )
    $cleanup = [System.Diagnostics.Stopwatch]::StartNew()
    $failed = $false
    # Closing this writer is the first cleanup action, including cancellation.
    try { $Process.StandardInput.Close() } catch {
        $failed = $true
        [Console]::Error.WriteLine('[onepage-resume] Cannot close stdin: ' + $_.Exception.Message)
    }
    if ($null -ne $Request) { $Request.Abort() }
    $forced = $false
    do {
        $progress = $false
        try { $progress = Write-ProcessOutput -Drains $Drains } catch {
            $failed = $true
            [Console]::Error.WriteLine('[onepage-resume] ' + $_.Exception.Message)
        }
        $openDrains = @($Drains | Where-Object { -not $_.Closed })
        if ($Process.HasExited -and $openDrains.Count -eq 0) { return (-not $failed) }
        # Reserve the last 200 ms for EOF/output after a forced stop. This is
        # only the Process we started, never a lookup by name, PID or port.
        if (-not $forced -and $cleanup.ElapsedMilliseconds -ge ($BudgetMilliseconds - 200)) {
            if (-not $Process.HasExited) {
                [Console]::Error.WriteLine('[onepage-resume] stdin EOF grace expired; stopping our WSL handle only.')
                try { $Process.Kill() } catch {
                    $failed = $true
                    [Console]::Error.WriteLine('[onepage-resume] Cannot stop our child: ' + $_.Exception.Message)
                }
            }
            $forced = $true
        }
        if (-not $progress) { [System.Threading.Thread]::Sleep(10) }
    } while ($cleanup.ElapsedMilliseconds -lt $BudgetMilliseconds)
    try { [void](Write-ProcessOutput -Drains $Drains) } catch {
        $failed = $true
        [Console]::Error.WriteLine('[onepage-resume] ' + $_.Exception.Message)
    }
    if ($failed -or -not $Process.HasExited -or @($Drains | Where-Object { -not $_.Closed }).Count -ne 0) {
        [Console]::Error.WriteLine('[onepage-resume] Child/output cleanup was not completed within the budget.')
        return $false
    }
    return $true
}

function Invoke-WebUiController {
    param([switch]$NoOpen, [ValidateRange(2, 30)][int]$StartupTimeoutSeconds = 30)
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    Set-StrictMode -Version 2.0
    $process = New-Object System.Diagnostics.Process
    $started = $false
    $drains = @()
    $request = $null
    $pending = $null
    $ready = $false
    $identityMatched = $false
    $exitCode = 1
    $oldEncoding = $null
    $oldControlC = $false
    $controlCChanged = $false
    # Default: 28 seconds probing + 2 seconds cleanup, not 30 + 2.
    # Short test budgets split in half until the cleanup reserve reaches 2 s.
    $cleanupMilliseconds = [Math]::Min(2000, $StartupTimeoutSeconds * 500)
    $startupMilliseconds = $StartupTimeoutSeconds * 1000 - $cleanupMilliseconds
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $port = 0
        if (-not [int]::TryParse($env:WEBUI_PORT, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
            throw 'WEBUI_PORT must be an integer in 1..65535.'
        }
        $launcherId = [Guid]::NewGuid().ToString('N')
        $arguments = @(Get-WebUiArguments -Base $env:BASE -Distro $env:WSLDISTRO `
            -LinuxDirectory $env:LINUXDIR -Port $port -LauncherId $launcherId)
        $utf8 = New-Object System.Text.UTF8Encoding -ArgumentList $false
        $info = $process.StartInfo
        $info.FileName = 'wsl.exe'
        $info.Arguments = Join-NativeArguments -Values $arguments
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = $utf8
        $info.StandardErrorEncoding = $utf8
        $oldEncoding = [Console]::OutputEncoding
        [Console]::OutputEncoding = $utf8
        if (-not [Console]::IsInputRedirected) {
            $oldControlC = [Console]::TreatControlCAsInput
            [Console]::TreatControlCAsInput = $true
            $controlCChanged = $true
        }
        $clock.Restart()
        if (-not $process.Start()) { throw 'wsl.exe did not start.' }
        $started = $true
        $drains += New-OutputDrain -Reader $process.StandardOutput -Writer ([Console]::Out)
        $drains += New-OutputDrain -Reader $process.StandardError -Writer ([Console]::Error)
        $expectedHeader = 'v1;' + $launcherId
        $readyUri = 'http://127.0.0.1:{0}/__launcher/ready' -f $port
        $browserUri = 'http://127.0.0.1:{0}/' -f $port
        $nextProbeAt = 0
        $probeDeadline = 0
        $lastProbeError = 'No readiness response.'
        [Console]::WriteLine('[onepage-resume] Waiting for this launcher. Press Q or Ctrl-C to stop.')
        while ($true) {
            [void](Write-ProcessOutput -Drains $drains)
            if (Test-StopRequested -Enabled $controlCChanged) {
                $exitCode = if ($ready) { 0 } else { 130 }
                [Console]::WriteLine('[onepage-resume] Stopping: closing the stdin lifeline.')
                break
            }
            if ($process.HasExited) {
                $childCode = $process.ExitCode
                if (-not $ready) {
                    # Even an early 0 (or WSL's -1) is not a ready service.
                    [Console]::Error.WriteLine('[onepage-resume] Child exited before readiness; exit code: ' + $childCode)
                    $exitCode = 1
                } else {
                    $exitCode = $childCode
                    if ($childCode -ne 0) {
                        [Console]::Error.WriteLine('[onepage-resume] Web service failed; exit code: ' + $childCode)
                    }
                }
                break
            }
            if ($ready) { [System.Threading.Thread]::Sleep(20); continue }
            $now = $clock.Elapsed.TotalMilliseconds
            if ($now -ge $startupMilliseconds) {
                [Console]::Error.WriteLine('[onepage-resume] Startup timed out. ' + $lastProbeError)
                [Console]::Error.WriteLine('[onepage-resume] See child errors above; also check WSL2 localhostForwarding.')
                break
            }
            # Recheck liveness on the pass AFTER the exact response matched.
            if ($identityMatched -and -not $process.HasExited) {
                $ready = $true
                if (-not $NoOpen) {
                    try { Start-Process -FilePath $browserUri -ErrorAction Stop }
                    catch [System.ComponentModel.Win32Exception], [System.InvalidOperationException] {
                        [Console]::Error.WriteLine('[onepage-resume] Cannot open the browser: ' + $_.Exception.GetBaseException().Message)
                        [Console]::Error.WriteLine('[onepage-resume] Please visit manually: ' + $browserUri)
                    }
                }
                [Console]::WriteLine('[onepage-resume] Ready: ' + $browserUri)
                [Console]::WriteLine('[onepage-resume] Keep this window open. Q or Ctrl-C stops the service.')
                continue
            }
            if ($null -ne $request) {
                # Timeout does not govern BeginGetResponse; enforce its deadline
                # here while BOTH output pipes, keys and child liveness are polled.
                if ($now -ge $probeDeadline) {
                    $request.Abort()
                    $request = $null
                    $pending = $null
                    $lastProbeError = 'Readiness HEAD timed out.'
                    $nextProbeAt = $now + 150
                } elseif ($pending.IsCompleted) {
                    $response = $null
                    try {
                        $response = $request.EndGetResponse($pending)
                        $identityMatched = Test-ReadyResponse -Response $response -ExpectedHeader $expectedHeader
                        $lastProbeError = 'HEAD status/header did not identify this launcher.'
                    } catch {
                        $exception = $_.Exception.GetBaseException()
                        if ($exception -is [System.Net.WebException]) { $response = $exception.Response }
                        $lastProbeError = $exception.Message
                    } finally {
                        # HEAD only: close even HTTP error responses, never read a body.
                        if ($null -ne $response) { $response.Close() }
                        $request.Abort()
                        $request = $null
                        $pending = $null
                    }
                    $nextProbeAt = $clock.Elapsed.TotalMilliseconds + 150
                }
            } elseif ($now -ge $nextProbeAt) {
                $probeMilliseconds = [int][Math]::Floor([Math]::Min(1000, $startupMilliseconds - $now))
                if ($probeMilliseconds -gt 0) {
                    $request = New-ReadinessRequest -Uri $readyUri -TimeoutMilliseconds $probeMilliseconds
                    $probeDeadline = $now + $probeMilliseconds
                    $pending = $request.BeginGetResponse($null, $null)
                }
            }
            $delay = [Math]::Min(20, $startupMilliseconds - $clock.Elapsed.TotalMilliseconds)
            if ($null -ne $request) { $delay = [Math]::Min($delay, $probeDeadline - $clock.Elapsed.TotalMilliseconds) }
            [System.Threading.Thread]::Sleep([int][Math]::Max(0, [Math]::Floor($delay)))
        }
    } catch {
        [Console]::Error.WriteLine('[onepage-resume] Launcher failed: ' + $_.Exception.GetBaseException().Message)
        $exitCode = 1
    } finally {
        try {
            if ($started) {
                $cleaned = Stop-WebUiChild -Process $process -Drains $drains -Request $request `
                    -BudgetMilliseconds $cleanupMilliseconds
                if (-not $cleaned) { $exitCode = 1 }
            } elseif ($null -ne $request) { $request.Abort() }
        } finally {
            foreach ($drain in $drains) { $drain.Reader.Dispose() }
            $process.Dispose()
            if ($controlCChanged) { [Console]::TreatControlCAsInput = $oldControlC }
            if ($null -ne $oldEncoding) { [Console]::OutputEncoding = $oldEncoding }
        }
    }
    return $exitCode
}

# Dot-source for side-effect-free function tests; normal -File usage runs once.
if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-WebUiController -NoOpen:$NoOpen -StartupTimeoutSeconds $StartupTimeoutSeconds)
}
