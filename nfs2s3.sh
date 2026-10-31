#!/usr/bin/env bash
#===============================================================================
# nfs2s3.sh — Copie un répertoire NFS vers un bucket S3 sans risque de perte
#
#   * copie idempotente et reprenable (aucune suppression, ni source ni S3)
#   * barre de progression, débit, ETA et date/heure de fin estimée
#   * vérification d'intégrité après copie (taille / checksum / relecture)
#   * journal horodaté + rapport fichier par fichier
#
# Dépendances : rclone, jq, flock, numfmt (coreutils)
# Reprise : relancer la même commande reprend là où ça s'est arrêté ; en cas de
#           coupure (réseau, S3, NFS) le script réessaie seul (-R / -w).
# Codes retour : 0 OK | 1 erreur de copie | 2 vérification en échec | 64 usage
#===============================================================================
set -euo pipefail

SRC=""; DEST=""; ENDPOINT=""; INSECURE=0; TRANSFERS=8; BWLIMIT=""
VERIFY="checksum"; DRYRUN=0; MINAGE=""; EXCLUDE_FILE=""; LOGDIR="./nfs2s3_logs"
PRESCAN=1; RETRIES=3; MAX_ATTEMPTS=10; WAIT=60; IMMUTABLE=0; FOLLOW_LINKS=0; VERBOSE=0
CHUNK="${CHUNK:-32M}"           # taille des parts multipart (RAM ~ transfers x 4 x CHUNK)
TOTAL_BYTES=0; TOTAL_FILES=0; LOG=""

if [[ -t 2 ]]; then RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; RST=$'\033[0m'
else RED=""; YEL=""; GRN=""; RST=""; fi

info() { printf '%s\n' "$*"; if [[ -n $LOG ]]; then printf '%s\n' "$*" >>"$LOG"; fi; }
warn() { printf '%sATTENTION :%s %s\n' "$YEL" "$RST" "$*" >&2; }
die()  { printf '%sERREUR :%s %s\n' "$RED" "$RST" "$1" >&2; exit "${2:-1}"; }
hsize() { numfmt --to=iec-i --suffix=B "${1:-0}"; }
fmt_dur() { local s=$1; printf '%dh%02dm%02ds' $((s / 3600)) $((s % 3600 / 60)) $((s % 60)); }

usage() {
  cat <<EOF
Usage : ${0##*/} -s SOURCE -d DEST [options]

  -s DIR    Répertoire source (montage NFS)                          [obligatoire]
  -d DEST   Destination : "bucket/prefixe" (avec -e)  ou  "remote:bucket/prefixe"
            si le remote existe déjà dans ~/.config/rclone/rclone.conf [obligatoire]
  -e URL    Endpoint S3 (ex. https://s3.example.local). Les clés sont lues dans
            AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (jamais en ligne de commande)
  -k        Ne pas vérifier le certificat TLS (certificat auto-signé)
  -t N      Transferts en parallèle (défaut : $TRANSFERS)
  -b RATE   Limite de bande passante, ex. 50M, ou planning "08:00,20M 20:00,off"
  -V MODE   Vérification après copie (défaut : $VERIFY)
              none      aucune
              size      tailles uniquement (rapide, faible garantie)
              checksum  comparaison des empreintes MD5 (recommandé)
              download  relit tout depuis S3 et compare octet par octet (le plus sûr)
  -a AGE    Ignorer les fichiers modifiés depuis moins de AGE (ex. 10m, 1h) :
            évite de copier des fichiers encore en cours d'écriture
  -x FILE   Fichier de motifs à exclure (syntaxe rclone --exclude-from)
  -i        Immuable : n'écrase jamais un objet S3 existant et différent (erreur)
  -L        Suivre les liens symboliques (ignorés par défaut)
  -P        Ne pas faire de pré-scan (démarre plus vite, ETA moins précise)
  -r N      Passes de réessai internes à rclone (défaut : $RETRIES)
  -R N      Tentatives de reprise automatique après coupure, 0 = illimité (défaut : $MAX_ATTEMPTS)
  -w SEC    Attente avant la 1re reprise, doublée à chaque échec, plafonnée à 15 min (défaut : ${WAIT}s)
  -l DIR    Répertoire des journaux (défaut : $LOGDIR)
  -n        Simulation : liste ce qui serait copié, n'écrit rien
  -v        Journal détaillé (une ligne par fichier copié)
  -h        Cette aide

Exemple :
  export AWS_ACCESS_KEY_ID=xxxx AWS_SECRET_ACCESS_KEY=yyyy
  ${0##*/} -s /mnt/nfs/data -d mon-bucket/archive -e https://s3.example.local \\
           -t 16 -b 200M -a 10m -V checksum

Relancer la même commande reprend là où le transfert s'est arrêté.
EOF
}

while getopts ":s:d:e:kt:b:V:na:x:l:Pr:R:w:iLvh" opt; do
  case $opt in
    s) SRC=$OPTARG ;;        d) DEST=$OPTARG ;;      e) ENDPOINT=$OPTARG ;;
    k) INSECURE=1 ;;         t) TRANSFERS=$OPTARG ;; b) BWLIMIT=$OPTARG ;;
    V) VERIFY=$OPTARG ;;     n) DRYRUN=1 ;;          a) MINAGE=$OPTARG ;;
    x) EXCLUDE_FILE=$OPTARG ;; l) LOGDIR=$OPTARG ;;  P) PRESCAN=0 ;;
    r) RETRIES=$OPTARG ;;    R) MAX_ATTEMPTS=$OPTARG ;; w) WAIT=$OPTARG ;;    i) IMMUTABLE=1 ;;       L) FOLLOW_LINKS=1 ;;
    v) VERBOSE=1 ;;          h) usage; exit 0 ;;
    :)  echo "Option -$OPTARG : argument manquant" >&2; exit 64 ;;
    \?) echo "Option inconnue : -$OPTARG" >&2; usage >&2; exit 64 ;;
  esac
done

[[ -n $SRC && -n $DEST ]] || { usage >&2; exit 64; }
[[ $TRANSFERS =~ ^[0-9]+$ ]] && (( TRANSFERS >= 1 )) || die "-t doit être un entier >= 1" 64
[[ $RETRIES =~ ^[0-9]+$ && $MAX_ATTEMPTS =~ ^[0-9]+$ && $WAIT =~ ^[0-9]+$ ]] || die "-r, -R et -w doivent être des entiers" 64
case $VERIFY in none|size|checksum|download) ;; *) die "-V : none|size|checksum|download" 64 ;; esac
[[ -z $EXCLUDE_FILE || -r $EXCLUDE_FILE ]] || die "Fichier d'exclusion illisible : $EXCLUDE_FILE" 64

for c in rclone jq flock numfmt timeout; do
  command -v "$c" >/dev/null || die "Commande manquante : $c (rclone : paquet EPEL ou binaire officiel rclone.org)"
done

# --- Source -------------------------------------------------------------------
[[ -d $SRC && -r $SRC ]] || die "Source introuvable ou illisible : $SRC"
timeout 15 stat -t "$SRC" >/dev/null 2>&1 || die "La source ne répond pas (montage NFS bloqué ?) : $SRC"
fstype=$(stat -f -c %T "$SRC" 2>/dev/null || echo "?")
[[ $fstype == nfs* ]] || warn "La source n'est pas détectée comme NFS (type : $fstype)"

# --- Destination S3 -------------------------------------------------------------
if [[ $DEST != *:* ]]; then
  [[ -n $ENDPOINT ]] || die "-e ENDPOINT est requis quand DEST est de la forme bucket/prefixe" 64
  [[ -n ${AWS_ACCESS_KEY_ID:-} && -n ${AWS_SECRET_ACCESS_KEY:-} ]] \
    || die "Exporter AWS_ACCESS_KEY_ID et AWS_SECRET_ACCESS_KEY avant de lancer le script" 64
  export RCLONE_CONFIG_NFS2S3_TYPE=s3 RCLONE_CONFIG_NFS2S3_PROVIDER=Other
  export RCLONE_CONFIG_NFS2S3_ENV_AUTH=true RCLONE_CONFIG_NFS2S3_ENDPOINT="$ENDPOINT"
  export RCLONE_CONFIG_NFS2S3_FORCE_PATH_STYLE=true RCLONE_CONFIG_NFS2S3_NO_CHECK_BUCKET=true
  DEST="NFS2S3:$DEST"
fi

# --- Verrou : une seule exécution par couple source/destination ----------------
LOCK="/tmp/nfs2s3_$(printf '%s|%s' "$SRC" "$DEST" | md5sum | cut -c1-12).lock"
exec 9>"$LOCK"
flock -n 9 || die "Une autre exécution est déjà en cours (verrou : $LOCK)"

# --- Journaux -------------------------------------------------------------------
mkdir -p "$LOGDIR"
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$LOGDIR/nfs2s3_$STAMP.log"
REPORT="$LOGDIR/nfs2s3_$STAMP.report.txt"
: >"$LOG"

# --- Options rclone ----------------------------------------------------------------
COMMON=(--transfers "$TRANSFERS" --checkers $(( TRANSFERS * 2 )) --retries "$RETRIES"
        --low-level-retries 10 --s3-chunk-size "$CHUNK")
SCOPE=()
[[ -n $MINAGE ]]       && SCOPE+=(--min-age "$MINAGE")
[[ -n $EXCLUDE_FILE ]] && SCOPE+=(--exclude-from "$EXCLUDE_FILE")
(( FOLLOW_LINKS ))     && SCOPE+=(--copy-links)
[[ -n $BWLIMIT ]]      && COMMON+=(--bwlimit "$BWLIMIT")
(( INSECURE ))         && COMMON+=(--no-check-certificate)
(( IMMUTABLE ))        && COMMON+=(--immutable)

if [[ -t 1 ]]; then CR=$'\r'; CLR=$'\033[K'; NL=""; STATS=${STATS_INTERVAL:-2s}
else CR=""; CLR=""; NL=$'\n'; STATS=${STATS_INTERVAL:-60s}; fi

trap 'echo; warn "Interrompu. Relancer la même commande reprend le transfert (fichiers déjà copiés ignorés)."; exit 130' INT TERM

info "== nfs2s3 — $(date '+%d/%m/%Y %H:%M:%S')"
info "Source      : $SRC ($fstype)"
info "Destination : ${DEST#NFS2S3:}${ENDPOINT:+  [endpoint $ENDPOINT]}"
info "Parallélisme: $TRANSFERS transferts | vérification : $VERIFY | bwlimit : ${BWLIMIT:-aucune}"
info "Journal     : $LOG"

# --- Simulation -----------------------------------------------------------------------
if (( DRYRUN )); then
  info "Mode simulation : rien ne sera écrit."
  rclone copy "$SRC" "$DEST" "${COMMON[@]}" "${SCOPE[@]}" --dry-run --log-level INFO 2>&1 | tee -a "$LOG"
  exit 0
fi

# --- Reprise détectée ? Sinon pré-scan : volume total pour une ETA fiable ----------------------
RESUMED=0
if [[ -n $(rclone lsf "$DEST" --max-depth 1 "${COMMON[@]}" 2>/dev/null | head -n 1) ]]; then RESUMED=1; fi
if (( RESUMED )); then
  info "Reprise détectée : la destination contient déjà des données. Seuls les fichiers manquants ou"
  info "différents seront copiés ; la barre est calculée sur le reste à copier."
elif (( PRESCAN )); then
  info "Pré-scan de la source (peut durer sur une grosse arborescence)…"
  scan=$(rclone size "$SRC" --json "${SCOPE[@]}" 2>>"$LOG") || die "Échec du pré-scan (voir $LOG)"
  TOTAL_BYTES=$(jq -r '.bytes' <<<"$scan"); TOTAL_FILES=$(jq -r '.count' <<<"$scan")
  info "→ $TOTAL_FILES fichiers, $(hsize "$TOTAL_BYTES")"
fi

# --- Affichage de la progression à partir des stats JSON de rclone ---------------------------------
render_progress() {
  local line b t sp eta errs total pct f bar pad end_s eta_s w=30
  while IFS= read -r line; do
    printf '%s\n' "$line" >>"$LOG"
    [[ $line == '{'*'"stats":'* ]] || continue
    read -r b t sp eta errs < <(jq -r '.stats | [.bytes, .totalBytes, .speed, (.eta // -1), .errors] | map(floor) | @tsv' <<<"$line" 2>/dev/null) || continue
    total=$TOTAL_BYTES; if (( t > total )); then total=$t; fi
    pct=0; if (( total > 0 )); then pct=$(( b * 100 / total )); fi
    if (( pct > 100 )); then pct=100; fi
    if (( TOTAL_BYTES > 0 && sp > 0 && total >= b )); then eta=$(( (total - b) / sp )); fi
    f=$(( pct * w / 100 ))
    printf -v bar '%*s' "$f" ''; bar=${bar// /#}
    printf -v pad '%*s' "$(( w - f ))" ''; pad=${pad// /-}
    if (( eta >= 0 )); then
      printf -v end_s '%(%d/%m/%Y %H:%M)T' "$(( EPOCHSECONDS + eta ))"
      eta_s=$(fmt_dur "$eta")
    else
      end_s="calcul…"; eta_s="calcul…"
    fi
    printf '%s[%s%s] %3d%%  %s / %s  %s/s  ETA %s  fin ≈ %s  err:%s%s%s' \
      "$CR" "$bar" "$pad" "$pct" "$(hsize "$b")" "$(hsize "$total")" "$(hsize "$sp")" \
      "$eta_s" "$end_s" "$errs" "$CLR" "$NL"
  done
  printf '\n'
}

# --- Attente de la source NFS (reprise après coupure) -------------------------------------------
wait_source() {
  until [[ -d $SRC ]] && timeout 15 stat -t "$SRC" >/dev/null 2>&1; do
    warn "Source NFS indisponible — nouvelle vérification dans 30 s…"; sleep 30
  done
}

# --- Copie avec reprise automatique (jamais de suppression : "copy" et non "sync"/"move") -------
LOGLEVEL=NOTICE; if (( VERBOSE )); then LOGLEVEL=INFO; fi
START=$SECONDS; attempt=1; rc_copy=0
while :; do
  wait_source
  maxlabel=""; if (( MAX_ATTEMPTS > 0 )); then maxlabel="/$MAX_ATTEMPTS"; fi
  info "Copie en cours (tentative $attempt$maxlabel)…"
  set +e
  rclone copy "$SRC" "$DEST" "${COMMON[@]}" "${SCOPE[@]}" \
    --use-json-log --log-level "$LOGLEVEL" --stats "$STATS" --stats-log-level NOTICE 2>&1 >/dev/null | render_progress
  rc_copy=${PIPESTATUS[0]}
  set -e
  if (( rc_copy == 0 )); then break; fi
  case $rc_copy in 2|3|4|7) warn "Erreur non récupérable (code rclone $rc_copy) — voir $LOG"; break ;; esac
  if (( MAX_ATTEMPTS > 0 && attempt >= MAX_ATTEMPTS )); then
    warn "Abandon après $attempt tentatives — relancer la commande pour reprendre."; break
  fi
  delay=$(( WAIT * (1 << (attempt > 6 ? 6 : attempt - 1)) )); if (( delay > 900 )); then delay=900; fi
  warn "Interruption (code $rc_copy). Reprise automatique dans ${delay}s — les fichiers déjà copiés seront ignorés."
  sleep "$delay"
  attempt=$(( attempt + 1 )); TOTAL_BYTES=0   # après une reprise, la progression suit le reste à copier
done
if (( rc_copy != 0 )); then warn "La copie s'est terminée avec des erreurs (code $rc_copy) — voir $LOG"; fi

# --- Vérification d'intégrité ---------------------------------------------------------------------------
verify() {
  local args=() prog=() rc=0 bad total
  case $VERIFY in size) args=(--size-only) ;; download) args=(--download) ;; esac
  if [[ -t 1 ]]; then prog=(--progress); fi
  info "Vérification d'intégrité (mode : $VERIFY)…"
  rclone check "$SRC" "$DEST" --one-way "${args[@]}" "${prog[@]}" "${COMMON[@]}" "${SCOPE[@]}" \
    --combined "$REPORT" --log-file "$LOG" --log-level NOTICE || rc=$?
  [[ -f $REPORT ]] || { warn "Rapport de vérification absent — voir $LOG"; return 2; }
  bad=$(grep -vc '^= ' "$REPORT" || true)
  total=$(wc -l <"$REPORT")
  if (( rc == 0 && bad == 0 )); then
    info "${GRN}✔ Intégrité OK${RST} : $total fichiers vérifiés, 0 écart."
    if grep -q 'could not be checked' "$LOG"; then
      warn "Certains fichiers n'ont pas d'empreinte comparable : relancer avec -V download pour une preuve complète."
    fi
    return 0
  fi
  warn "$bad écart(s) détecté(s) (+ manquant sur S3, * différent, ! erreur) — extrait :"
  grep -v '^= ' "$REPORT" | head -n 20 >&2
  return 2
}

rc_verify=0
if [[ $VERIFY != none ]]; then verify || rc_verify=$?
else warn "Vérification désactivée (-V none) : aucune garantie d'intégrité."; fi

# --- Bilan -------------------------------------------------------------------------------------------------
info "Durée : $(fmt_dur $(( SECONDS - START ))) | rapport : $REPORT"
if (( rc_copy != 0 )); then exit 1; fi
if (( rc_verify != 0 )); then exit 2; fi
info "${GRN}Terminé sans erreur.${RST} La source n'a pas été modifiée : à toi de décider quand la supprimer."
