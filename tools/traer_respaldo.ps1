# Trae a esta PC el respaldo más nuevo de la base del Jetson.
#
# Por qué: los respaldos diarios (src/storage/respaldos.py) quedan en el SSD
# del Jetson y en su disco USB: el MISMO equipo. Un robo, una inundación o un
# Jetson que no vuelve a arrancar se llevan las dos copias, y con ellas los
# aforos entregados (7, 9, 26, 27 y 28) con su calibración. Esta es la copia
# fuera del equipo.
#
# Usa la llave SSH que ya tiene esta PC (la misma del despliegue). Una vez,
# para que corra solo cada día a las 9:00 (con la PC encendida):
#
#   schtasks /Create /SC DAILY /ST 09:00 /TN "Aforo - traer respaldo" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File D:\vehicle-traffic-counter\tools\traer_respaldo.ps1"
#
# Restaurar es lo mismo que con un respaldo local: ver respaldos.py.

param(
    [string]$Jetson = "apia@10.197.1.156",
    [string]$Destino = "D:\aforo_respaldos",
    [int]$Conservar = 30
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Destino | Out-Null
$bitacora = Join-Path $Destino "bitacora.txt"

function Anotar($texto) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm')  $texto" | Out-File -Append -Encoding utf8 $bitacora
}

try {
    # Solo los automáticos (traffic_AAAA-MM-DD_HHMM.db), igual que respaldos.listar().
    $remoto = ssh -o BatchMode=yes -o ConnectTimeout=15 $Jetson `
        "ls -1 ~/vehicle-traffic-counter/data/respaldos/ | grep -E '^traffic_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.db$' | sort | tail -1"
    if (-not $remoto) { throw "el Jetson no tiene respaldos" }
    $remoto = $remoto.Trim()
    $local = Join-Path $Destino $remoto
    if (Test-Path $local) {
        Anotar "ya estaba $remoto"
        exit 0
    }
    scp -q -o BatchMode=yes "${Jetson}:~/vehicle-traffic-counter/data/respaldos/$remoto" "$local.parcial"
    if ($LASTEXITCODE -ne 0) { throw "scp falló ($LASTEXITCODE)" }
    Move-Item -Force "$local.parcial" $local
    $mb = [math]::Round((Get-Item $local).Length / 1MB, 1)
    Anotar "traído $remoto ($mb MB)"

    Get-ChildItem $Destino -Filter "traffic_*.db" | Sort-Object Name -Descending |
        Select-Object -Skip $Conservar | Remove-Item -Force
}
catch {
    Anotar "ERROR: $_"
    exit 1
}
