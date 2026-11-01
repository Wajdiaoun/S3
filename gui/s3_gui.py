#!/usr/bin/env python3
"""Interface graphique PySide6 pour nfs2s3.sh."""
import os, shutil, sys, json
from pathlib import Path
from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtWidgets import (QApplication,QCheckBox,QComboBox,QFileDialog,QFormLayout,QFrame,
 QGridLayout,QHBoxLayout,QLabel,QLineEdit,QMainWindow,QMessageBox,QProgressBar,QPushButton,
 QPlainTextEdit,QSpinBox,QTabWidget,QVBoxLayout,QWidget)

STYLE = """
QWidget{background:#10141d;color:#e6eaf2;font-family:'Inter','Segoe UI',sans-serif;font-size:13px}
QMainWindow{background:#0c1018}
QFrame#panel{background:#171e2b;border:1px solid #283449;border-radius:12px}
QLabel#muted{color:#94a3b8}
QLabel#heading{font-size:24px;font-weight:700;color:#f8fafc}
QLabel#metric{font-size:23px;font-weight:700;color:#91a2ff}
QLineEdit,QComboBox,QSpinBox{background:#0e1521;border:1px solid #334155;border-radius:7px;padding:9px;min-height:18px}
QLineEdit:focus,QComboBox:focus,QSpinBox:focus{border:1px solid #7488ff}
QPushButton{background:#283449;border:1px solid #3b4a62;border-radius:8px;padding:10px 15px;font-weight:600}
QPushButton:hover{background:#34445f}
QPushButton#primary{background:#596cf0;border-color:#7182ff;color:white}
QPushButton#danger{background:#672d3b;border-color:#8d4051}
QTabWidget::pane{border:1px solid #283449;border-radius:10px;background:#171e2b}
QTabBar::tab{background:#111824;color:#94a3b8;padding:10px 18px;margin-right:4px;border-radius:6px}
QTabBar::tab:selected{background:#27334a;color:white}
QProgressBar{background:#0c1320;border:1px solid #334155;border-radius:7px;height:18px;text-align:center}
QProgressBar::chunk{background:#6678f4;border-radius:6px}
QPlainTextEdit{background:#0a0f17;color:#b8c7dc;border:1px solid #283449;border-radius:8px;font-family:monospace}
"""

def card():
    w=QFrame(); w.setObjectName("panel"); return w

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NFS2S3 — Console de transfert")
        self.resize(1080,790)
        self.script=Path(os.environ.get("NFS2S3_SCRIPT",Path(__file__).resolve().parent.parent/"nfs2s3.sh"))
        if not self.script.is_file(): self.script=Path("/usr/share/nfs2s3/nfs2s3.sh")
        self.proc=QProcess(self); self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self.output)
        self.proc.finished.connect(self.finished)
        self.proc.errorOccurred.connect(lambda e:self.console.appendPlainText("Erreur processus : "+self.proc.errorString()) if hasattr(self,"console") else None)
        self.build()
        self.check_deps()

    def build(self):
        root=QWidget(); outer=QVBoxLayout(root); outer.setContentsMargins(26,22,26,22); outer.setSpacing(14)
        header=QHBoxLayout(); branding=QVBoxLayout()
        title=QLabel("NFS2S3"); title.setObjectName("heading")
        sub=QLabel("Transfert sécurisé de vos montages NFS vers S3"); sub.setObjectName("muted")
        branding.addWidget(title); branding.addWidget(sub); header.addLayout(branding); header.addStretch()
        self.status=QLabel("● PRÊT"); self.status.setStyleSheet("color:#5ee0ad;font-weight:700"); header.addWidget(self.status)
        outer.addLayout(header)
        self.tabs=QTabWidget(); page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(16,16,16,16); v.setSpacing(12)
        loc=card(); f=QFormLayout(loc); f.setContentsMargins(16,14,16,16); f.setVerticalSpacing(11)
        self.src=QLineEdit(); self.src.setPlaceholderText("/mnt/nfs/donnees")
        row=QHBoxLayout(); row.addWidget(self.src); b=QPushButton("Parcourir…"); b.clicked.connect(self.pick_src); row.addWidget(b); f.addRow("Source NFS",row)
        self.dest=QLineEdit(); self.dest.setPlaceholderText("bucket/prefixe ou remote:bucket/prefixe"); f.addRow("Destination S3",self.dest)
        self.endpoint=QLineEdit(); self.endpoint.setPlaceholderText("https://s3.example.local (facultatif avec remote rclone)"); f.addRow("Endpoint",self.endpoint)
        self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText("AWS Access Key ID"); f.addRow("Access key",self.key)
        self.secret=QLineEdit(); self.secret.setEchoMode(QLineEdit.Password); self.secret.setPlaceholderText("AWS Secret Access Key"); f.addRow("Secret key",self.secret)
        v.addWidget(loc)
        actions=QHBoxLayout(); self.go=QPushButton("▶  Démarrer le transfert"); self.go.setObjectName("primary"); self.go.clicked.connect(self.start)
        self.stop=QPushButton("■  Arrêter"); self.stop.setObjectName("danger"); self.stop.setEnabled(False); self.stop.clicked.connect(self.stop_job)
        self.dry=QCheckBox("Simulation sans écriture")
        actions.addWidget(self.go); actions.addWidget(self.stop); actions.addStretch(); actions.addWidget(self.dry); v.addLayout(actions)
        prog=card(); pv=QVBoxLayout(prog); pv.setContentsMargins(16,14,16,14); pv.addWidget(QLabel("PROGRESSION DU TRANSFERT"))
        self.bar=QProgressBar(); self.bar.setRange(0,100); self.bar.setFormat("En attente"); pv.addWidget(self.bar)
        grid=QGridLayout(); self.metrics={}
        for i,(key,label) in enumerate([("speed","Débit"),("eta","Temps restant"),("files","Fichiers"),("phase","Étape")]):
            box=card(); bl=QVBoxLayout(box); val=QLabel("—"); val.setObjectName("metric"); lab=QLabel(label); lab.setObjectName("muted"); bl.addWidget(val); bl.addWidget(lab); self.metrics[key]=val; grid.addWidget(box,0,i)
        pv.addLayout(grid); v.addWidget(prog); self.tabs.addTab(page,"Transfert")
        adv=QWidget(); av=QVBoxLayout(adv); av.setContentsMargins(16,16,16,16)
        opts=card(); of=QFormLayout(opts); of.setContentsMargins(16,14,16,16)
        self.parallel=QSpinBox(); self.parallel.setRange(1,128); self.parallel.setValue(8); of.addRow("Transferts parallèles",self.parallel)
        self.band=QLineEdit(); self.band.setPlaceholderText("50M ou 08:00,20M 20:00,off"); of.addRow("Limite de débit",self.band)
        self.verify=QComboBox(); self.verify.addItems(["checksum","size","download","none"]); of.addRow("Vérification",self.verify)
        self.age=QLineEdit(); self.age.setPlaceholderText("10m, 1h…"); of.addRow("Âge minimum",self.age)
        self.exclude=QLineEdit(); self.exclude.setPlaceholderText("Fichier de motifs rclone"); ex=QHBoxLayout(); ex.addWidget(self.exclude); eb=QPushButton("Choisir…"); eb.clicked.connect(self.pick_ex); ex.addWidget(eb); of.addRow("Exclusions",ex)
        self.retries=QSpinBox(); self.retries.setRange(0,100); self.retries.setValue(3); of.addRow("Réessais rclone",self.retries)
        self.attempts=QSpinBox(); self.attempts.setRange(0,1000); self.attempts.setValue(10); of.addRow("Reprises (0 = illimité)",self.attempts)
        self.wait=QSpinBox(); self.wait.setRange(1,3600); self.wait.setValue(60); of.addRow("Attente avant reprise (s)",self.wait); av.addWidget(opts)
        flags=card(); fg=QGridLayout(flags); fg.setContentsMargins(16,14,16,14)
        self.immutable=QCheckBox("Ne jamais écraser un objet différent"); self.links=QCheckBox("Suivre les liens symboliques")
        self.tls=QCheckBox("Ignorer la validation TLS"); self.prescan=QCheckBox("Pré-scan pour estimer la progression"); self.prescan.setChecked(True); self.verbose=QCheckBox("Journal détaillé")
        for i,w in enumerate([self.immutable,self.links,self.tls,self.prescan,self.verbose]): fg.addWidget(w,i//2,i%2)
        av.addWidget(flags); av.addStretch(); self.tabs.addTab(adv,"Options avancées")
        logs=QWidget(); lv=QVBoxLayout(logs); lv.setContentsMargins(14,14,14,14)
        top=QHBoxLayout(); top.addWidget(QLabel("JOURNAL D’EXÉCUTION")); top.addStretch(); clear=QPushButton("Effacer"); clear.clicked.connect(lambda:self.console.clear()); top.addWidget(clear); lv.addLayout(top)
        self.console=QPlainTextEdit(); self.console.setReadOnly(True); self.console.setMaximumBlockCount(5000); lv.addWidget(self.console); self.tabs.addTab(logs,"Journal")
        outer.addWidget(self.tabs); foot=QLabel("Copie non destructive • Reprise automatique • Vérification après transfert"); foot.setObjectName("muted"); outer.addWidget(foot)
        self.setCentralWidget(root)

    def check_deps(self):
        missing=[x for x in ["rclone","jq","flock","numfmt","timeout"] if not shutil.which(x)]
        if missing:self.console.appendPlainText("Dépendances absentes : "+", ".join(missing))
        else:self.console.appendPlainText("Dépendances détectées.")
        if not self.script.is_file(): self.console.appendPlainText("ERREUR : moteur nfs2s3.sh introuvable.")

    def pick_src(self):
        p=QFileDialog.getExistingDirectory(self,"Choisir le répertoire source")
        if p:self.src.setText(p)
    def pick_ex(self):
        p,_=QFileDialog.getOpenFileName(self,"Fichier d’exclusion")
        if p:self.exclude.setText(p)

    def start(self):
        src=self.src.text().strip(); dest=self.dest.text().strip()
        if not src or not dest: QMessageBox.warning(self,"Configuration","Indiquez la source et la destination."); return
        if not Path(src).is_dir(): QMessageBox.warning(self,"Source invalide","Répertoire source inaccessible."); return
        if not self.script.is_file(): QMessageBox.critical(self,"Script absent","nfs2s3.sh est introuvable."); return
        if self.proc.state()!=QProcess.NotRunning:return
        if ":" not in dest and (not self.endpoint.text().strip() or not self.key.text() or not self.secret.text()):
            QMessageBox.warning(self,"Identifiants S3","Pour bucket/prefixe, renseignez endpoint et les deux clés."); return
        args=["-s",src,"-d",dest,"-t",str(self.parallel.value()),"-V",self.verify.currentText(),"-r",str(self.retries.value()),"-R",str(self.attempts.value()),"-w",str(self.wait.value())]
        for flag,value in [("-e",self.endpoint.text()),("-b",self.band.text()),("-a",self.age.text()),("-x",self.exclude.text())]:
            if value.strip():args += [flag,value.strip()]
        for checked,flag in [(self.immutable,"-i"),(self.links,"-L"),(self.tls,"-k"),(self.verbose,"-v"),(self.dry,"-n")]:
            if checked.isChecked():args.append(flag)
        if not self.prescan.isChecked():args.append("-P")
        env=QProcessEnvironment.systemEnvironment()
        if self.key.text():env.insert("AWS_ACCESS_KEY_ID",self.key.text())
        if self.secret.text():env.insert("AWS_SECRET_ACCESS_KEY",self.secret.text())
        self.proc.setProcessEnvironment(env)
        self.console.appendPlainText("\\n"+"="*58+"\\nDémarrage : "+src+" → "+dest)
        self.go.setEnabled(False); self.stop.setEnabled(True); self.bar.setValue(0); self.bar.setFormat("Transfert en cours…")
        self.status.setText("● EN COURS"); self.status.setStyleSheet("color:#60a5fa;font-weight:700")
        self.metrics["phase"].setText("Copie")
        self.proc.start("bash",[str(self.script),*args])

    def output(self):
        data=bytes(self.proc.readAllStandardOutput()).decode("utf-8",errors="replace")
        self.console.moveCursor(self.console.textCursor().End); self.console.insertPlainText(data); self.console.ensureCursorVisible()
        for line in data.replace("\\r","\\n").splitlines():
            if '"stats"' not in line: 
                if "Vérification d'intégrité" in line:self.metrics["phase"].setText("Vérification")
                continue
            try:
                s=json.loads(line).get("stats",{}); total=int(s.get("totalBytes") or 0); done=int(s.get("bytes") or 0)
                if total:self.bar.setValue(min(100,int(done*100/total)))
                self.metrics["speed"].setText(self.human(s.get("speed",0))+"/s")
                eta=s.get("eta"); self.metrics["eta"].setText(self.duration(eta) if eta is not None else "—")
                self.metrics["files"].setText(str(s.get("transfers","—")))
            except Exception:pass

    @staticmethod
    def human(n):
        n=float(n or 0)
        for u in ["B","KB","MB","GB","TB"]:
            if n<1024:return f"{n:.1f} {u}"
            n/=1024
        return f"{n:.1f} PB"
    @staticmethod
    def duration(n):
        n=max(0,int(n)); return f"{n//3600:02d}:{n%3600//60:02d}:{n%60:02d}"
    def stop_job(self):
        if self.proc.state()!=QProcess.NotRunning:
            self.proc.terminate()
            if not self.proc.waitForFinished(4000):self.proc.kill()
    def finished(self,code,status):
        self.go.setEnabled(True); self.stop.setEnabled(False)
        ok=code==0; self.status.setText("● TERMINÉ" if ok else f"● ERREUR ({code})")
        self.status.setStyleSheet("color:#5ee0ad;font-weight:700" if ok else "color:#fb7185;font-weight:700")
        self.metrics["phase"].setText("Terminé" if ok else "À vérifier")
        if ok:self.bar.setValue(100); self.bar.setFormat("Terminé")
        self.console.appendPlainText(f"\\nProcessus terminé — code retour : {code}")

def main():
    app=QApplication(sys.argv); app.setApplicationName("NFS2S3"); app.setStyle("Fusion"); app.setStyleSheet(STYLE)
    w=MainWindow(); w.show(); sys.exit(app.exec())
if __name__=="__main__":main()
