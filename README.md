# nfs2s3

Copie un répertoire NFS vers un bucket S3 (Scality ou compatible) **sans risque de perte**, avec barre de progression, estimation de fin, reprise automatique et vérification d'intégrité. S'appuie sur [rclone](https://rclone.org).

## Principes de sécurité

- `rclone copy` uniquement : **aucune suppression**, ni côté source ni côté S3.
- Idempotent : relancer la même commande reprend là où le transfert s'est arrêté.
- Reprise automatique après coupure (réseau, S3, NFS) avec attente croissante.
- Vérification après copie : `size`, `checksum` (MD5) ou `download` (relecture complète).
- Journal horodaté et rapport fichier par fichier dans `nfs2s3_logs/`.

## Prérequis

`rclone`, `jq`, `flock`, `numfmt` (coreutils), bash 5. Sur RHEL 9, `rclone` est disponible via EPEL ou en binaire officiel.

## Utilisation

```bash
export AWS_ACCESS_KEY_ID='...'
export AWS_SECRET_ACCESS_KEY='...'

./nfs2s3.sh -s /mnt/nfs/projets -d mon-bucket/prefixe -e https://s3.exemple.local \
  -t 16 -b "08:00,100M 20:00,500M" -a 15m -V checksum -R 0 -w 30
```

`-d mon-bucket/prefixe` : le bucket (qui doit exister) puis un préfixe optionnel. `-d mon-bucket` copie à la racine.
Avec un remote déjà défini dans `rclone.conf` : `-d remote:mon-bucket/prefixe` (sans `-e`).

## Options

| Option | Rôle |
|---|---|
| `-s DIR` | Répertoire source (NFS) |
| `-d DEST` | `bucket/prefixe` (avec `-e`) ou `remote:bucket/prefixe` |
| `-e URL` | Endpoint S3 ; clés via `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| `-k` | Ne pas vérifier le certificat TLS |
| `-t N` | Transferts en parallèle (défaut 8) |
| `-b RATE` | Limite de débit, ex. `50M` ou `"08:00,20M 20:00,off"` |
| `-V MODE` | `none`, `size`, `checksum` (défaut), `download` |
| `-a AGE` | Ignorer les fichiers modifiés depuis moins de AGE (ex. `15m`) |
| `-x FILE` | Fichier de motifs à exclure |
| `-i` | N'écrase jamais un objet S3 existant et différent |
| `-L` | Suivre les liens symboliques |
| `-P` | Pas de pré-scan |
| `-r N` | Réessais internes de rclone (défaut 3) |
| `-R N` | Tentatives de reprise automatique, `0` = illimité (défaut 10) |
| `-w SEC` | Attente avant la 1re reprise, doublée à chaque échec (max 15 min) |
| `-l DIR` | Répertoire des journaux |
| `-n` | Simulation, rien n'est écrit |
| `-v` | Journal détaillé |

## Codes retour

`0` OK, `1` erreur de copie, `2` vérification en échec, `64` erreur d'usage.

## Limites

- Un fichier interrompu est recopié depuis le début, pas depuis l'octet atteint.
- Une coupure peut laisser des envois multipart incomplets sur S3 : `rclone cleanup remote:bucket`.
- Pour une longue copie, lancer dans `tmux` ou via `systemd-run`.
