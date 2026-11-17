#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Allow the WarshipPilot WebUI on the local network (run once as administrator).
.DESCRIPTION
  The launcher runs as the desktop user and cannot change Windows Firewall. When
  WebUI.Host is 0.0.0.0, other devices on the LAN need an inbound rule for the
  WebUI port. The rule is port-based (TCP <Port>, local subnet only) because the
  backend's Python path changes whenever uv installs a newer interpreter, and it
  removes Block rules Windows created for this installation's interpreters when a
  firewall prompt was dismissed. Idempotent.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\allow-lan-access.ps1
#>
[CmdletBinding()]
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [int]$Port = 22680
)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')
if (!(Test-Path -LiteralPath "$Root\gui.py")) { throw "Not a WarshipPilot installation: $Root" }
$blocked = Get-NetFirewallRule -Action Block -ErrorAction SilentlyContinue | Where-Object {
    ($_ | Get-NetFirewallApplicationFilter).Program -like "$Root\*"
}
foreach ($rule in @($blocked)) {
    Write-Output ("Removing block rule {0} for {1}" -f $rule.DisplayName, ($rule | Get-NetFirewallApplicationFilter).Program)
    $rule | Remove-NetFirewallRule
}
Get-NetFirewallRule -Name 'WarshipPilot-WebUI-LAN' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name 'WarshipPilot-WebUI-LAN' -DisplayName 'WarshipPilot WebUI (LAN)' -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Profile Any `
    -Description 'WarshipPilot WebUI, local subnet only (port rule: survives Python path changes).' | Out-Null
Write-Output "Allowed TCP $Port from the local subnet (rule WarshipPilot-WebUI-LAN)."
