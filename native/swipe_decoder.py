"""SHARK2-style swipe decoder ported from maloocas/Gaize:swipe-keyboard."""

from __future__ import annotations

import math


SAMPLE_COUNT=40


def _resample(points,count=SAMPLE_COUNT):
    if not points: return []
    if len(points)==1: return [points[0]]*count
    total=sum(math.dist(points[i-1],points[i]) for i in range(1,len(points)))
    if not total: return [points[0]]*count
    step=total/(count-1); output=[points[0]]; accumulated=0.0; previous=points[0]
    for current in points[1:]:
        distance=math.dist(previous,current)
        while accumulated+distance>=step and len(output)<count:
            ratio=(step-accumulated)/distance
            point=(previous[0]+ratio*(current[0]-previous[0]),
                   previous[1]+ratio*(current[1]-previous[1]))
            output.append(point); previous=point
            distance=math.dist(previous,current); accumulated=0.0
        accumulated+=distance; previous=current
    return output+[points[-1]]*(count-len(output))


def _normalize(points):
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    cx=sum(xs)/len(xs); cy=sum(ys)/len(ys)
    scale=max(max(xs)-min(xs),max(ys)-min(ys)) or 1
    return [((x-cx)/scale,(y-cy)/scale) for x,y in points]


def _mean_distance(a,b):
    return sum(math.dist(x,y) for x,y in zip(a,b))/len(a)


class SwipeDecoder:
    def __init__(self,word_file):
        self.words=[]; self.frequency=[]; self.by_first={}; self.templates={}
        for line in word_file.read_text(errors="ignore").splitlines():
            parts=line.lower().split()
            if not parts or not parts[0].isalpha(): continue
            word=parts[0]; frequency=int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 1
            index=len(self.words); self.words.append(word); self.frequency.append(frequency)
            self.by_first.setdefault(word[0],[]).append(index)
        self.max_log=max(math.log(f+1) for f in self.frequency)
        self.keys={}; self.key_width=1

    def set_layout(self,centers,key_width):
        self.keys=centers; self.key_width=key_width; self.templates.clear()

    def _template(self,index):
        if index not in self.templates:
            points=[]
            for char in self.words[index]:
                if char not in self.keys: continue
                point=self.keys[char]
                if not points or points[-1]!=point: points.append(point)
            sampled=_resample(points)
            self.templates[index]=(sampled,_normalize(sampled))
        return self.templates[index]

    def decode(self,path,limit=6,radius=1.6):
        return [word for _,word in self.decode_scored(path,limit,radius)]

    def decode_scored(self,path,limit=6,radius=1.6):
        """[(cost, word)] best first; lower cost is a better match."""
        if not path or not self.keys: return []
        fixations=[]; group=None
        for x,y in path:
            if group and math.hypot(x-group[0]/group[2],y-group[1]/group[2])<.5*self.key_width:
                group=(group[0]+x,group[1]+y,group[2]+1)
            else:
                if group: fixations.append((group[0]/group[2],group[1]/group[2],group[2]))
                group=(x,y,1)
        if group: fixations.append((group[0]/group[2],group[1]/group[2],group[2]))
        sampled=_resample([(x,y) for x,y,_ in fixations]); shape=_normalize(sampled)
        start,end=sampled[0],sampled[-1]
        near=lambda p:[c for c,k in self.keys.items() if math.dist(k,p)<=radius*self.key_width]
        endings=set(near(end)); pause_n=max(4,2*(len(path)/len(fixations)))
        pauses=[f for f in fixations[1:-1] if f[2]>=pause_n]
        results=[]
        for first in near(start):
            for index in self.by_first.get(first,[]):
                word=self.words[index]
                if word[-1] not in endings or any(c not in self.keys for c in word): continue
                location,template_shape=self._template(index)
                cost=_mean_distance(sampled,location)/self.key_width+2*_mean_distance(shape,template_shape)
                cost+=.5*(math.dist(self.keys[word[0]],start)+math.dist(self.keys[word[-1]],end))/self.key_width
                for px,py,_ in pauses:
                    best=min(math.dist(self.keys[c],(px,py)) for c in word)
                    cost+=max(0,best/self.key_width-.5)/len(pauses)
                cost+=.15*(self.max_log-math.log(self.frequency[index]+1))
                results.append((cost,word))
        return sorted(results)[:limit]
