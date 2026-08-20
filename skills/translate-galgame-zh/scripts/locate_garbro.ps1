[CmdletBinding()]
param(
    [string]$Path,
    [switch]$Launch
)

$skillRoot = Split-Path -Parent $PSScriptRoot
$candidates = [System.Collections.Generic.List[string]]::new()

if ($Path) {
    $candidates.Add($Path)
}
if ($env:GARBRO_PATH) {
    $candidates.Add($env:GARBRO_PATH)
}

foreach ($name in @('GARbro.Console.exe', 'GARbro.GUI.exe')) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
        $candidates.Add($command.Source)
    }
}

foreach ($relative in @(
    'assets\tools\garbro\GARbro.Console.exe',
    'assets\tools\garbro\GARbro.GUI.exe'
)) {
    $candidates.Add((Join-Path $skillRoot $relative))
}

$resolvedExe = $null
foreach ($candidate in $candidates) {
    if (-not $candidate) {
        continue
    }
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        foreach ($name in @('GARbro.Console.exe', 'GARbro.GUI.exe')) {
            $nested = Join-Path $candidate $name
            if (Test-Path -LiteralPath $nested -PathType Leaf) {
                $resolvedExe = (Resolve-Path -LiteralPath $nested).Path
                break
            }
        }
    } elseif (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $resolvedExe = (Resolve-Path -LiteralPath $candidate).Path
    }
    if ($resolvedExe) {
        break
    }
}

if (-not $resolvedExe) {
    throw 'GARbro was not found. Pass -Path, set GARBRO_PATH, or add GARbro.Console.exe/GARbro.GUI.exe to PATH.'
}

if ($Launch) {
    $launchExe = $resolvedExe
    $guiSibling = Join-Path (Split-Path -Parent $resolvedExe) 'GARbro.GUI.exe'
    if (Test-Path -LiteralPath $guiSibling -PathType Leaf) {
        $launchExe = (Resolve-Path -LiteralPath $guiSibling).Path
    }
    Start-Process -FilePath $launchExe -WorkingDirectory (Split-Path -Parent $launchExe)
}

$resolvedExe
