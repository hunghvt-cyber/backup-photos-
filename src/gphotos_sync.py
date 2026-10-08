from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

SEL='a[href*="/photo/"],a[href*="/video/"]'; ID=re.compile(r'/(photo|video)/([^/?#]+)')
VIDATE=re.compile(r'(\d{1,2}):(\d{2}):(\d{2})\s+(\d{1,2})\s+thg\s+(\d{1,2}),\s*(\d{4})',re.I)
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def cmd(*a,ok=True,cap=False): return subprocess.run(a,check=ok,text=True,capture_output=cap)
def savej(p,d):
 p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); q=p.with_suffix(p.suffix+'.tmp'); q.write_text(json.dumps(d,ensure_ascii=False,indent=2)); q.replace(p)
def href(x): return 'https://photos.google.com/'+x[2:] if x.startswith('./') else 'https://photos.google.com'+x if x.startswith('/') else x
def ident(u):
 m=ID.search(u)
 if not m: raise ValueError(u)
 return m.group(2),m.group(1)
def created(label):
 m=VIDATE.search(label or '')
 if not m:return None
 h,mi,s,d,mo,y=map(int,m.groups()); return datetime(y,mo,d,h,mi,s).isoformat(timespec='seconds')
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

class DB:
 def __init__(self,p):
  self.p=Path(p); self.p.parent.mkdir(parents=True,exist_ok=True); self.c=sqlite3.connect(p); self.c.execute('PRAGMA journal_mode=WAL'); self.c.executescript('''
  CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,type TEXT,url TEXT,label TEXT,created TEXT,filename TEXT,size INTEGER,sha256 TEXT,remote TEXT,first_seen TEXT,last_seen TEXT,uploaded_at TEXT,status TEXT,last_error TEXT);
  CREATE TABLE IF NOT EXISTS reconcile_seen(gen TEXT,id TEXT,seen_at TEXT,PRIMARY KEY(gen,id));'''); self.c.commit()
 def touch(self,i,t,u,l,cr):
  n=now(); self.c.execute("INSERT INTO media(id,type,url,label,created,first_seen,last_seen,status) VALUES(?,?,?,?,?,?,?,'seen') ON CONFLICT(id) DO UPDATE SET url=excluded.url,label=COALESCE(excluded.label,media.label),created=COALESCE(excluded.created,media.created),last_seen=excluded.last_seen",(i,t,u,l,cr,n,n)); self.c.commit()
 def uploaded(self,i):
  r=self.c.execute("SELECT 1 FROM media WHERE id=? AND status='uploaded'",(i,)).fetchone(); return bool(r)
 def done(self,i,nm,sz,h,r): self.c.execute("UPDATE media SET filename=?,size=?,sha256=?,remote=?,uploaded_at=?,last_seen=?,status='uploaded',last_error=NULL WHERE id=?",(nm,sz,h,r,now(),now(),i)); self.c.commit()
 def err(self,i,e): self.c.execute("UPDATE media SET last_error=?,status=CASE WHEN status='uploaded' THEN status ELSE 'error' END WHERE id=?",(str(e)[:800],i)); self.c.commit()
 def seen(self,g,i): self.c.execute("INSERT OR REPLACE INTO reconcile_seen VALUES(?,?,?)",(g,i,now())); self.c.commit()
 def report(self,g):
  up=self.c.execute("SELECT COUNT(*) FROM media WHERE status='uploaded'").fetchone()[0]; sn=self.c.execute("SELECT COUNT(*) FROM reconcile_seen WHERE gen=?",(g,)).fetchone()[0]; ms=self.c.execute("SELECT COUNT(*) FROM media m WHERE status='uploaded' AND NOT EXISTS(SELECT 1 FROM reconcile_seen r WHERE r.gen=? AND r.id=m.id)",(g,)).fetchone()[0]; return {'uploaded':up,'seen':sn,'missing_report_only':ms}

class Engine:
 def __init__(self,a):
  self.a=a; self.start=time.monotonic(); self.sd=Path(a.state); self.wd=Path(a.work); self.sd.mkdir(parents=True,exist_ok=True); self.wd.mkdir(parents=True,exist_ok=True); self.restore(); self.db=DB(self.sd/'manifest.sqlite'); self.cp=self.load('daily-checkpoint.json',{'version':1,'bootstrap_complete':False}); self.stats={'discovered':0,'uploaded':0,'skipped':0,'errors':0}; self.seen=set()
 def load(self,n,d):
  p=self.sd/n
  try:return json.loads(p.read_text())
  except:return d
 def restore(self):
  for n in ('manifest.sqlite','daily-checkpoint.json','reconcile-state.json'):
   r=cmd('rclone','copyto',f'{self.a.sroot}/{n}',str(self.sd/n),ok=False)
   if r.returncode:(self.sd/n).unlink(missing_ok=True)
 def flush(self):
  self.db.c.commit(); self.db.c.execute('PRAGMA wal_checkpoint(FULL)'); self.db.c.commit(); savej(self.sd/'daily-checkpoint.json',self.cp); cmd('rclone','copyto',str(self.sd/'manifest.sqlite'),f'{self.a.sroot}/manifest.sqlite'); cmd('rclone','copyto',str(self.sd/'daily-checkpoint.json'),f'{self.a.sroot}/daily-checkpoint.json')
 def left(self):return self.a.seconds-int(time.monotonic()-self.start)
 def visible(self,p):
  out=[]; q=p.locator(SEL)
  for x in range(q.count()):
   e=q.nth(x); h=e.get_attribute('href')
   if not h:continue
   u=href(h)
   try:i,t=ident(u)
   except:continue
   l=e.get_attribute('aria-label') or e.get_attribute('data-tooltip'); out.append((i,t,u,l,created(l)))
  return out
 def download(self,p,u,i):
  p.goto(u,wait_until='domcontentloaded',timeout=120000); p.wait_for_timeout(2500)
  with p.expect_request(lambda r:'usercontent.google.com' in r.url,timeout=120000) as rq:
   with p.expect_download(timeout=120000) as dl:p.keyboard.press('Shift+D')
  r=rq.value; d=dl.value; hs={k:v for k,v in r.all_headers().items() if not k.startswith(':') and k.lower() not in ('host','content-length')}; hs['accept-encoding']='identity'; nm=Path(d.suggested_filename).name; dst=self.wd/f'{i}__{nm}'
  with urllib.request.urlopen(urllib.request.Request(r.url,headers=hs),timeout=180) as z,open(dst,'wb') as f:shutil.copyfileobj(z,f,1048576)
  if dst.stat().st_size<1:raise RuntimeError('empty download')
  return dst,nm
 def remote(self,cr,nm,i):
  try:d=datetime.fromisoformat(cr) if cr else None; y,m=(f'{d.year:04d}',f'{d.month:02d}') if d else ('Unknown-Date','00')
  except:y,m='Unknown-Date','00'
  base=f'{self.a.root}/{y}/{m}/{Path(nm).name}'; r=cmd('rclone','lsf',base,ok=False,cap=True)
  if r.returncode==0 and r.stdout.strip():
   s,x=os.path.splitext(Path(nm).name); base=f'{self.a.root}/{y}/{m}/{s}__{i[:12]}{x}'
  return base
 def one(self,p,i,t,u,l,cr):
  self.db.touch(i,t,u,l,cr)
  if self.db.uploaded(i):self.stats['skipped']+=1;return
  f=None
  try:
   f,nm=self.download(p,u,i); sz=f.stat().st_size; h=sha(f); r=self.remote(cr,nm,i); cmd('rclone','copyto',str(f),r,'--ignore-times','--retries','3'); line=cmd('rclone','lsl',r,cap=True).stdout.strip(); rz=int(line.split()[0]) if line else -1
   if rz!=sz:raise RuntimeError(f'size mismatch {sz}!={rz}')
   self.db.done(i,nm,sz,h,r); self.stats['uploaded']+=1; self.cp.update({'last_uploaded_id':i,'last_uploaded_at':now()}); self.flush(); print(f'UPLOAD_OK id={i} file={nm} size={sz}',flush=True)
  except Exception as e:self.stats['errors']+=1;self.db.err(i,e);self.flush();print(f'UPLOAD_ERROR id={i} error={e}',file=sys.stderr,flush=True)
  finally:
   if f:f.unlink(missing_ok=True)
 def daily(self):
  boundary=self.cp.get('newest_id') if self.cp.get('bootstrap_complete') else None; hit=False; head=None; nogrow=0
  with sync_playwright() as pw:
   c=pw.chromium.launch_persistent_context(user_data_dir=self.a.profile,executable_path=self.a.chrome,headless=True,accept_downloads=True,args=['--disable-dev-shm-usage','--no-first-run']); p=c.pages[0] if c.pages else c.new_page(); p.goto('https://photos.google.com/',wait_until='domcontentloaded',timeout=120000);p.wait_for_timeout(8000)
   if p.locator(SEL).count()==0:raise RuntimeError('Google Photos session unavailable')
   while self.left()>180 and self.stats['uploaded']<self.a.maxitems:
    n=0
    for i,t,u,l,cr in self.visible(p):
     if i in self.seen:continue
     self.seen.add(i);head=head or i;n+=1;self.stats['discovered']+=1
     if boundary and i==boundary:hit=True;break
     self.one(p,i,t,u,l,cr)
     if self.left()<=180 or self.stats['uploaded']>=self.a.maxitems:break
    if hit or self.left()<=180 or self.stats['uploaded']>=self.a.maxitems:break
    nogrow=nogrow+1 if n==0 else 0
    if nogrow>=3:self.cp.update({'bootstrap_complete':True,'bootstrap_completed_at':now()});break
    p.goto('https://photos.google.com/',wait_until='domcontentloaded',timeout=120000);p.wait_for_timeout(1200)
    for _ in range(max(1,len(self.seen)//20)):p.keyboard.press('End');p.wait_for_timeout(700)
   try:c.close()
   except:pass
  if hit and head:self.cp['newest_id']=head
  elif not self.cp.get('newest_id') and head:self.cp['newest_id']=head
  self.cp.update({'last_daily_run':now(),'last_daily_stats':self.stats});self.flush();return {'boundary_seen':hit,**self.stats,'checkpoint':self.cp}
 def reconcile(self):
  sp=self.sd/'reconcile-state.json'; st=self.load('reconcile-state.json',{}); g=st.get('generation') if st.get('status')=='PAUSED' else datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); target=st.get('resume_last_id') if st.get('status')=='PAUSED' else None; resuming=bool(target); st.update({'generation':g,'status':'RUNNING','started_at':st.get('started_at') or now()});savej(sp,st);cmd('rclone','copyto',str(sp),f'{self.a.sroot}/reconcile-state.json'); seen=set();nogrow=0;complete=False;last=target;pending=0
  with sync_playwright() as pw:
   c=pw.chromium.launch_persistent_context(user_data_dir=self.a.profile,executable_path=self.a.chrome,headless=True,args=['--disable-dev-shm-usage','--no-first-run']);p=c.pages[0] if c.pages else c.new_page();p.goto('https://photos.google.com/',wait_until='domcontentloaded',timeout=120000);p.wait_for_timeout(8000)
   if p.locator(SEL).count()==0:raise RuntimeError('Google Photos session unavailable')
   while self.left()>180:
    n=0
    for i,t,u,l,cr in self.visible(p):
     if i in seen:continue
     seen.add(i)
     if resuming:
      if i==target:resuming=False;nogrow=0
      continue
     n+=1;pending+=1;last=i;self.db.touch(i,t,u,l,cr);self.db.seen(g,i)
    if not resuming:nogrow=nogrow+1 if n==0 else 0
    if pending>=200:
     st.update({'status':'PAUSED','updated_at':now(),'resume_last_id':last});savej(sp,st);self.flush();cmd('rclone','copyto',str(sp),f'{self.a.sroot}/reconcile-state.json');pending=0
    if not resuming and nogrow>=3:complete=True;break
    p.keyboard.press('End');p.wait_for_timeout(200 if resuming else 900)
   try:c.close()
   except:pass
  st.update({'status':'COMPLETE' if complete else 'PAUSED','updated_at':now(),'seen_this_run':len(seen),'resume_last_id':None if complete else last,'report':self.db.report(g),'deletion_enabled':False});savej(sp,st);self.flush();cmd('rclone','copyto',str(sp),f'{self.a.sroot}/reconcile-state.json');rp=self.sd/f'reconcile-report-{g}.json';savej(rp,st);cmd('rclone','copyto',str(rp),f'{self.a.sroot}/logs/{rp.name}');return st

def main():
 a=argparse.ArgumentParser();a.add_argument('mode',choices=['daily','reconcile']);a.add_argument('--profile',default=os.path.expanduser('~/gphotos-profile'));a.add_argument('--chrome',default=os.environ.get('CHROME_BIN','/usr/bin/google-chrome-stable'));a.add_argument('--state',default='/tmp/gphotos-state');a.add_argument('--work',default='/tmp/gphotos-downloads');a.add_argument('--root',default='koofr_remote:/Google Photos/Photos');a.add_argument('--sroot',default='koofr_remote:/Google Photos/.gphotos-sync');a.add_argument('--seconds',type=int,default=int(os.environ.get('MAX_RUNTIME_SECONDS','16800')));a.add_argument('--maxitems',type=int,default=int(os.environ.get('MAX_ITEMS','1000')));x=a.parse_args();e=Engine(x)
 try:r=e.daily() if x.mode=='daily' else e.reconcile();print('SUMMARY='+json.dumps(r,ensure_ascii=False));return 0
 finally:
  try:e.flush()
  except Exception as z:print('FINAL_STATE_FLUSH_ERROR='+str(z),file=sys.stderr)
  e.db.c.close();shutil.rmtree(e.wd,ignore_errors=True)
if __name__=='__main__':raise SystemExit(main())
