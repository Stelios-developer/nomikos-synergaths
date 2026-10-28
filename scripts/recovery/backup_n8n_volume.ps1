param(
    [string]$VolumeName = 'n8n_n8n_data',
    [string]$BackupDirectory = 'output/security-backups'
)

$ErrorActionPreference = 'Stop'

# Run only while n8n is stopped. This is an encrypted, current-user-local
# recovery copy; it never writes a plaintext volume archive to disk.
$containerState = docker inspect --format '{{.State.Running}}' document-rag-n8n
if ($LASTEXITCODE -ne 0 -or $containerState.Trim() -ne 'false') {
    throw 'Stop document-rag-n8n before taking a consistent volume backup.'
}
$volumeId = docker volume inspect --format '{{.Name}}' $VolumeName
if ($LASTEXITCODE -ne 0 -or $volumeId.Trim() -ne $VolumeName) {
    throw 'The exact n8n volume could not be verified.'
}

$destination = [IO.Path]::GetFullPath((Join-Path (Get-Location) $BackupDirectory))
if (-not $destination.StartsWith([IO.Path]::GetFullPath((Get-Location).Path + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Backup target must stay inside the repository.'
}
[IO.Directory]::CreateDirectory($destination) | Out-Null

$processInfo = [Diagnostics.ProcessStartInfo]::new()
$processInfo.FileName = 'docker'
$processInfo.UseShellExecute = $false
$processInfo.RedirectStandardOutput = $true
$processInfo.RedirectStandardError = $true
foreach ($argument in @(
    'run', '--rm', '--read-only', '--network', 'none', '--user', '0:0',
    '--mount', "type=volume,src=$VolumeName,dst=/snapshot,readonly",
    '--entrypoint', 'python', 'pdf_worker-pdf-worker:latest', '-c',
    'import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode="w|"); t.add("/snapshot",arcname="n8n_data"); t.close()'
)) { $processInfo.ArgumentList.Add($argument) }

$process = [Diagnostics.Process]::Start($processInfo)
$stderr = $process.StandardError.ReadToEndAsync()
$archive = [IO.MemoryStream]::new()
try {
    $process.StandardOutput.BaseStream.CopyTo($archive)
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "Volume snapshot failed: $($stderr.Result.Trim())"
    }
    $plaintext = $archive.ToArray()
    if ($plaintext.Length -lt 1024) { throw 'Volume snapshot was unexpectedly small.' }

    $stream = [IO.MemoryStream]::new($plaintext, $false)
    $reader = [System.Formats.Tar.TarReader]::new($stream)
    $foundDatabase = $false
    try {
        while ($entry = $reader.GetNextEntry()) {
            if ($entry.Name -eq 'n8n_data/database.sqlite') { $foundDatabase = $true }
        }
    } finally { $reader.Dispose(); $stream.Dispose() }
    if (-not $foundDatabase) { throw 'Volume snapshot is missing the n8n SQLite database.' }

    $key = [byte[]]::new(32)
    $nonce = [byte[]]::new(12)
    [Security.Cryptography.RandomNumberGenerator]::Fill($key)
    [Security.Cryptography.RandomNumberGenerator]::Fill($nonce)
    $ciphertext = [byte[]]::new($plaintext.Length)
    $tag = [byte[]]::new(16)
    $aes = [Security.Cryptography.AesGcm]::new($key, 16)
    try { $aes.Encrypt($nonce, $plaintext, $ciphertext, $tag) }
    finally { $aes.Dispose() }

    $context = [Text.Encoding]::UTF8.GetBytes('NEXUS n8n local volume backup v1')
    $protectedKey = [Security.Cryptography.ProtectedData]::Protect(
        $key, $context, [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    $stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $base = Join-Path $destination "n8n-volume-$stamp"
    $encryptedPath = "$base.tar.aesgcm"
    $keyPath = "$base.key.dpapi"
    if ([IO.File]::Exists($encryptedPath) -or [IO.File]::Exists($keyPath)) {
        throw 'Backup target already exists.'
    }
    $magic = [Text.Encoding]::ASCII.GetBytes('NEXUSBK1')
    $output = [byte[]]::new($magic.Length + $nonce.Length + $tag.Length + $ciphertext.Length)
    [Array]::Copy($magic, 0, $output, 0, $magic.Length)
    [Array]::Copy($nonce, 0, $output, $magic.Length, $nonce.Length)
    [Array]::Copy($tag, 0, $output, $magic.Length + $nonce.Length, $tag.Length)
    [Array]::Copy($ciphertext, 0, $output, $magic.Length + $nonce.Length + $tag.Length, $ciphertext.Length)
    [IO.File]::WriteAllBytes($encryptedPath, $output)
    [IO.File]::WriteAllBytes($keyPath, $protectedKey)

    # Restore-test the written files in memory before declaring success.
    $saved = [IO.File]::ReadAllBytes($encryptedPath)
    $savedKey = [Security.Cryptography.ProtectedData]::Unprotect(
        [IO.File]::ReadAllBytes($keyPath), $context, [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    $restored = [byte[]]::new($saved.Length - 36)
    $savedNonce = $saved[8..19]
    $savedTag = $saved[20..35]
    $savedCipher = $saved[36..($saved.Length - 1)]
    $aes = [Security.Cryptography.AesGcm]::new($savedKey, 16)
    try { $aes.Decrypt($savedNonce, $savedCipher, $savedTag, $restored) }
    finally { $aes.Dispose() }
    if (-not [Security.Cryptography.CryptographicOperations]::FixedTimeEquals($plaintext, $restored)) {
        throw 'Encrypted backup did not pass restore verification.'
    }
    Write-Output "Verified encrypted backup: $encryptedPath"
    Write-Output "Current-user DPAPI key: $keyPath"
    Write-Output "Archive bytes: $($plaintext.Length)"
} finally {
    $archive.Dispose()
}
