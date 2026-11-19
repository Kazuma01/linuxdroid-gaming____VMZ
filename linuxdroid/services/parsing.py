"""Parsing puro para saída de comandos Waydroid/ADB."""
import re
from ..models import WaydroidStatus, WaydroidState, AdbDevice
PACKAGE_RE=re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
def is_valid_package(pkg): return bool(pkg and PACKAGE_RE.fullmatch(pkg))
def waydroid_status(stdout,stderr="",code=0):
    text=(stdout+"\n"+stderr).lower()
    if "not initialized" in text: return WaydroidStatus(WaydroidState.NOT_INITIALIZED,message="Waydroid ainda não foi inicializado.")
    values={}
    for line in stdout.splitlines():
        if ":" in line:
            k,v=line.split(":",1); values[k.strip().lower()]=v.strip().upper() if k.strip().lower() in ("session","container") else v.strip()
    session=values.get("session",""); container=values.get("container",""); ip=values.get("ip address","")
    if session=="RUNNING": state=WaydroidState.RUNNING
    elif session: state=WaydroidState.STOPPED
    elif code: state=WaydroidState.ERROR
    else: state=WaydroidState.UNKNOWN
    message=(stderr or "").strip() if code else ""
    return WaydroidStatus(state,session,container,ip,message)
def parse_devices(text):
    out=[]
    for line in text.splitlines():
        bits=line.split()
        if len(bits)>=2 and not line.startswith("*") and not bits[0].lower().startswith("list"):
            extra=dict(x.split(":",1) for x in bits[2:] if ":" in x)
            out.append(AdbDevice(bits[0],bits[1],extra.get("model",""),extra.get("product","")))
    return out
def parse_packages(text):
    return sorted({line.strip()[8:] for line in text.splitlines() if line.strip().startswith("package:") and is_valid_package(line.strip()[8:])})
def parse_waydroid_apps(text):
    apps=[]; name=""
    for line in text.splitlines():
        val=line.strip()
        if val.lower().startswith("name:"): name=val.split(":",1)[1].strip()
        elif re.sub(r"\s+", "", val.lower()).startswith("packagename:"):
            pkg=val.split(":",1)[1].strip()
            if is_valid_package(pkg): apps.append((name or pkg.rsplit(".",1)[-1].title(),pkg))
            name=""
    return apps
