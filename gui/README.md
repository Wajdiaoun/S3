# NFS2S3 — Interface graphique

Application de bureau Linux en thème sombre pour piloter le moteur existant nfs2s3.sh.

## Installation simple

Téléchargez NFS2S3-x86_64.AppImage depuis GitHub Releases, puis exécutez :

    chmod +x NFS2S3-x86_64.AppImage
    ./NFS2S3-x86_64.AppImage

Pour l'installer dans le menu des applications :

    ./scripts/install-appimage.sh NFS2S3-x86_64.AppImage

L'AppImage embarque l'interface, rclone et jq. Le système doit fournir bash, flock, numfmt, timeout et stat. Sur Debian/Ubuntu, ces commandes sont fournies par coreutils et util-linux. Le montage NFS doit déjà être accessible.

## Configuration S3

Pour une destination bucket/prefixe, renseignez l'endpoint et les deux clés S3. Pour remote:bucket/prefixe, configurez au préalable le remote dans ~/.config/rclone/rclone.conf et laissez les champs d'identifiants vides.

Les clés sont masquées et transmises au processus via son environnement, pas dans les arguments du script.

## Développement

    python3 -m venv .venv
    . .venv/bin/activate
    pip install PySide6
    python gui/s3_gui.py

Le script nfs2s3.sh reste à la racine du dépôt.

## Compatibilité

Les versions publiées sont des AppImages x86_64 construites sur Ubuntu 22.04. Elles visent les distributions Linux modernes de cette architecture. Ce n'est pas un binaire universel ARM/32 bits. Les systèmes sans FUSE peuvent nécessiter l'extraction AppImage avec --appimage-extract.
