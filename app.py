import os, secrets, hashlib, hmac, json
from datetime import datetime, date
from typing import Optional
import chess
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, String, Integer, Date, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BASE_DIR=os.path.dirname(os.path.abspath(__file__)); STATIC_DIR=os.path.join(BASE_DIR,'static')
DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///'+os.path.join(BASE_DIR,'chess_arcade.db'))
if DATABASE_URL.startswith('postgres://'): DATABASE_URL=DATABASE_URL.replace('postgres://','postgresql+psycopg://',1)
if DATABASE_URL.startswith('postgresql://'): DATABASE_URL=DATABASE_URL.replace('postgresql://','postgresql+psycopg://',1)
engine=create_engine(DATABASE_URL,pool_pre_ping=True,connect_args={'check_same_thread':False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal=sessionmaker(bind=engine,expire_on_commit=False)
class Base(DeclarativeBase): pass
class Player(Base):
    __tablename__='players'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    name:Mapped[str]=mapped_column(String(80)); email:Mapped[str]=mapped_column(String(255),unique=True,index=True)
    password_hash:Mapped[str]=mapped_column(String(255)); birth_date:Mapped[date]=mapped_column(Date)
    coins:Mapped[int]=mapped_column(Integer,default=0); games_played:Mapped[int]=mapped_column(Integer,default=0)
    wins:Mapped[int]=mapped_column(Integer,default=0); losses:Mapped[int]=mapped_column(Integer,default=0); draws:Mapped[int]=mapped_column(Integer,default=0)
    unlocked_boards:Mapped[str]=mapped_column(Text,default='["Classic"]'); selected_board:Mapped[str]=mapped_column(String(40),default='Classic')
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class LoginSession(Base):
    __tablename__='sessions'; token:Mapped[str]=mapped_column(String(128),primary_key=True); player_id:Mapped[int]=mapped_column(Integer,index=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
Base.metadata.create_all(engine)
app=FastAPI(title='Chess Arcade'); app.mount('/static',StaticFiles(directory=STATIC_DIR),name='static')
class Register(BaseModel): name:str=Field(min_length=1,max_length=80); email:EmailStr; password:str=Field(min_length=8,max_length=128); birth_date:date
class Login(BaseModel): email:EmailStr; password:str
class BoardPick(BaseModel): board:str
class Purchase(BaseModel): board:str
THEMES={'Classic':0,'Midnight':50,'Emerald':100,'Royal':150}

def hp(p):
    salt=secrets.token_bytes(16); d=hashlib.pbkdf2_hmac('sha256',p.encode(),salt,240000); return f'pbkdf2$240000${salt.hex()}${d.hex()}'
def vp(p,s):
    try:
        _,r,sh,dh=s.split('$'); d=hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(sh),int(r)); return hmac.compare_digest(d.hex(),dh)
    except Exception:return False
def pub(p): return {'id':p.id,'name':p.name,'email':p.email,'birth_date':p.birth_date.isoformat(),'coins':p.coins,'games_played':p.games_played,'wins':p.wins,'losses':p.losses,'draws':p.draws,'unlocked_boards':json.loads(p.unlocked_boards or '["Classic"]'),'selected_board':p.selected_board}
def player_from_auth(auth):
    if not auth or not auth.lower().startswith('bearer '): raise HTTPException(401,'Login required.')
    with SessionLocal() as db:
        s=db.get(LoginSession,auth.split(' ',1)[1].strip())
        if not s: raise HTTPException(401,'Session expired.')
        p=db.get(Player,s.player_id)
        if not p: raise HTTPException(401,'Player not found.')
        return p
@app.get('/')
def home(): return FileResponse(os.path.join(STATIC_DIR,'index.html'))
@app.post('/api/register')
def register(x:Register):
    if x.birth_date>date.today(): raise HTTPException(400,'Birth date cannot be in the future.')
    with SessionLocal() as db:
        email=x.email.lower().strip()
        if db.query(Player).filter(Player.email==email).first(): raise HTTPException(409,'An account with this email already exists.')
        p=Player(name=x.name.strip(),email=email,password_hash=hp(x.password),birth_date=x.birth_date); db.add(p); db.commit(); db.refresh(p)
        t=secrets.token_urlsafe(48); db.add(LoginSession(token=t,player_id=p.id)); db.commit(); return {'token':t,'player':pub(p)}
@app.post('/api/login')
def login(x:Login):
    with SessionLocal() as db:
        p=db.query(Player).filter(Player.email==x.email.lower().strip()).first()
        if not p or not vp(x.password,p.password_hash): raise HTTPException(401,'Incorrect email or password.')
        t=secrets.token_urlsafe(48); db.add(LoginSession(token=t,player_id=p.id)); db.commit(); return {'token':t,'player':pub(p)}
@app.post('/api/logout')
def logout(authorization:Optional[str]=Header(None)):
    if authorization and authorization.lower().startswith('bearer '):
        with SessionLocal() as db:
            s=db.get(LoginSession,authorization.split(' ',1)[1].strip())
            if s: db.delete(s); db.commit()
    return {'ok':True}
@app.get('/api/me')
def me(authorization:Optional[str]=Header(None)): return pub(player_from_auth(authorization))
@app.post('/api/profile/board')
def select_board(x:BoardPick,authorization:Optional[str]=Header(None)):
    p=player_from_auth(authorization)
    with SessionLocal() as db:
        q=db.get(Player,p.id); owned=json.loads(q.unlocked_boards or '["Classic"]')
        if x.board not in owned: raise HTTPException(403,'Board is not unlocked.')
        q.selected_board=x.board; db.commit(); return pub(q)
@app.post('/api/profile/purchase')
def purchase(x:Purchase,authorization:Optional[str]=Header(None)):
    p=player_from_auth(authorization)
    if x.board not in THEMES: raise HTTPException(400,'Unknown board.')
    with SessionLocal() as db:
        q=db.get(Player,p.id); owned=json.loads(q.unlocked_boards or '["Classic"]')
        if x.board in owned: q.selected_board=x.board
        else:
            price=THEMES[x.board]
            if q.coins<price: raise HTTPException(400,'Not enough coins.')
            q.coins-=price; owned.append(x.board); q.unlocked_boards=json.dumps(owned); q.selected_board=x.board
        db.commit(); return pub(q)
@app.post('/api/reward')
def reward(result:str,authorization:Optional[str]=Header(None)):
    p=player_from_auth(authorization)
    if result not in {'win','loss','draw'}: raise HTTPException(400,'Invalid result.')
    with SessionLocal() as db:
        q=db.get(Player,p.id); q.games_played+=1
        if result=='win': q.wins+=1; q.coins+=20
        elif result=='loss': q.losses+=1
        else: q.draws+=1; q.coins+=5
        db.commit(); return {'player':pub(q)}

waiting=[]; matches={}
def pref_ok(a,b): return (a in ('random','white') and b in ('random','black')) or (a in ('random','black') and b in ('random','white'))
def colors(a,b):
    if a=='white': return 'white','black'
    if a=='black': return 'black','white'
    if b=='white': return 'black','white'
    if b=='black': return 'white','black'
    return ('white','black') if secrets.randbelow(2)==0 else ('black','white')
async def wsmsg(ws,x):
    try: await ws.send_json(x)
    except: pass
async def remove(ws):
    waiting[:]=[x for x in waiting if x['ws'] is not ws]; m=matches.pop(ws,None)
    if m:
        for o in list(m['players']):
            matches.pop(o,None)
            if o is not ws: await wsmsg(o,{'type':'opponent_left'})
@app.websocket('/ws')
async def ws(ws:WebSocket):
    await ws.accept()
    try:
        while True:
            m=await ws.receive_json(); typ=m.get('type')
            if typ=='join':
                name=str(m.get('name','Player'))[:40] or 'Player'; pref=m.get('preference','random')
                found=next((x for x in waiting if pref_ok(x['preference'],pref)),None)
                if found:
                    waiting.remove(found); c1,c2=colors(found['preference'],pref); board=chess.Board()
                    match={'players':[found['ws'],ws],'colors':{found['ws']:c1,ws:c2},'board':board,'names':{found['ws']:found['name'],ws:name}}
                    matches[found['ws']]=match; matches[ws]=match
                    await wsmsg(found['ws'],{'type':'start','color':c1,'opponent':name}); await wsmsg(ws,{'type':'start','color':c2,'opponent':found['name']})
                else:
                    waiting.append({'ws':ws,'name':name,'preference':pref}); await wsmsg(ws,{'type':'waiting'})
            elif typ=='move':
                mth=matches.get(ws)
                if not mth: continue
                col=chess.WHITE if mth['colors'][ws]=='white' else chess.BLACK
                try: mv=chess.Move.from_uci(m.get('uci',''))
                except: await wsmsg(ws,{'type':'error','message':'Invalid move.'}); continue
                if mth['board'].turn!=col or mv not in mth['board'].legal_moves:
                    await wsmsg(ws,{'type':'error','message':'That move is not legal.'}); continue
                mth['board'].push(mv)
                for o in mth['players']:
                    if o is not ws: await wsmsg(o,{'type':'move','uci':mv.uci()})
                if mth['board'].is_game_over():
                    outcome=mth['board'].outcome(); winner='draw' if outcome.winner is None else ('white' if outcome.winner else 'black')
                    for o in mth['players']: await wsmsg(o,{'type':'result','winner':winner})
            elif typ=='leave': await remove(ws); return
    except WebSocketDisconnect: pass
    finally: await remove(ws)
