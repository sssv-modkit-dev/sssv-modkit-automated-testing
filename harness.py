#!/usr/bin/env python3
"""Mupen64Plus capture and frame-based button recipes, stdlib only.
Core API: https://mupen64plus.org/wiki/index.php/Mupen64Plus_v2.0_Core_Front-End
Frames mean rendered frames, not VI ticks or guaranteed 30 FPS.
"""
import argparse
import ctypes as C
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib

ROOT = Path(__file__).resolve().parent
DEFAULT_ROM = os.environ.get('SSSV_ROM')
# Core 2.5.9 SDL2 key injection uses SDL scancodes, while config key(...)
# strings retain SDL1 key IDs. Keep these two domains separate.
BUTTONS = {'START':40, 'A':225, 'B':224, 'Z':29, 'L':27, 'R':6,
    'UP':82, 'DOWN':81, 'LEFT':80, 'RIGHT':79,
    'DPAD_UP':26, 'DPAD_DOWN':22, 'DPAD_LEFT':4, 'DPAD_RIGHT':7,
    'C_UP':12, 'C_DOWN':14, 'C_LEFT':13, 'C_RIGHT':15}

def digest(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()

def positive(value):
    if type(value) is not int or not 1 <= value <= 1000000:
        raise ValueError('frames must be an integer between 1 and 1000000')
    return value

def label(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',value):
        raise ValueError('labels must be 1-80 letters, digits, underscores or hyphens')
    return value

def compile_recipe(recipe):
    if recipe.get('version') != 1 or not isinstance(recipe.get('steps'),list) or not recipe['steps']:
        raise ValueError('recipe needs version 1 and nonempty steps')
    events,labels,frame = [],set(),1
    for step in recipe['steps']:
        op = step.get('action')
        if op == 'wait': frame += positive(step['frames'])
        elif op == 'press':
            names = step['buttons']
            if not isinstance(names,list) or not names or any(not isinstance(n,str) or n not in BUTTONS for n in names) or len(set(names))!=len(names):
                raise ValueError('press requires distinct buttons from: '+', '.join(BUTTONS))
            hold=positive(step.get('frames',3))
            events.extend([{'frame':frame,'action':'down','buttons':names},{'frame':frame+hold,'action':'up','buttons':names}])
            frame += hold+positive(step.get('release_frames',12))
        elif op in ('capture','save_state'):
            name=label(step['label'])
            if name in labels: raise ValueError('duplicate label: '+name)
            labels.add(name)
            events.append({'frame':frame,'action':op,'label':name})
            frame += 2
        else: raise ValueError('unknown action: '+str(op))
    if not any(e['action']=='capture' for e in events): raise ValueError('recipe must capture at least once')
    return events,frame+3

def duration(value):
    m=re.fullmatch(r'([0-9]+)([smhf]?)',value)
    if not m: raise ValueError('duration must be e.g. 2s, 5m, 120f')
    return positive(int(m[1])*{'':30,'s':30,'m':1800,'h':108000,'f':1}[m[2]])

def validate_state(state,rom):
    if not state: return 'cold_boot'
    state=Path(state)
    if not state.is_file(): raise ValueError('state not found: '+str(state))
    meta=Path(str(state)+'.json')
    if meta.exists():
        metadata=json.loads(meta.read_text())
        if metadata['rom_sha1']!=digest(rom) or metadata['state_sha1']!=digest(state):
            raise ValueError('state provenance hash mismatch')
        return 'sha1_manifest_matches'
    if zipfile.is_zipfile(state):
        with zipfile.ZipFile(state) as z:
            members=[i for i in z.infolist() if re.search(r'\.pj[0-9]?$',i.filename,re.I)]
            if len(members)==1:
                with z.open(members[0]) as f: header=f.read(72)
                if header[:4]==bytes.fromhex('c8a6d823') and len(header)==72:
                    stored=b''.join(header[i:i+4][::-1] for i in range(8,72,4))
                    if stored[16:24]!=Path(rom).read_bytes()[16:24]:
                        raise ValueError('Project64 ROM CRC identity mismatch; use a matching state, never rewrite its header')
                    return 'pj64_crc_matches_geometry_unverified'
    return 'identity_unverified_core_must_validate'

def png(path,w,h,rgb):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    stride=w*3
    rows=b''.join(b'\0'+rgb[i*stride:(i+1)*stride] for i in reversed(range(h)))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))

class Core:
    def __init__(self,plan):
        self.plan=plan; self.run=Path(plan['run_dir'])
        self.lib=C.CDLL('libmupen64plus.so.2',mode=C.RTLD_GLOBAL)
        self.plugins=[]; self.events=[]; self.captures=[]; self.saves=[]; self.ptrs=[]; self.save_written=set()
        self.core_errors=[]; self.message_counts={}; self.frame=0; self.error=None; self.pending_save=None
        self.loaded=not bool(plan.get('state')); self.load_requested=False
        self.debug_type=C.CFUNCTYPE(None,C.c_void_p,C.c_int,C.c_char_p)
        self.state_type=C.CFUNCTYPE(None,C.c_void_p,C.c_int,C.c_int)
        self.frame_type=C.CFUNCTYPE(None,C.c_uint)
        for name,types in {
            'CoreStartup':[C.c_int,C.c_char_p,C.c_char_p,C.c_void_p,self.debug_type,C.c_void_p,self.state_type],
            'CoreDoCommand':[C.c_int,C.c_int,C.c_void_p],
            'CoreAttachPlugin':[C.c_int,C.c_void_p], 'CoreDetachPlugin':[C.c_int], 'CoreShutdown':[],
            'ConfigSaveFile':[],
            'ConfigOpenSection':[C.c_char_p,C.POINTER(C.c_void_p)],
            'ConfigSetParameter':[C.c_void_p,C.c_char_p,C.c_int,C.c_void_p]}.items():
            fn=getattr(self.lib,name); fn.argtypes=types; fn.restype=C.c_int
    def check(self,code,action):
        if code: raise RuntimeError('%s failed with Mupen error %s'%(action,code))
    def command(self,cmd,value=0,ptr=None):
        self.check(self.lib.CoreDoCommand(cmd,value,ptr),'command %s'%cmd)
    def set(self,section,key,value):
        h=C.c_void_p(); self.check(self.lib.ConfigOpenSection(section.encode(),C.byref(h)),'config section')
        if isinstance(value,str): kind,data=4,C.create_string_buffer(value.encode())
        else: kind,data=(3 if isinstance(value,bool) else 1),C.c_int(value)
        self.check(self.lib.ConfigSetParameter(h,key.encode(),kind,C.byref(data)),key)
    def debug(self,context,level,message):
        text=message.decode(errors='replace')
        if text.startswith('Saved state to: '): self.save_written.add(text.split(': ',1)[1])
        if level==1 and text not in self.core_errors: self.core_errors.append(text)
        count=self.message_counts.get(text,0)+1; self.message_counts[text]=count
        if count<=3: print('M64[%s] %s'%(level,text),flush=True)
    def state_changed(self,context,param,value):
        try:
            if param==1 and value==2:
                speed=C.c_int(0); self.command(17,5,C.byref(speed))
                if self.plan.get('state') and not self.load_requested:
                    self.load_requested=True; ptr=C.create_string_buffer(self.plan['state'].encode()); self.ptrs.append(ptr)
                    self.command(10,0,ptr)
            elif param==10:
                if not value: raise RuntimeError('core rejected state load')
                self.loaded=True; self.command(8)
            elif param==11:
                if not value: raise RuntimeError('core failed state save')
                # In core 2.5.9 this reports queue acceptance, not gzip completion.
                # debug() observes the post-gzclose completion message instead.
        except Exception as e:
            self.error=str(e); self.lib.CoreDoCommand(6,0,None)
    def capture(self,name):
        w,h=C.c_int(),C.c_int()
        self.video.ReadScreen2(None,C.byref(w),C.byref(h),0)
        if not 0<w.value<=4096 or not 0<h.value<=4096: raise RuntimeError('invalid capture dimensions')
        buf=(C.c_ubyte*(w.value*h.value*3))()
        self.video.ReadScreen2(buf,C.byref(w),C.byref(h),0)
        data=bytes(buf); path=self.run/(name+'.png'); png(path,w.value,h.value,data)
        self.captures.append({'path':str(path),'frame':self.frame,'all_black':not any(data),'width':w.value,'height':h.value,
            'rgb_sha1':hashlib.sha1(data).hexdigest(),'png_sha1':digest(path)})
    def on_frame(self,index):
        try:
            if not self.loaded: return
            self.frame+=1
            if self.pending_save and self.pending_save.name in self.save_written:
                self.saves.append(str(self.pending_save)); self.pending_save=None
            for e in self.plan['events']:
                if e['frame']!=self.frame: continue
                print('RECIPE '+json.dumps(e),flush=True); self.events.append(e)
                op=e['action']
                if op in ('down','up'):
                    for b in e['buttons']: self.command(13 if op=='down' else 14,BUTTONS[b])
                    if hasattr(self,'input'):
                        word=C.c_uint32(); self.input.GetKeys(0,C.byref(word)); e['controller_word']=word.value; print('CONTROLLER '+hex(word.value),flush=True)
                elif op=='capture': self.capture(e['label'])
                elif op=='save_state':
                    if self.pending_save: raise RuntimeError('previous state save not completed')
                    self.pending_save=self.run/(e['label']+'.st')
                    ptr=C.create_string_buffer(str(self.pending_save).encode()); self.ptrs.append(ptr); self.command(11,1,ptr)
            if self.frame>=self.plan['end_frame'] and not self.pending_save: self.command(6)
        except Exception as e:
            self.error=str(e); self.lib.CoreDoCommand(6,0,None)
    def execute(self):
        config=self.run/'config'; config.mkdir()
        debug,state,frame=self.debug_type(self.debug),self.state_type(self.state_changed),self.frame_type(self.on_frame)
        self.callbacks=[debug,state,frame]
        self.check(self.lib.CoreStartup(0x020001,str(config).encode(),b'/usr/share/games/mupen64plus',None,debug,None,state),'CoreStartup')
        opened=False
        try:
            (self.run/'saves').mkdir()
            # A fresh configuration prevents personal renderer settings/hotkeys from
            # changing the recipe. The GB camera backend is unrelated to ReadScreen2.
            for k,v in {'ScreenshotPath':str(self.run),'SaveStatePath':str(self.run),'SaveSRAMPath':str(self.run/'saves'),'OnScreenDisplay':False,'RandomizeInterrupt':False,'GbCameraVideoCaptureBackend1':'dummy'}.items(): self.set('Core',k,v)
            for k,v in {'Fullscreen':False,'ScreenWidth':640,'ScreenHeight':480,'VerticalSync':False}.items(): self.set('Video-General',k,v)
            for k,v in {'mode':0,'device':-1,'name':'Keyboard','plugged':True,'plugin':1,'mouse':False}.items(): self.set('Input-SDL-Control1',k,v)
            for i in range(2,5):
                self.set('Input-SDL-Control%d'%i,'mode',0); self.set('Input-SDL-Control%d'%i,'plugged',False)
            for k,v in {'Start':'key(13)','A Button':'key(304)','B Button':'key(306)','Z Trig':'key(122)','L Trig':'key(120)','R Trig':'key(99)','DPad U':'key(119)','DPad D':'key(115)','DPad L':'key(97)','DPad R':'key(100)','C Button U':'key(105)','C Button D':'key(107)','C Button L':'key(106)','C Button R':'key(108)','X Axis':'key(276,275)','Y Axis':'key(273,274)'}.items(): self.set('Input-SDL-Control1',k,v)
            raw=Path(self.plan['rom']).read_bytes(); self.rom=C.create_string_buffer(raw); self.command(1,len(raw),self.rom); opened=True
            directory=Path('/usr/lib/x86_64-linux-gnu/mupen64plus')
            for kind,name in [(2,'video-rice'),(4,'input-sdl'),(1,'rsp-hle')]:
                plugin=C.CDLL(str(directory/('mupen64plus-'+name+'.so')))
                plugin.PluginStartup.argtypes=[C.c_void_p,C.c_void_p,self.debug_type]; plugin.PluginStartup.restype=C.c_int
                plugin.PluginShutdown.argtypes=[]
                self.check(plugin.PluginStartup(self.lib._handle,None,debug),'PluginStartup '+name)
                self.check(self.lib.CoreAttachPlugin(kind,plugin._handle),'CoreAttachPlugin '+name)
                self.plugins.append((kind,plugin))
                if kind==4:
                    self.input=plugin; plugin.GetKeys.argtypes=[C.c_int,C.POINTER(C.c_uint32)]; plugin.GetKeys.restype=None
                if kind==2:
                    self.video=plugin; plugin.ReadScreen2.argtypes=[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_int),C.c_int]; plugin.ReadScreen2.restype=None
            self.check(self.lib.ConfigSaveFile(),'save isolated configuration')
            self.command(15,0,C.cast(frame,C.c_void_p)); self.command(5)
            if self.error: raise RuntimeError(self.error)
            if self.frame<self.plan['end_frame']: raise RuntimeError('emulator stopped before recipe completed')
            valid=bool(self.captures) and not self.core_errors and not any(c['all_black'] for c in self.captures)
            return {'status':'capture_complete' if valid else 'capture_invalid','capture_pass':valid,'semantic_pass':None,'frames':self.frame,'state_loaded':self.loaded if self.plan.get('state') else None,'captures':self.captures,'core_errors':self.core_errors,'review_required':not valid,'saved_states':self.saves,'events_executed':self.events}
        finally:
            for kind,plugin in reversed(self.plugins): self.lib.CoreDetachPlugin(kind); plugin.PluginShutdown()
            if opened: self.lib.CoreDoCommand(2,0,None)
            self.lib.CoreShutdown()

def worker(path):
    plan=json.loads(Path(path).read_text())
    try: result=Core(plan).execute()
    except Exception as e: result={'status':'failed','error':str(e)}
    Path(plan['run_dir'],'result.json').write_text(json.dumps(result,indent=2))
    return 0 if result['status']=='capture_complete' else 1

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv[:1]==['--worker']: return worker(argv[1])
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='mode',required=True)
    cap=sub.add_parser('capture',help='compatible ROM/duration/timeout capture'); cap.add_argument('positionals',nargs='*'); cap.add_argument('--state')
    rec=sub.add_parser('recipe',help='cold boot and execute JSON recipe'); rec.add_argument('recipe'); rec.add_argument('--rom',default=DEFAULT_ROM); rec.add_argument('--timeout',type=int,default=180); rec.add_argument('--state')
    for p in (cap,rec): p.add_argument('--dry-run',action='store_true')
    args=parser.parse_args(argv)
    try:
        state=None; recipe=None
        if args.mode=='capture':
            pos=list(args.positionals); rom=DEFAULT_ROM if not pos or re.fullmatch(r'[0-9]+[smhf]?',pos[0]) else pos.pop(0)
            target=duration(pos.pop(0) if pos else '2s'); timeout=int(pos.pop(0)) if pos else 30
            if pos: raise ValueError('too many positional arguments')
            state=str(Path(args.state).resolve()) if args.state else None
            events,end=[{'frame':target,'action':'capture','label':'capture'}],target+2
        else:
            state=str(Path(args.state).resolve()) if args.state else None
            rom,timeout=args.rom,args.timeout; recipe=json.loads(Path(args.recipe).read_text()); events,end=compile_recipe(recipe)
            if state and recipe.get('cold_boot_only'): raise ValueError('this recipe requires cold boot')
            if recipe.get('ready') is not True and not args.dry_run: raise ValueError('recipe is a calibration draft; verify sequence and set ready to true')
        if timeout<1: raise ValueError('timeout must be positive')
        if not rom: raise ValueError('provide a ROM path or set SSSV_ROM')
        rom=str(Path(rom).resolve())
        if not Path(rom).is_file(): raise ValueError('ROM not found: '+rom)
        if Path(rom).read_bytes()[:4]!=bytes.fromhex('80371240'): raise ValueError('expected a big-endian .z64 ROM')
        identity=validate_state(state,rom)
        plan={'version':1,'rom':rom,'rom_sha1':digest(rom),'state':state,'state_sha1':digest(state) if state else None,'state_identity':identity,'recipe':recipe,'events':events,'end_frame':end,'timeout_seconds':timeout,'frame_units':'rendered_frames','wallclock_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
        if args.dry_run: print(json.dumps(plan,indent=2)); return 0
        root=Path(os.environ.get('SSSV_TEST_DIR',ROOT)).resolve(); now=dt.datetime.now(); parent=root/'captures'/now.strftime('%Y-%m-%d'); parent.mkdir(parents=True,exist_ok=True)
        run=Path(tempfile.mkdtemp(prefix=now.strftime('%H%M%S-'),dir=parent)); plan['run_dir']=str(run); planpath=run/'plan.json'; planpath.write_text(json.dumps(plan,indent=2))
        print('ROM: '+rom+'\nRun: '+str(run),flush=True); started=time.monotonic()
        with (run/'emulator.log').open('w') as log:
            try: code=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(planpath)],stdout=log,stderr=subprocess.STDOUT,timeout=timeout).returncode
            except subprocess.TimeoutExpired: code=124
        rp=run/'result.json'; result=json.loads(rp.read_text()) if rp.exists() else {'status':'failed','error':'timeout' if code==124 else 'worker exited without result'}
        result.update({'exit_code':code,'elapsed_seconds':round(time.monotonic()-started,3),'plan':str(planpath),'log':str(run/'emulator.log')})
        if not ((code==0 and result['status']=='capture_complete') or
                (code==1 and result['status']=='capture_invalid')):
            result['status']='failed'
        if result['status'] in ('capture_complete','capture_invalid'):
            for saved in result.get('saved_states',[]):
                Path(saved+'.json').write_text(json.dumps({'rom_sha1':plan['rom_sha1'],'rom':rom,'state_sha1':digest(saved),'origin':'cold_boot' if not state else 'loaded_state','source_state':state},indent=2))
        (run/'summary.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2))
        return 0 if result['status']=='capture_complete' else 1
    except (ValueError,KeyError,OSError,TypeError,AttributeError) as e: parser.error(str(e))

if __name__=='__main__': sys.exit(main())
