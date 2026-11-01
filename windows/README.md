# NFS2S3 — Version Windows native

Application Windows 10/11 x64, sans WSL2, Bash ou environnement Linux.
Interface en français et thème sombre.

## Lancer en développement

PowerShell :

    py -3.12 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r windows\requirements.txt
    python windows\nfs2s3_windows.py

## Construire l'exécutable

    pip install pyinstaller
    pyinstaller --noconfirm --clean --onefile --windowed --name NFS2S3 --add-data "windows/nfs2s3_engine.py;." windows/nfs2s3_windows.py

Le binaire se trouve dans dist\NFS2S3.exe. GitHub Actions construit une archive portable Windows x64 à chaque push/PR sur cette branche et publie l'archive lors d'un tag windows-v*.

## Source NFS sous Windows

Cette version n'utilise pas WSL2. Le chemin source doit être un dossier Windows accessible (par exemple un lecteur réseau monté). Pour un serveur NFS, activez/installez le Client pour NFS dans les fonctionnalités Windows prises en charge par votre édition, puis montez l'export NFS avec les outils Windows. L'application ne monte pas elle-même les exports NFS.

## Transfert S3

Le moteur Python utilise boto3 directement. Les objets transférés par cette application portent la métadonnée nfs2s3-md5, utilisée pour éviter les recopies lorsque le checksum correspond. Les objets préexistants sans cette métadonnée sont retransférés en mode checksum. Le mode taille ne compare que les tailles et offre une garantie plus faible.

Le transfert est non destructif : aucun objet n'est supprimé du bucket et aucun fichier source n'est supprimé. Le mode immuable refuse de remplacer un objet existant différent. Le mode simulation n'effectue pas d'upload.

Les identifiants saisis dans l'interface sont transmis au processus via les variables d'environnement AWS et ne sont pas ajoutés à la ligne de commande. En production, préférez un profil AWS ou des identifiants temporaires IAM à privilèges minimaux.

## Limites actuelles

- Cible de build : Windows x64. ARM64 n'est pas encore fourni.
- L'export NFS doit être monté par Windows avant l'exécution.
- La reprise s'effectue au niveau des fichiers : boto3 gère les reprises multipart pendant un upload, mais le moteur ne persiste pas un upload multipart interrompu entre deux lancements.
- La validation checksum s'appuie sur la métadonnée MD5 créée par cette application, et non sur l'ETag S3 (qui n'est pas toujours un MD5).
- Le contrôle de limite de bande passante et le rapport détaillé par fichier restent à ajouter.
