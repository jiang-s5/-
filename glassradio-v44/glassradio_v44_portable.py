#!/usr/bin/env python3
"""GlassRadio V44-compatible *new* video replay reference (not original V44 sender).

Only 8x8 binarized tiles are reconstructed bit-exactly. Occlusion masks are
synthetic retrieval-only observations, not actual inferred UI occluders.
Five-mode wire packet layout follows archived V44 independent decoder.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import random
import statistics
import time
from collections import OrderedDict, defaultdict
from pathlib import Path

MASK64=(1<<64)-1
NWRITE=65535
METHODS=('full_lru','recent16_lru','recent256_lru','exact_lru','bs1_lru','bs2_lru','cascade_lru','full_sieve','full_gds')


def nbytes(d:bytes)->int: return len(d)

def word_from_tile(tile):
    value=0
    for v in tile.flatten().tolist(): value=(value<<1)|int(v>=128)
    return value


def make_packet(target:int, ref_slot:int|None, ref:int|None, write:int=NWRITE):
    """Return shortest wire-valid RAW/COPY/BIT/BYTE/RUN packet; deterministic ties."""
    assert 0<=target<=MASK64 and 0<=write<=NWRITE
    tail=write.to_bytes(2,'little')
    choices=[(b'\x00'+target.to_bytes(8,'big')+tail, 'RAW')]
    if ref_slot is not None and ref is not None:
        assert 0 <= ref_slot < NWRITE
        head=ref_slot.to_bytes(2,'little')
        delta=target^ref
        if delta==0: choices.append((b'\x01'+head+tail,'COPY'))
        positions=[i for i in range(64) if (delta>>(63-i))&1]
        if len(positions)<=64:
            choices.append((b'\x02'+head+bytes([len(positions)])+bytes(positions)+tail,'BIT'))
        by=delta.to_bytes(8,'big')
        changed=[i for i,b in enumerate(by) if b]
        bits=sum(1<<(7-i) for i in changed)
        choices.append((b'\x03'+head+bytes([bits])+bytes(by[i] for i in changed)+tail,'BYTE'))
        if changed:
            st,en=min(changed),max(changed)+1
            choices.append((b'\x04'+head+bytes([st,en-st])+by[st:en]+tail,'RUN'))
    data,mode=min(choices,key=lambda pair:(len(pair[0]),('COPY','BIT','BYTE','RUN','RAW').index(pair[1])))
    return data,mode


def independent_decode(data:bytes, cache:dict[int,int])->int:
    """Independent, strict receiver; no sender codec helpers called."""
    if len(data)<3: raise ValueError('truncated packet')
    op=data[0]; write=int.from_bytes(data[-2:],'little')
    if op==0:
        if len(data)!=11: raise ValueError('RAW length')
        value=int.from_bytes(data[1:9],'big')
    else:
        if len(data)<5: raise ValueError('header')
        sid=int.from_bytes(data[1:3],'little')
        if sid not in cache: raise ValueError('unknown reference')
        value=cache[sid]
        if op==1:
            if len(data)!=5: raise ValueError('COPY length')
        elif op==2:
            n=data[3]; pos=data[4:-2]
            if len(data)!=6+n or len(set(pos))!=len(pos) or any(x>=64 for x in pos): raise ValueError('BIT payload')
            for p in pos: value^=1<<(63-p)
        elif op==3:
            mask=data[3]; raw=data[4:-2]
            if len(data)!=6+mask.bit_count(): raise ValueError('BYTE payload')
            j=0
            for i in range(8):
                if mask&(1<<(7-i)):
                    value ^= raw[j] << (8*(7-i)); j+=1
        elif op==4:
            if len(data)<7: raise ValueError('RUN header')
            st,n=data[3:5]
            if n<1 or st+n>8 or len(data)!=7+n: raise ValueError('RUN payload')
            for i,b in enumerate(data[5:-2]): value^=b<<(8*(7-st-i))
        else: raise ValueError('invalid opcode')
    if write!=NWRITE: cache[write]=value
    return value


class ReplayCache:
    def __init__(self, k:int, eviction:str, index_mode:str="none"):
        if not 1<=k<=NWRITE: raise ValueError('K must be 1..65535 (0xFFFF reserved)')
        self.k=k; self.eviction=eviction; self.index_mode=index_mode; self.values={};self.use=OrderedDict(); self.nextslot=0
        self.visited={};self.hand=0;self.gds_priority={};self.gds_L=0.0
        self.postings=defaultdict(set);self.by_value=defaultdict(set)
        self.index_cpu_ns=0;self.postings_visited=0
    def _index_change(self,slot,value,adding):
        if self.index_mode=="none":return
        t=time.process_time_ns()
        fn='add' if adding else 'discard'
        if self.index_mode=="exact":getattr(self.by_value[value],fn)(slot)
        elif self.index_mode=="bits":
            for p in range(64):
                getattr(self.postings[(p, (value>>(63-p))&1)],fn)(slot)
        self.index_cpu_ns+=time.process_time_ns()-t
    def touch(self,sid):
        if sid in self.use:self.use.move_to_end(sid)
        if self.eviction=='sieve':self.visited[sid]=True
    def recent(self,n): return list(reversed(self.use))[:n]
    def _victim(self):
        if self.eviction=='lru': return next(iter(self.use))
        if self.eviction=='sieve':
            for _ in range(2*self.k+2):
                sid=self.hand%self.k;self.hand=(self.hand+1)%self.k
                if sid not in self.values:continue
                if self.visited.get(sid,False):self.visited[sid]=False
                else:return sid
            return next(iter(self.use))
        if self.eviction=='gds':
            s=min(self.gds_priority,key=lambda i:(self.gds_priority[i],i));self.gds_L=self.gds_priority[s];return s
        raise ValueError(self.eviction)
    def choose_slot(self):
        return self.nextslot if len(self.values)<self.k else self._victim()
    def write(self,sid,val,last_packet_bytes):
        if sid in self.values:
            old=self.values[sid];self._index_change(sid,old,False)
            self.use.pop(sid,None)
        else:self.nextslot+=1
        self.values[sid]=val;self.use[sid]=None;self.visited[sid]=False
        self._index_change(sid,val,True)
        # Explicit GDS approximation: object score = last wire bytes / 8-byte object.
        # Not asserted byte-for-byte compatible with the historical V44 implementation.
        self.gds_priority[sid]=self.gds_L+last_packet_bytes/8
    def candidates(self,method,observed,visible):
        if method.startswith('recent16'):return self.recent(16),0
        if method.startswith('recent256'):return self.recent(256),0
        if method.startswith('exact'):
            if visible != MASK64:return [],0
            return sorted(self.by_value.get(observed,())),0
        if method.startswith('full'):return list(self.values),0
        if method.startswith('cascade'):
            # Stage 1: only recency candidates. Search decision is made on wire length.
            return self.recent(64),0
        if method.startswith(('bs1','bs2')):
            positions=[p for p in range(64) if (visible>>(63-p))&1]
            if len(positions)<5:return self.recent(16),0
            groups=[positions[:5]]
            if method.startswith('bs2') and len(positions)>=10:groups.append(positions[5:10])
            ids=set();visits=0
            for group in groups:
                lists=[self.postings.get((p,(observed>>(63-p))&1),set()) for p in group]
                visits+=sum(len(x) for x in lists)
                ids.update(set.intersection(*map(set,lists)))
            self.postings_visited+=visits
            return sorted(ids),visits
        raise ValueError(method)


def mask_for(target:int,mode:str,rng:random.Random):
    if mode=='full':return MASK64
    if mode=='random':
        vis=0
        for p in range(64):
            if rng.random()<0.65:vis|=1<<(63-p)
        return vis
    if mode=='block':
        start=rng.randrange(48); width=16
        return MASK64 ^ (((1<<width)-1) << (64-start-width))
    raise ValueError(mode)


def replay_trace(records, method:str,k:int, write_every:int=2, receiver_work_limit:int=960, max_writes:int=6):
    ev='sieve' if method.endswith('sieve') else 'gds' if method.endswith('gds') else 'lru'
    idxmode=('exact' if method.startswith('exact') else 'bits' if method.startswith(('bs1','bs2')) else 'none')
    ca=ReplayCache(k,ev,idxmode);rc={}; history=[];tx=0;cpu=[];viol=0;writes_total=0;errors=0;postings_total=0
    work_window=writes_window=0;step_window=0
    for t,(target,observed,visible,meta) in enumerate(records):
        begin=time.process_time_ns()
        ids,postings=ca.candidates(method,observed,visible)
        postings_total+=postings
        ranked=sorted(ids,key=lambda i:(((ca.values[i]^observed)&visible).bit_count(),i))[:2]
        candidates=[(None,None)]+[(i,ca.values[i]) for i in ranked]
        write_ok=(t%write_every==0) and (writes_window<max_writes)
        slot=ca.choose_slot() if write_ok else NWRITE
        pairs=[]
        for i,val in candidates:
            pkt,mode=make_packet(target,i,val,slot)
            pairs.append((len(pkt),pkt,mode,i))
        _,pkt,mode,refid=min(pairs,key=lambda x:(x[0],x[2],x[3] if x[3] is not None else -1))
        if method.startswith('cascade') and len(pkt)>10:
            # Full scan only when recent reference cannot yield a <=10B packet.
            ids=list(ca.values)
            ranked=sorted(ids,key=lambda i:(((ca.values[i]^observed)&visible).bit_count(),i))[:2]
            pairs=[]
            for i in ranked:
                p,m=make_packet(target,i,ca.values[i],slot)
                pairs.append((len(p),p,m,i))
            pairs.append((len(pkt),pkt,mode,refid))
            _,pkt,mode,refid=min(pairs,key=lambda x:(x[0],x[2],x[3] if x[3] is not None else -1))
        decoded=independent_decode(pkt,rc)
        if decoded!=target:errors+=1
        if refid is not None:ca.touch(refid)
        if slot!=NWRITE:
            ca.write(slot,target,len(pkt));writes_window+=1;writes_total+=1
        work={0:8,1:2,2:8,3:8,4:8}[pkt[0]]+(64 if slot!=NWRITE else 0)
        work_window+=work
        tx+=len(pkt)+10 # modeled frame/tile/packet-length header (4+2+2+2 bytes)
        cpun=time.process_time_ns()-begin
        cpu.append(cpun/1000)
        history.append({'update':t,'packet_bytes':len(pkt),'framing_bytes':10,'total_transport_bytes':len(pkt)+10,'wire_mode':mode,'reference_slot':refid if refid is not None else '',
                        'write_slot':slot if slot!=NWRITE else '', 'cpu_us':round(cpun/1000,4),
                        'receiver_work_proxy':work,'postings_visits':postings,'index_maintenance_cpu_us':round(ca.index_cpu_ns/1000,4),
                        'lossless':int(decoded==target),'frame':meta['frame'],'tile_row':meta['row'],'tile_col':meta['col']})
        step_window+=1
        if step_window==12:
            viol+=int(work_window>receiver_work_limit)+int(writes_window>max_writes)
            step_window=work_window=writes_window=0
    if step_window:viol+=int(work_window>receiver_work_limit)+int(writes_window>max_writes)
    scpu=sorted(cpu); p99=scpu[min(len(scpu)-1,max(0,int(0.99*len(scpu))))] if scpu else 0
    summary={'method':method,'k':k,'updates':len(records),'bytes':tx,'byte_accounting':'wire_packet_plus_10B_modeled_video_header','bytes_per_update':tx/max(1,len(records)),
             'sender_cpu_total_us':round(sum(cpu),3),'sender_cpu_p99_us':round(p99,4),
             'write_count':writes_total,'lossless_errors':errors,'receiver_budget_violations':viol,
             'postings_visited':postings_total,'index_cpu_total_us':round(ca.index_cpu_ns/1000,3)}
    return summary,history


def extract_video(path:Path,size=(256,144),stride=15,max_frames=240,threshold=128):
    """Make chronological changed 8x8 *binary* tiles from real pixels."""
    try:import cv2
    except ImportError as e:raise SystemExit('pip install opencv-python-headless') from e
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened():raise ValueError(f'cannot open video: {path}')
    width,height=size
    if width%8 or height%8:raise ValueError('dimensions must be multiples of 8')
    frame=selected=0;last=None;updates=[]
    while selected<max_frames:
        ok,img=cap.read()
        if not ok:break
        if frame%stride:
            frame+=1;continue
        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        gray=cv2.resize(gray,(width,height),interpolation=cv2.INTER_AREA)
        binary=(gray>=threshold).astype('uint8')*255
        for r in range(0,height,8):
            for c in range(0,width,8):
                curr=word_from_tile(binary[r:r+8,c:c+8]);prev=None if last is None else word_from_tile(last[r:r+8,c:c+8])
                if curr!=prev:updates.append((curr,{'frame':frame,'row':r//8,'col':c//8}))
        last=binary;selected+=1;frame+=1
    cap.release()
    return updates,selected


def make_records(updates,mode,seed):
    rng=random.Random(seed)
    return [(v,v&(mask:=mask_for(v,mode,rng)),mask,meta) for v,meta in updates]


def _write_csv(path,rows):
    if not rows:return
    with open(path,'w',newline='',encoding='utf8') as f:
        out=csv.DictWriter(f,fieldnames=list(rows[0]));out.writeheader();out.writerows(rows)


def run(cfg,inputs,output):
    output.mkdir(parents=True,exist_ok=True)
    manifest=[];summary=[];per_update=[]
    for video in sorted(inputs):
        video=Path(video); digest=hashlib.sha256(video.read_bytes()).hexdigest();sid=digest[:12]
        updates,frames=extract_video(video,tuple(cfg['video_size']),cfg['frame_stride'],cfg['max_frames'],cfg['binarize_threshold'])
        manifest.append({'session':sid,'filename':video.name,'sha256':digest,'selected_frames':frames,'changed_tiles':len(updates),'source':'real video -> binarized 8x8 tiles'})
        for mask_mode in cfg['observation_modes']:
            stable_seed=int(hashlib.sha256(f'{cfg["seed"]}:{sid}:{mask_mode}'.encode()).hexdigest()[:12],16)
            records=make_records(updates,mask_mode,stable_seed)
            for method in cfg['methods']:
                for k in cfg['cache_slots']:
                    s,h=replay_trace(records,method,k,cfg['write_every'],cfg['receiver_work_per_12'],cfg['max_writes_per_12'])
                    s.update(session=sid,observation=mask_mode,source_video=video.name,source_sha256=digest)
                    summary.append(s)
                    for row in h:row.update(session=sid,observation=mask_mode,method=method,k=k)
                    per_update.extend(h)
    _write_csv(output/'v44_video_results.csv',summary)
    _write_csv(output/'v44_video_updates.csv',per_update)
    _write_csv(output/'session_manifest.csv',manifest)
    (output/'config_used.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
    result={'sessions':len(manifest),'comparisons':len(summary),'all_lossless':all(r['lossless_errors']==0 for r in summary),
            'all_receiver_budgets_met':all(r['receiver_budget_violations']==0 for r in summary)}
    (output/'verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if not result['all_lossless'] or not result['all_receiver_budgets_met']:raise RuntimeError('failed invariant')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='video_config.json');p.add_argument('--videos',nargs='+',required=True)
    p.add_argument('--out',default='runs/video_experiment')
    a=p.parse_args();cfg=json.loads(Path(a.config).read_text())
    if any(m not in METHODS for m in cfg['methods']):raise ValueError('unknown method')
    run(cfg,[Path(x) for x in a.videos],Path(a.out))
if __name__=='__main__':main()