param(
    [int]$Jobs = 4,
    [switch]$SkipClean
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bash = "C:\tools\msys64\usr\bin\bash.exe"

if (-not (Test-Path $Bash)) {
    throw "MSYS2 bash not found: $Bash"
}

$env:PATH = "$RepoRoot\bin;C:\ProgramData\mingw64\mingw64\bin;C:\ProgramData\miniconda3;C:\ProgramData\miniconda3\Scripts;" + $env:PATH

$msysRoot = $RepoRoot -replace "\\", "/"
$msysRoot = "/" + $msysRoot.Substring(0, 1).ToLower() + $msysRoot.Substring(2)

$commands = @(
    'export PATH="/c/ProgramData/mingw64/mingw64/bin:/c/ProgramData/miniconda3:/c/ProgramData/miniconda3/Scripts:/c/ProgramData/chocolatey/bin:$PATH"',
    "cd '$msysRoot'",
    "make msys2fix"
)

if (-not $SkipClean) {
    $commands += "make clean HAVE_HYLIA=false"
}

$commands += "make backend discovery bridges-ui frontend HAVE_HYLIA=false -j$Jobs"

& $Bash -lc ($commands -join "; ")
