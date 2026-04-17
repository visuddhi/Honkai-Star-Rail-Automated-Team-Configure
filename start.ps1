$python = "C:\Users\hzqin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& $python (Join-Path $scriptRoot "app.py")
