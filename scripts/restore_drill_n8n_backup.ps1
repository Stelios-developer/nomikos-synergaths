param(
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [Parameter(Mandatory = $true)][string]$KeyPath
)

$ErrorActionPreference = 'Stop'
$backup = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $BackupPath).Path)
if ($backup.Length -lt 37 -or $backup.Length -gt 512MB -or
    [Text.Encoding]::ASCII.GetString($backup, 0, 8) -ne 'NEXUSBK1') {
    throw 'Invalid or oversized Documents Made Clear backup.'
}
$context = [Text.Encoding]::UTF8.GetBytes('NEXUS n8n local volume backup v1')
$key = [Security.Cryptography.ProtectedData]::Unprotect(
    [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $KeyPath).Path),
    $context, [Security.Cryptography.DataProtectionScope]::CurrentUser
)
$nonce = [byte[]]::new(12)
$tag = [byte[]]::new(16)
$cipher = [byte[]]::new($backup.Length - 36)
[Array]::Copy($backup, 8, $nonce, 0, 12)
[Array]::Copy($backup, 20, $tag, 0, 16)
[Array]::Copy($backup, 36, $cipher, 0, $cipher.Length)
$archive = [byte[]]::new($cipher.Length)
$aes = [Security.Cryptography.AesGcm]::new($key, 16)
try { $aes.Decrypt($nonce, $cipher, $tag, $archive) }
finally { $aes.Dispose(); [Array]::Clear($key) }

# The live n8n volume is never mounted. Restore into a unique test volume,
# validate the database, then remove only the volume created by this run.
$runId = [Guid]::NewGuid().ToString('N')
$volume = "nexus-backup-verify-$runId"
$existing = docker volume ls --format '{{.Name}}'
if ($LASTEXITCODE -ne 0 -or $existing -contains $volume) { throw 'Cannot reserve a fresh restore-test volume.' }
docker volume create --label "nexus.restore-drill=$runId" $volume | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not create the restore-test volume.' }

$python = @'
import io,json,pathlib,sqlite3,sys,tarfile
root=pathlib.Path('/restore')
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:') as archive:
    for member in archive.getmembers():
        if not member.name.startswith('n8n_data/') and member.name != 'n8n_data':
            raise ValueError('Unexpected backup root')
        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise ValueError('Unsupported backup entry')
    archive.extractall(root,filter='data')
database=root/'n8n_data'/'database.sqlite'
connection=sqlite3.connect(f'file:{database}?mode=ro',uri=True)
assert connection.execute('pragma integrity_check').fetchone()[0]=='ok'
assert connection.execute('pragma foreign_key_check').fetchall()==[]
counts={table:connection.execute(f'select count(*) from {table}').fetchone()[0]
        for table in ('workflow_entity','execution_entity','execution_data')}
connection.close()
print(json.dumps({'integrity':'ok','counts':counts}))
'@

try {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = 'docker'
    $info.UseShellExecute = $false
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in @(
        'run', '--rm', '-i', '--network', 'none', '--read-only', '--user', '0:0',
        '--mount', "type=volume,src=$volume,dst=/restore",
        '--entrypoint', 'python', 'pdf_worker-pdf-worker:latest', '-c', $python
    )) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($info)
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.BaseStream.Write($archive, 0, $archive.Length)
    $process.StandardInput.Close()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Restore drill failed: $($stderr.Result.Trim())" }
    Write-Output $stdout.Result.Trim()
} finally {
    [Array]::Clear($archive)
    $label = docker volume inspect --format '{{index .Labels "nexus.restore-drill"}}' $volume
    if ($LASTEXITCODE -ne 0 -or $label.Trim() -ne $runId) {
        throw "Restore-test volume ownership could not be verified: $volume"
    }
    docker volume rm $volume | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not remove the exact restore-test volume: $volume" }
    Write-Output 'Temporary restore-test volume removed; encrypted backup retained.'
}
