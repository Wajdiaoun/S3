#!/usr/bin/env python3
"""Interface NFS2S3 native Windows — aucune dépendance WSL ou Bash."""
import json, os, sys, time
from pathlib import Path
from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtWidgets import (QApplication,QCheckBox,QComboBox,QFileDialog,QFormLayout,
 QHBoxLayout,QLabel,QLineEdit,QMainWindow,QMessageBox,QProgressBar,QPushButton,
 QPlainTextEdit,QSpinBox,QTabWidget,QVBoxLayout,QWidget,QGridLayout,QFrame)

DARK="""
QWidget{background:#10141d;color:#e6eaf2;font-family:'Segoe UI';font-size:13px}
QMainWindow{background:#0c1018}
QLineEdit,QComboBox,QSpinBox{background:#0e1521;border:1px solid #334155;border-radius:7px;padding:9px}
QPushButton{background:#283449;border:1px solid #3b4a62;border-radius:8px;padding:10px 15px;font-weight:600}
QPushButton#go{background:#596cf0;color:white} QPushButton#stop{background:#672d3b}
QTabWidget::pane{border:1px solid #283449;border-radius:10px}
QTabBar::tab{background:#111824;padding:10px 18px} QTabBar::tab:selected{background:#27334a}
QProgressBar{background:#0c1320;border:1px solid #334155;border-radius:7px;height:20px;text-align:center}
QProgressBar::chunk{background:#29ce89;border-radius:6px}
QPlainTextEdit{background:#0a0f17;color:#b8c7dc;border:1px solid #283449;font-family:Consolas}
QFrame#panel{background:#171e2b;border:1px solid #283449;border-radius:12px}
"""
def panel():
    x=QFrame();x.setObjectName("panel");return x
class Window(QMainWindow):
 def __init__(self):
    super().__init__();self.setWindowTitle("NFS2S3 — Windows");self.resize(1050,760)
    self.base=(Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent)
    self.engine=self.base/"nfs2s3_engine.py"
    self.proc=QProcess(self);self.proc.setProcessChannelMode(QProcess.MergedChannels)
    self.proc.readyReadStandardOutput.connect(self.read);self.proc.finished.connect(self.finished)
    self.buffer="";self.started=0;self.build()
 def build(self):
    root=QWidget();v=QVBoxLayout(root);v.setContentsMargins(24,20,24,20)
    h=QHBoxLayout();t=QLabel("NFS2S3");t.setStyleSheet("font-size:28px;font-weight:700");h.addWidget(t)
    h.addWidget(QLabel("  Transfert sécurisé vers Amazon S3"));h.addStretch()
    self.status=QLabel("● PRÊT");self.status.setStyleSheet("color:#5ee0ad;font-weight:bold");h.addWidget(self.status);v.addLayout(h)
    tabs=QTabWidget();page=QWidget();p=QVBoxLayout(page)
    card=panel();f=QFormLayout(card);f.setContentsMargins(16,16,16,16)
    self.src=QLineEdit();b=QPushButton("Parcourir…");b.clicked.connect(self.pick);r=QHBoxLayout();r.addWidget(self.src);r.addWidget(b);f.addRow("Dossier source",r)
    self.bucket=QLineEdit();f.addRow("Bucket S3",self.bucket)
    self.prefix=QLineEdit();f.addRow("Préfixe",self.prefix)
    self.endpoint=QLineEdit();self.endpoint.setPlaceholderText("https://s3.example.com (optionnel)");f.addRow("Endpoint S3",self.endpoint)
    self.region=QLineEdit("eu-west-1");f.addRow("Région AWS",self.region)
    self.ak=QLineEdit();self.ak.setEchoMode(QLineEdit.Password);f.addRow("Access key",self.ak)
    self.sk=QLineEdit();self.sk.setEchoMode(QLineEdit.Password);f.addRow("Secret key",self.sk);p.addWidget(card)
    adv=panel();a=QFormLayout(adv);a.setContentsMargins(16,14,16,14)
    self.workers=QSpinBox();self.workers.setRange(1,64);self.workers.setValue(8);a.addRow("Transferts parallèles",self.workers)
    self.verify=QComboBox();self.verify.addItems(["checksum","size","none"]);a.addRow("Vérification",self.verify)
    self.retry=QSpinBox();self.retry.setRange(1,20);self.retry.setValue(3);a.addRow("Réessais AWS",self.retry)
    self.immutable=QCheckBox("Ne jamais remplacer un objet existant différent")
    self.follow=QCheckBox("Suivre les liens symboliques")
    self.dry=QCheckBox("Simulation (aucune écriture)")
    a.addRow(self.immutable);a.addRow(self.follow);a.addRow(self.dry);p.addWidget(adv)
    actions=QHBoxLayout();self.go=QPushButton("▶  Démarrer");self.go.setObjectName("go");self.go.clicked.connect(self.start)
    self.stop=QPushButton("■  Arrêter");self.stop.setObjectName("stop");self.stop.setEnabled(False);self.stop.clicked.connect(self.stop_job)
    actions.addWidget(self.go);actions.addWidget(self.stop);actions.addStretch();p.addLayout(actions)
    self.bar=QProgressBar();self.bar.setValue(0);self.bar.setFormat("En attente");p.addWidget(self.bar)
    grid=QGridLayout();self.speed=QLabel("—");self.count=QLabel("—");self.errors=QLabel("0")
    for i,(lab,val) in enumerate([("Débit",self.speed),("Fichiers",self.count),("Erreurs",self.errors)]):
        box=panel();z=QVBoxLayout(box);z.addWidget(val);z.addWidget(QLabel(lab));grid.addWidget(box,0,i)
    p.addLayout(grid);tabs.addTab(page,"Configuration & transfert")
    logs=QWidget();lv=QVBoxLayout(logs);self.console=QPlainTextEdit();self.console.setReadOnly(True);lv.addWidget(self.console);tabs.addTab(logs,"Journal")
    v.addWidget(tabs);self.setCentralWidget(root)
 def pick(self):
    d=QFileDialog.getExistingDirectory(self,"Choisir le dossier source")
    if d:self.src.setText(d)
 def start(self):
    source=self.src.text().strip();bucket=self.bucket.text().strip()
    if not Path(source).is_dir():QMessageBox.warning(self,"Source","Sélectionnez un dossier source accessible.");return
    if not bucket:QMessageBox.warning(self,"S3","Le nom du bucket est obligatoire.");return
    if not self.engine.exists():QMessageBox.critical(self,"Moteur absent","nfs2s3_engine.py est introuvable.");return
    args=[str(self.engine),"--source",source,"--bucket",bucket,"--prefix",self.prefix.text().strip(),
      "--region",self.region.text().strip(),"--workers",str(self.workers.value()),"--verify",self.verify.currentText(),
      "--retries",str(self.retry.value())]
    if self.endpoint.text().strip():args += ["--endpoint",self.endpoint.text().strip()]
    if self.immutable.isChecked():args+=["--immutable"]
    if self.follow.isChecked():args+=["--follow-links"]
    if self.dry.isChecked():args+=["--dry-run"]
    env=QProcessEnvironment.systemEnvironment()
    if self.ak.text():env.insert("AWS_ACCESS_KEY_ID",self.ak.text())
    if self.sk.text():env.insert("AWS_SECRET_ACCESS_KEY",self.sk.text())
    self.proc.setProcessEnvironment(env);self.go.setEnabled(False);self.stop.setEnabled(True)
    self.status.setText("● EN COURS");self.bar.setValue(0);self.started=time.monotonic()
    if getattr(sys,"frozen",False):
      engine_bin=self.base/"nfs2s3_engine.exe"
      if not engine_bin.exists():QMessageBox.critical(self,"Moteur absent","nfs2s3_engine.exe est introuvable dans le dossier de l’application.");self.go.setEnabled(True);self.stop.setEnabled(False);return
      self.proc.start(str(engine_bin),args[1:])
    else:self.proc.start(sys.executable,args)
 def read(self):
    self.buffer+=bytes(self.proc.readAllStandardOutput()).decode("utf-8",errors="replace")
    while "\n" in self.buffer:
      line,self.buffer=self.buffer.split("\n",1);self.console.appendPlainText(line)
      try:
       d=json.loads(line)
       if d.get("event")=="progress":
        total=d.get("files",0);done=d.get("done",0)
        if total:self.bar.setValue(int(done*100/total));self.bar.setFormat(f"{done}/{total} fichiers — %p%")
        self.speed.setText(f"{d.get('speed',0)/1024/1024:.1f} MB/s")
        self.count.setText(f"{done}/{total}");self.errors.setText(str(d.get("errors",0)))
       elif d.get("event")=="start":self.count.setText(f"0/{d.get('files',0)}")
      except (ValueError,TypeError):pass
 def stop_job(self):
    if self.proc.state()!=QProcess.NotRunning:self.proc.terminate()
 def finished(self,code,status):
    self.go.setEnabled(True);self.stop.setEnabled(False)
    self.status.setText("● TERMINÉ" if code==0 else f"● ERREUR ({code})")
    self.status.setStyleSheet("color:#5ee0ad" if code==0 else "color:#fb7185")
    if code==0:self.bar.setValue(100);self.bar.setFormat("Transfert terminé")
def main():
 app=QApplication(sys.argv);app.setStyle("Fusion");app.setStyleSheet(DARK);w=Window();w.show();sys.exit(app.exec())
if __name__=="__main__":main()
