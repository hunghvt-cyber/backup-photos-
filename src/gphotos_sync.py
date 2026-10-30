from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from pathlib import Path
from playwright.sync_api import sync_playwright

SEL='a[href*="/photo/"],a[href*="/video/"]'; ID=re.compile(r'/(photo|video)/([^/?#]+)')
VIDATE=re.compile(r'(\d{1,2}):(\d{2}):(\d{2})\s+(\d{1,2})\s+thg\s+(\d{1,2}),\s*(\d{4})',re.I)
def wait_for_library(page, timeout_ms=30000, poll_ms=500):
 """Bounded gallery readiness check; never log account URLs or private DOM."""
 if timeout_ms < 0 or poll_ms <= 0:raise ValueError('INVALID_LIBRARY_WAIT')
 remaining=timeout_ms
 while True:
  host=(urlsplit(page.url).hostname or '').lower()
  if host=='accounts.google.com':status='AUTH_REQUIRED'
  elif host=='consent.google.com':status='CONSENT_REQUIRED'
  else:status=None
  if status:
   print('PHOTOS_LIBRARY_STATUS='+status,flush=True)
   raise RuntimeError('GOOGLE_PHOTOS_'+status)
  if host=='photos.google.com' and page.locator(SEL).count()>0:
   print('PHOTOS_LIBRARY_STATUS=READY',flush=True)
   return
  if remaining<=0:
   print('PHOTOS_LIBRARY_STATUS=GALLERY_NOT_READY',flush=True)
   raise RuntimeError('GOOGLE_PHOTOS_GALLERY_NOT_READY')
  wait=min(poll_ms,remaining);page.wait_for_timeout(wait);remaining-=wait

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

RAW_EXTENSIONS={'.arw','.cr2','.cr3','.dng','.nef','.nrw','.raf','.pef','.rw2','.srw','.orf','.raw'}
VIDEO_EXTENSIONS={'.mp4','.mov','.m4v','.webm','.mkv','.avi','.3gp','.3g2','.mts','.m2ts','.mpg','.mpeg'}
def image_payload(prefix):
 return (prefix.startswith((b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n',b'GIF87a',b'GIF89a'))
         or (prefix[:4]==b'RIFF' and prefix[8:12]==b'WEBP'))
def validate_media(path,filename,expected_type=None):
 """Recognize actual payload; never rename a preview as an original video."""
 path=Path(path)
 if not path.stat().st_size:raise RuntimeError('EMPTY_MEDIA_DOWNLOAD')
 with path.open('rb') as stream:prefix=stream.read(512)
 lower=prefix.lstrip().lower()
 if lower.startswith((b'<!doctype html',b'<html')) or b'<html' in lower:
  raise RuntimeError('HTML_INSTEAD_OF_MEDIA')
 image=image_payload(prefix)
 if image and Path(filename).suffix.lower() in RAW_EXTENSIONS:raise RuntimeError('IMAGE_PREVIEW_INSTEAD_OF_RAW')
 wants_video=expected_type=='video' or Path(filename).suffix.lower() in VIDEO_EXTENSIONS
 if wants_video:
  if image:raise RuntimeError('IMAGE_PREVIEW_INSTEAD_OF_VIDEO')
  try:
   probe=subprocess.run(['ffprobe','-v','error','-show_entries',
    'format=format_name,duration:stream=codec_type,codec_name','-of','json',str(path)],
    capture_output=True,text=True,timeout=30)
   data=json.loads(probe.stdout)
   format_name=data.get('format',{}).get('format_name','')
   duration=float(data.get('format',{}).get('duration') or 0)
  except (OSError,ValueError,subprocess.TimeoutExpired):
   raise RuntimeError('VIDEO_VALIDATION_UNAVAILABLE') from None
  if (probe.returncode or not any(x.get('codec_type')=='video' for x in data.get('streams',[]))
      or any(x in format_name for x in ('image2','_pipe','gif')) or not duration>0):
   raise RuntimeError('INVALID_OR_STILL_IMAGE_VIDEO')
  return 'video'
 return 'photo' if image else 'unclassified'

class DB:
 def __init__(self,p):
  self.p=Path(p); self.p.parent.mkdir(parents=True,exist_ok=True); self.c=sqlite3.connect(p); self.c.execute('PRAGMA journal_mode=WAL'); self.c.executescript('''
  CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,type TEXT,url TEXT,label TEXT,created TEXT,filename TEXT,size INTEGER,sha256 TEXT,remote TEXT,first_seen TEXT,last_seen TEXT,uploaded_at TEXT,status TEXT,last_error TEXT);
  CREATE TABLE IF NOT EXISTS reconcile_seen(gen TEXT,id TEXT,seen_at TEXT,PRIMARY KEY(gen,id));'''); self.c.commit()
 def touch(self,i,t,u,l,cr):
  n=now(); self.c.execute("INSERT INTO media(id,type,url,label,created,first_seen,last_seen,status) VALUES(?,?,?,?,?,?,?,'seen') ON CONFLICT(id) DO UPDATE SET url=excluded.url,label=COALESCE(excluded.label,media.label),created=COALESCE(excluded.created,media.created),last_seen=excluded.last_seen",(i,t,u,l,cr,n,n)); self.c.commit()
 def uploaded(self,i):
  r=self.c.execute("SELECT 1 FROM media WHERE id=? AND status='uploaded'",(i,)).fetchone(); return bool(r)
 def done(self,i,nm,sz,h,r,media_type=None): self.c.execute("UPDATE media SET filename=?,size=?,sha256=?,remote=?,uploaded_at=?,last_seen=?,type=COALESCE(?,type),status='uploaded',last_error=NULL WHERE id=?",(nm,sz,h,r,now(),now(),media_type,i)); self.c.commit()
 def err(self,i,e): self.c.execute("UPDATE media SET last_error=?,status=CASE WHEN status='uploaded' THEN status ELSE 'error' END WHERE id=?",(str(e)[:800],i)); self.c.commit()
 def seen(self,g,i): self.c.execute("INSERT OR REPLACE INTO reconcile_seen VALUES(?,?,?)",(g,i,now())); self.c.commit()
 def snapshot(self,p):
  p=Path(p); p.unlink(missing_ok=True); out=sqlite3.connect(p)
  try:self.c.commit();self.c.backup(out);out.commit()
  finally:out.close()
 def report(self,g):
  up=self.c.execute("SELECT COUNT(*) FROM media WHERE status='uploaded'").fetchone()[0]; sn=self.c.execute("SELECT COUNT(*) FROM reconcile_seen WHERE gen=?",(g,)).fetchone()[0]; ms=self.c.execute("SELECT COUNT(*) FROM media m WHERE status='uploaded' AND NOT EXISTS(SELECT 1 FROM reconcile_seen r WHERE r.gen=? AND r.id=m.id)",(g,)).fetchone()[0]; return {'uploaded':up,'seen':sn,'missing_report_only':ms}

class Engine:
 def __init__(self,a):
  self.a=a; self.start=time.monotonic(); self.sd=Path(a.state); self.wd=Path(a.work); self.sd.mkdir(parents=True,exist_ok=True); self.wd.mkdir(parents=True,exist_ok=True); self.restore(); self.db=DB(self.sd/'manifest.sqlite'); self.cp=self.load('daily-checkpoint.json',{'version':1,'bootstrap_complete':False}); self.stats={'discovered':0,'attempted':0,'uploaded':0,'skipped':0,'errors':0}; self.seen=set()
 def recheck_small_video_records(self):
  # Run only inside the regular serialized worker, never in the read-only audit.
  # Verify exact remote bytes against the recorded hash before changing a row.
  rows=self.db.c.execute("SELECT id,filename,remote,size,sha256 FROM media WHERE status='uploaded' AND size>0 AND size<=4096 ORDER BY uploaded_at,id").fetchall()
  candidates=[r for r in rows if Path(r[1] or '').suffix.lower() in VIDEO_EXTENSIONS][:20]
  requeued=0
  for media,name,remote,size,digest in candidates:
   if self.left()<240:break
   if not remote or not remote.startswith(self.a.root.rstrip('/')+'/'):continue
   try:
    result=subprocess.run(['rclone','cat',remote,'--head','4097','--retries','1',
     '--low-level-retries','1','--contimeout','10s','--timeout','15s'],capture_output=True,timeout=45)
    data=result.stdout
    if result.returncode or len(data)!=size or hashlib.sha256(data).hexdigest()!=digest:
     print('SMALL_VIDEO_RECHECK_UNCONFIRMED',flush=True);continue
    if not image_payload(data):continue
    self.db.c.execute("UPDATE media SET status='error',last_error='IMAGE_PREVIEW_INSTEAD_OF_VIDEO; original queued for retry' WHERE id=? AND status='uploaded' AND remote=? AND sha256=?",(media,remote,digest))
    self.db.c.commit();requeued+=1
   except (OSError,subprocess.TimeoutExpired):
    print('SMALL_VIDEO_RECHECK_UNAVAILABLE',flush=True)
  if requeued:self.flush()
  if candidates:print('SMALL_VIDEO_RECHECK='+json.dumps({'checked_candidates':len(candidates),'requeued':requeued,'old_files_preserved':True}),flush=True)
 def load(self,n,d):
  p=self.sd/n
  try:return json.loads(p.read_text())
  except:return d
 def restore(self):
  for n in ('manifest.sqlite','daily-checkpoint.json','reconcile-state.json'):
   r=cmd('rclone','copyto',f'{self.a.sroot}/{n}',str(self.sd/n),ok=False,cap=True)
   if r.returncode:
    (self.sd/n).unlink(missing_ok=True)
    if n in ('manifest.sqlite','daily-checkpoint.json'):
     raise RuntimeError(f'Required Koofr state {n} cannot be restored; refusing to reset production manifest/checkpoint')
    print(f'OPTIONAL_STATE_MISSING file={n}',flush=True)
 def flush(self):
  self.db.c.commit(); snap=self.sd/'manifest.snapshot.sqlite'; self.db.snapshot(snap); savej(self.sd/'daily-checkpoint.json',self.cp); cmd('rclone','copyto',str(snap),f'{self.a.sroot}/manifest.sqlite','--ignore-times'); cmd('rclone','copyto',str(self.sd/'daily-checkpoint.json'),f'{self.a.sroot}/daily-checkpoint.json','--ignore-times'); snap.unlink(missing_ok=True)
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
 def download(self,pw,u,i):
  c=pw.chromium.launch_persistent_context(user_data_dir=self.a.profile,executable_path=self.a.chrome,headless=True,accept_downloads=True,args=['--disable-dev-shm-usage','--no-first-run']);p=c.pages[0] if c.pages else c.new_page()
  try:
   p.goto(u,wait_until='domcontentloaded',timeout=120000);p.wait_for_timeout(1500)
   # The first googleusercontent request can be the viewer's WebP preview.
   # Save the exact Download event from Google's Download action instead.
   with p.expect_download(timeout=120000) as event:p.keyboard.press('Shift+D')
   download=event.value;nm=Path(download.suggested_filename).name
   if not nm or nm in ('.','..'):raise RuntimeError('INVALID_DOWNLOAD_FILENAME')
   dst=self.wd/f'{i}__{nm}'
   try:
    download.save_as(str(dst))
    validate_media(dst,nm)
   except BaseException:
    dst.unlink(missing_ok=True)
    raise
   return dst,nm
  finally:
   try:c.close()
   except:pass
 def remote(self,cr,nm,i,local_sha,local_size):
  try:d=datetime.fromisoformat(cr) if cr else None;y,m=(f'{d.year:04d}',f'{d.month:02d}') if d else ('Unknown-Date','00')
  except:y,m='Unknown-Date','00'
  name=Path(nm).name;stem,ext=os.path.splitext(name);folder=f'{self.a.root}/{y}/{m}'
  candidates=[f'{folder}/{name}',f'{folder}/{stem}__{i[:12]}{ext}',f'{folder}/{stem}__{i[:12]}__{local_sha[:16]}{ext}']
  for base in candidates:
   q=cmd('rclone','lsl',base,ok=False,cap=True)
   if q.returncode in (3,4):return base,False
   if q.returncode:raise RuntimeError('REMOTE_EXISTENCE_UNCONFIRMED')
   if not q.stdout.strip():
    stat=cmd('rclone','lsjson','--stat',base,'--retries','1','--low-level-retries','1','--contimeout','10s','--timeout','20s',ok=False,cap=True)
    if stat.returncode in (3,4):return base,False
    try:
     data=json.loads(stat.stdout) if stat.returncode==0 else None
     if not isinstance(data,dict) or data.get('IsDir') is not False or type(data.get('Size')) is not int or data['Size']<0:raise ValueError()
     remote_size=data['Size']
    except (ValueError,TypeError):raise RuntimeError('REMOTE_EXISTENCE_UNCONFIRMED') from None
   else:
    try:remote_size=int(q.stdout.strip().split()[0])
    except (ValueError,IndexError):raise RuntimeError('REMOTE_EXISTENCE_UNCONFIRMED') from None
   if remote_size==local_size:
    check=self.wd/f'{i}__remote-verify';cmd('rclone','copyto',base,str(check))
    try:
     if sha(check)==local_sha:return base,True
    finally:check.unlink(missing_ok=True)
  raise RuntimeError('REMOTE_COLLISION_UNRESOLVED')
 def verify_remote_size(self,remote,expected):
  for attempt in range(3):
   result=cmd('rclone','lsl',remote,'--retries','1','--low-level-retries','1','--contimeout','10s','--timeout','20s',ok=False,cap=True)
   line=result.stdout.strip() if result.returncode==0 else ''
   try:actual=int(line.split()[0]) if line else None
   except (ValueError,IndexError):actual=None
   if actual is None:
    stat=cmd('rclone','lsjson','--stat',remote,'--retries','1','--low-level-retries','1','--contimeout','10s','--timeout','20s',ok=False,cap=True)
    try:
     data=json.loads(stat.stdout) if stat.returncode==0 else None
     if isinstance(data,dict) and data.get('IsDir') is False and type(data.get('Size')) is int and data['Size']>=0:actual=data['Size']
    except (ValueError,TypeError):pass
    print('REMOTE_STAT_DIAGNOSTIC='+json.dumps({'lsl_rc':result.returncode,'lsl_stdout_bytes':len(result.stdout),'stat_rc':stat.returncode,'size_available':actual is not None}),flush=True)
   if actual==expected:return
   if actual is not None:
    raise RuntimeError(f'size mismatch {expected}!={actual}')
   if attempt==2 or self.left()<190:
    raise RuntimeError('REMOTE_SIZE_UNCONFIRMED')
   print(f'REMOTE_VERIFY_RETRY attempt={attempt+1}',flush=True)
   time.sleep(2*(attempt+1))
 def one(self,pw,i,t,u,l,cr,update_checkpoint=True,flush_state=True):
  self.db.touch(i,t,u,l,cr)
  if self.db.uploaded(i):self.stats['skipped']+=1;return
  self.stats['attempted']+=1;f=None
  try:
   for attempt in range(1,4):
    try:
     f,nm=self.download(pw,u,i)
     break
    except Exception as download_error:
     message=str(download_error)
     retryable=any(token in message.lower() for token in ('target page, context or browser has been closed','timeout','connectionerror','http error 403','forbidden','net::err'))
     if not retryable or attempt==3 or self.left()<240:raise
     print(f'DOWNLOAD_RETRY id={i} attempt={attempt} error={message[:180]}',flush=True)
     time.sleep(min(attempt*2,5))
   actual_type=validate_media(f,nm,t)
   verified_type=actual_type if actual_type in ('photo','video') else None
   sz=f.stat().st_size;h=sha(f);r,exists=self.remote(cr,nm,i,h,sz)
   if not exists:cmd('rclone','copyto',str(f),r,'--ignore-times','--retries','3')
   self.verify_remote_size(r,sz)
   self.db.done(i,nm,sz,h,r,media_type=verified_type);self.stats['uploaded']+=1
   if update_checkpoint:self.cp.update({'last_uploaded_id':i,'last_uploaded_at':now()})
   if flush_state:self.flush()
   print(f'UPLOAD_OK id={i} file={nm} size={sz} reused={exists}',flush=True)
  except Exception as e:
   self.stats['errors']+=1;self.db.err(i,e)
   if flush_state:self.flush()
   print(f'UPLOAD_ERROR id={i} error={e}',file=sys.stderr,flush=True)
  finally:
   if f:f.unlink(missing_ok=True)
 def scan(self,pw):
  c=pw.chromium.launch_persistent_context(user_data_dir=self.a.profile,executable_path=self.a.chrome,headless=True,args=['--disable-dev-shm-usage','--no-first-run']);p=c.pages[0] if c.pages else c.new_page()
  try:
   p.goto('https://photos.google.com/',wait_until='domcontentloaded',timeout=120000)
   wait_for_library(p)
   # Collect every intermediate viewport instead of jumping straight to End.
   # Reopen Chrome between batches so item downloads can use the same profile.
   from src.gphotos_backfill_grid import advance_gallery
   self._daily_scan_round=getattr(self,'_daily_scan_round',0)+1
   found={};scan_until=time.monotonic()+60
   for step in range(self._daily_scan_round*3+1):
    for row in self.visible(p):found.setdefault(row[0],row)
    if self.left()<190 or time.monotonic()>=scan_until:break
    advance_gallery(p,step)
   return list(found.values())
  finally:
   try:c.close()
   except:pass
 def daily(self):
  boundary=self.cp.get('newest_id');hit=False;head=None;nogrow=0;scan_status='PAUSED_TIME'
  with sync_playwright() as pw:
   while self.left()>180 and self.stats['attempted']<self.a.maxitems:
    items=self.scan(pw);n=0
    for i,t,u,l,cr in items:
     if i in self.seen:continue
     self.seen.add(i);head=head or i;n+=1;self.stats['discovered']+=1
     if boundary and i==boundary:hit=True;break
     self.one(pw,i,t,u,l,cr)
     if self.left()<=180 or self.stats['attempted']>=self.a.maxitems:break
    if hit or self.left()<=180 or self.stats['attempted']>=self.a.maxitems:break
    nogrow=nogrow+1 if n==0 else 0
    if nogrow>=3:scan_status='SCAN_STALLED';break
  if hit:
   scan_status='BOUNDARY_REACHED'
   # Keep the old boundary while errors remain so failed newer media can retry.
   if head and not self.stats['errors']:self.cp['newest_id']=head
  elif self.stats['attempted']>=self.a.maxitems:scan_status='PAUSED_LIMIT'
  # A stalled virtual gallery never proves full library coverage. Keep existing
  # IDs and manifest; retire only the misleading completion claim.
  self.cp.update({'bootstrap_complete':False,'last_daily_scan_status':scan_status,'last_daily_run':now(),'last_daily_stats':self.stats})
  self.flush();return {'boundary_seen':hit,'scan_status':scan_status,**self.stats,'checkpoint':self.cp}
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
 try:r=e.daily() if x.mode=='daily' else e.reconcile();print('SUMMARY='+json.dumps(r,ensure_ascii=False));return 1 if x.mode=='daily' and (r.get('errors',0)>0 or r.get('scan_status')!='BOUNDARY_REACHED') else 0
 finally:
  try:e.flush()
  except Exception as z:print('FINAL_STATE_FLUSH_ERROR='+str(z),file=sys.stderr)
  e.db.c.close();shutil.rmtree(e.wd,ignore_errors=True)
if __name__=='__main__':raise SystemExit(main())
