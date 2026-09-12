"""Rebuild data/corpus.txt, the offline generator's language-model source.

Run once; the output is committed. Needs OPENROUTER_API_KEY.

    PYTHONPATH=. ./.venv/bin/python scripts/build_corpus.py

The corpus is short, spoken, first-person utterances of the kind an AAC user
actually produces. Bigram statistics over it are what let the offline beam
search produce "I need some water" rather than a grammatical-but-alien string.
"""
import asyncio, os, httpx, re
from server.config import settings

THEMES = [
 "physical comfort and repositioning (pain, turning, cushions, sitting up)",
 "basic needs (water, food, bathroom, temperature, blankets)",
 "medical and care (nurse, doctor, medication, appointments, therapy, how they feel)",
 "family and visitors (asking for people, missing people, arranging visits)",
 "everyday social replies (yes/no, thanks, agreement, disagreement, small talk)",
 "emotions and states (tired, frustrated, happy, bored, scared, content)",
 "entertainment and interests (TV, baseball, books, music, outside, weather)",
 "technology and the device itself (screen, volume, slow down, start over, mistakes)",
 "time and planning (later, tomorrow, now, wait, soon, how long)",
 "questions they ask other people (how are you, what happened, where is, did you)",
]

PROMPT = ("Write {n} short sentences that an adult using a speech-generating "
 "communication device would realistically say out loud, on the theme of: {theme}.\n"
 "Rules: 3 to 8 words each. First person where natural. Plain spoken English, "
 "the way people actually talk. No numbering, no quotes, no commentary. "
 "One sentence per line. Vary the sentence openings a lot.")

async def one(client, theme, n=60):
    r = await client.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.openrouter_key}",
                 "Content-Type":"application/json"},
        json={"model": settings.openrouter_model,
              "messages":[{"role":"user","content":PROMPT.format(n=n, theme=theme)}],
              "max_tokens":1600,"temperature":1.0})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

CLEAN = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

async def main():
    lines=[]
    async with httpx.AsyncClient(timeout=90) as c:
        results = await asyncio.gather(*[one(c,t) for t in THEMES], return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            print("theme failed:", res); continue
        for ln in res.splitlines():
            ln = CLEAN.sub("", ln.strip()).strip().strip('"').strip()
            if not ln or ln.endswith(":") or len(ln.split())<2 or len(ln.split())>10:
                continue
            lines.append(ln)
    seen=set(); out=[]
    for ln in lines:
        k=re.sub(r"[^a-z ]","",ln.lower()).strip()
        if k in seen: continue
        seen.add(k); out.append(ln)
    open("data/corpus.txt","w").write("\n".join(out)+"\n")
    print(f"wrote data/corpus.txt: {len(out)} sentences")
    print("sample:"); [print("  ",s) for s in out[:8]]

asyncio.run(main())
