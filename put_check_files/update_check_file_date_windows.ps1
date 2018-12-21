$location = split-path -parent $MyInvocation.MyCommand.Definition
$file = "$location\.backup"

$date = (Get-Date).ToUniversalTime()
$date = Get-Date -Date $date -Format 'yyyy-MM-dd HH:mm:ss'
(Get-Content $file) -replace '\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d$', "$date" | Out-File -Encoding ASCII $file

exit
