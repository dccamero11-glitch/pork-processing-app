$ErrorActionPreference = 'Stop'

$appDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $appDirectory

$projectDirectory = Split-Path -Parent $appDirectory
$pythonExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    $pythonCommand = Get-Command 'python' -ErrorAction Stop
    $pythonExecutable = $pythonCommand.Source
}

Write-Host ''
Write-Host 'Product Processing System' -ForegroundColor Cyan
Write-Host 'Enter your OpenAI API key to enable AI label reading.'
Write-Host 'The key is hidden and is not saved to a file.' -ForegroundColor DarkGray

$secureApiKey = Read-Host 'OpenAI API key' -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureApiKey)

try {
    $plainApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
}

if ([string]::IsNullOrWhiteSpace($plainApiKey)) {
    Write-Host 'No API key was entered. The program was not started.' -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

$env:OPENAI_API_KEY = $plainApiKey
$plainApiKey = $null

$portClient = New-Object System.Net.Sockets.TcpClient
$portIsBusy = $false
try {
    $connectTask = $portClient.ConnectAsync('127.0.0.1', 8088)
    $portIsBusy = $connectTask.Wait(500) -and $portClient.Connected
}
catch {
    $portIsBusy = $false
}
finally {
    $portClient.Dispose()
}

if ($portIsBusy) {
    Remove-Item 'Env:\OPENAI_API_KEY' -ErrorAction SilentlyContinue
    Write-Host 'Port 8088 is already in use by an older server.' -ForegroundColor Red
    Write-Host 'Close the old Product Processing System window, then run start.bat again.'
    Read-Host 'Press Enter to close'
    exit 1
}

$serverProcess = $null
try {
    $serverProcess = Start-Process -FilePath $pythonExecutable -ArgumentList 'app.py' -WorkingDirectory $appDirectory -NoNewWindow -PassThru

    $status = $null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($serverProcess.HasExited) {
            throw 'The backend stopped before it was ready.'
        }

        try {
            $status = Invoke-RestMethod -Uri 'http://127.0.0.1:8088/api/status' -Method Get -TimeoutSec 2
        }
        catch {
            $status = $null
        }

        if ($null -ne $status) {
            break
        }

        Start-Sleep -Milliseconds 250
    }

    if ($null -eq $status) {
        throw 'The backend did not become ready on port 8088.'
    }

    if ($status.ai -ne $true) {
        throw 'The backend did not receive OPENAI_API_KEY.'
    }

    Write-Host 'AI is ready. Opening the web page...' -ForegroundColor Green
    Start-Process 'http://localhost:8088'
    $serverProcess.WaitForExit()
}
finally {
    Remove-Item 'Env:\OPENAI_API_KEY' -ErrorAction SilentlyContinue
}

Write-Host 'The program has stopped.'
Read-Host 'Press Enter to close'
