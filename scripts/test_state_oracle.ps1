# DEC-055: opt-in disposable snapshot/restore/oracle proof. Never the existing lab.
param([ValidateSet('desktop-linux')][string]$DockerContext)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$arguments = @((Join-Path $PSScriptRoot 'state_oracle_harness.py'))
if ($DockerContext) { $arguments += @('--docker-context', $DockerContext) }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw 'State/oracle disposable proof failed; inspect ignored diagnostic metadata.' }
