import cv2, numpy as np, threading, time, sqlite3, smtplib, random, urllib.request, json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, Response, jsonify, render_template, request
from ultralytics import YOLO

app = Flask(__name__)

EMAIL_SENDER    = "tejaswini.02.2005@gmail.com"
EMAIL_PASSWORD  = "joqx xscl douo zirn"
EMAIL_RECIPIENT = "tejumk0297@gmail.com"
ALERT_THRESHOLD = 2
ALERT_COOLDOWN  = 60
MODEL_PATH      = "yolov8n.pt"
DB_PATH         = "crowd.db"
LOG_EVERY_SEC   = 60

TARGET = {0:"Person", 2:"Car", 3:"Motorcycle", 5:"Bus", 7:"Truck"}

frame_lock     = threading.Lock()
latest_frame   = None
latest_heatmap = None
state = {"persons":0,"vehicles":0,"total":0,"fps":0,"last_alert":0,"running":False,"cam_ok":True}
history        = []
_hist_buf      = []
_hist_last_sec = ""

# ── Location (fetched once at startup via IP geolocation) ─────────────────────
location_info = {"city":"Unknown","region":"Unknown","country":"Unknown",
                 "lat":"N/A","lon":"N/A","maps_url":"#"}

def fetch_location():
    """Get approximate location from IP address — no GPS hardware needed."""
    global location_info
    try:
        with urllib.request.urlopen("http://ip-api.com/json/?fields=city,regionName,country,lat,lon", timeout=5) as r:
            d = json.loads(r.read().decode())
        location_info = {
            "city":     d.get("city","Unknown"),
            "region":   d.get("regionName","Unknown"),
            "country":  d.get("country","Unknown"),
            "lat":      d.get("lat","N/A"),
            "lon":      d.get("lon","N/A"),
            "maps_url": f"https://www.google.com/maps?q={d.get('lat')},{d.get('lon')}"
        }
        print(f"[LOCATION] {location_info['city']}, {location_info['region']}, {location_info['country']}")
    except Exception as e:
        print(f"[LOCATION] Could not fetch: {e}")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def init_db():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS log(
        id INTEGER PRIMARY KEY, ts TEXT, hour INTEGER,
        persons INTEGER, vehicles INTEGER, total INTEGER)""")
    conn.commit(); conn.close()

def db_insert(p,v,t):
    now=datetime.now(); conn=get_conn(); cur=conn.cursor()
    cur.execute("INSERT INTO log(ts,hour,persons,vehicles,total) VALUES(?,?,?,?,?)",
                (now.isoformat(),now.hour,p,v,t))
    conn.commit(); conn.close()

def db_hourly():
    today=datetime.now().date().isoformat(); conn=get_conn(); cur=conn.cursor()
    cur.execute("""SELECT hour,AVG(persons),AVG(vehicles),AVG(total),MAX(total)
        FROM log WHERE ts LIKE ? GROUP BY hour ORDER BY hour""",(f"{today}%",))
    rows=cur.fetchall(); conn.close(); return rows

def db_periods():
    today=datetime.now().date().isoformat(); conn=get_conn(); cur=conn.cursor()
    out={}
    defs={"Morning":"hour BETWEEN 6 AND 11","Afternoon":"hour BETWEEN 12 AND 16",
          "Evening":"hour BETWEEN 17 AND 20","Night":"hour NOT BETWEEN 6 AND 20"}
    for label,cond in defs.items():
        cur.execute(f"SELECT AVG(persons),AVG(vehicles),MAX(total),COUNT(*) FROM log WHERE ts LIKE ? AND {cond}",(f"{today}%",))
        r=cur.fetchone()
        out[label]={"avg_p":round(r[0] or 0,1),"avg_v":round(r[1] or 0,1),"peak":r[2] or 0,"samples":r[3] or 0}
    conn.close(); return out

def db_alerts():
    conn=get_conn(); cur=conn.cursor()
    cur.execute("SELECT ts,persons,vehicles,total FROM log WHERE total>=? ORDER BY id DESC LIMIT 30",(ALERT_THRESHOLD,))
    rows=cur.fetchall(); conn.close()
    return [{"ts":r[0][:19].replace("T"," "),"persons":r[1],"vehicles":r[2],"total":r[3]} for r in rows]

def db_last7():
    conn=get_conn(); cur=conn.cursor()
    cur.execute("SELECT substr(ts,1,10),AVG(persons),AVG(vehicles),MAX(total) FROM log GROUP BY substr(ts,1,10) ORDER BY substr(ts,1,10) DESC LIMIT 7")
    rows=cur.fetchall(); conn.close(); return list(reversed(rows))

def seed_demo_data():
    today=datetime.now().date().isoformat()
    conn=get_conn(); cur=conn.cursor()
    cur.execute("SELECT COUNT(*) FROM log WHERE ts LIKE ?",(f"{today}%",))
    count=cur.fetchone()[0]
    if count>0:
        conn.close(); print(f"[DB] {count} records exist for today, skipping seed"); return
    print("[DB] Seeding demo data...")
    pattern={0:(0,0),1:(0,0),2:(0,0),3:(0,0),4:(0,0),5:(1,0),
             6:(3,1),7:(6,2),8:(9,3),9:(11,4),10:(12,3),11:(13,4),
             12:(15,5),13:(14,4),14:(13,5),15:(12,4),16:(10,3),
             17:(8,3),18:(7,2),19:(5,2),20:(4,1),21:(3,1),22:(1,0),23:(0,0)}
    rows=[]
    for hour,(bp,bv) in pattern.items():
        if hour>datetime.now().hour: continue
        for minute in [5,20,40,55]:
            p=max(0,bp+random.randint(-1,2)); v=max(0,bv+random.randint(0,1))
            ts=datetime.now().replace(hour=hour,minute=minute,second=0,microsecond=0).isoformat()
            rows.append((ts,hour,p,v,p+v))
    cur.executemany("INSERT INTO log(ts,hour,persons,vehicles,total) VALUES(?,?,?,?,?)",rows)
    conn.commit(); conn.close()
    print(f"[DB] Seeded {len(rows)} records ✅")

def send_email_msg(subject, html_body):
    msg=MIMEMultipart("alternative")
    msg["Subject"]=subject; msg["From"]=EMAIL_SENDER; msg["To"]=EMAIL_RECIPIENT
    msg.attach(MIMEText(html_body,"html"))
    with smtplib.SMTP("smtp.gmail.com",587) as s:
        s.ehlo(); s.starttls(); s.ehlo()
        s.login(EMAIL_SENDER,EMAIL_PASSWORD)
        s.sendmail(EMAIL_SENDER,EMAIL_RECIPIENT,msg.as_string())

def send_alert(p,v,t):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        loc = location_info
        period = "Morning" if 6<=datetime.now().hour<12 else \
                 "Afternoon" if 12<=datetime.now().hour<17 else \
                 "Evening" if 17<=datetime.now().hour<21 else "Night"
        html=f"""
        <html><body style="background:#04080f;color:#d0e4f7;font-family:Arial,sans-serif;padding:24px;margin:0">
          <div style="max-width:520px;margin:auto;background:#0c1525;border-radius:16px;
                      padding:28px;border:1px solid rgba(255,59,92,0.3)">

            <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
              <div style="font-size:32px">🚨</div>
              <div>
                <h1 style="color:#ff3b5c;font-size:20px;margin:0">Crowd Alert</h1>
                <p style="color:#4d7090;font-size:12px;margin:4px 0 0">{now} &nbsp;·&nbsp; {period}</p>
              </div>
            </div>

            <!-- Counts -->
            <div style="display:flex;gap:10px;margin-bottom:20px">
              <div style="flex:1;background:#070d1a;border-radius:10px;padding:14px;text-align:center;border:1px solid rgba(255,59,92,0.2)">
                <div style="font-size:34px;font-weight:700;color:#ff3b5c">{t}</div>
                <div style="font-size:10px;color:#4d7090;margin-top:4px;letter-spacing:.1em">TOTAL</div>
              </div>
              <div style="flex:1;background:#070d1a;border-radius:10px;padding:14px;text-align:center;border:1px solid rgba(0,200,255,0.2)">
                <div style="font-size:34px;font-weight:700;color:#00c8ff">{p}</div>
                <div style="font-size:10px;color:#4d7090;margin-top:4px;letter-spacing:.1em">PERSONS</div>
              </div>
              <div style="flex:1;background:#070d1a;border-radius:10px;padding:14px;text-align:center;border:1px solid rgba(255,179,0,0.2)">
                <div style="font-size:34px;font-weight:700;color:#ffb300">{v}</div>
                <div style="font-size:10px;color:#4d7090;margin-top:4px;letter-spacing:.1em">VEHICLES</div>
              </div>
            </div>

            <!-- Location -->
            <div style="background:#070d1a;border-radius:10px;padding:16px;border:1px solid rgba(0,229,160,0.2);margin-bottom:16px">
              <div style="font-size:10px;color:#4d7090;letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px">📍 Camera Location</div>
              <div style="font-size:15px;font-weight:600;color:#00e5a0">{loc['city']}, {loc['region']}</div>
              <div style="font-size:12px;color:#4d7090;margin-top:3px">{loc['country']}</div>
              <div style="font-size:11px;color:#2a4a65;margin-top:4px;font-family:monospace">
                Lat: {loc['lat']} &nbsp; Lon: {loc['lon']}
              </div>
              <a href="{loc['maps_url']}" style="display:inline-block;margin-top:10px;padding:8px 16px;
                 background:rgba(0,229,160,0.1);border:1px solid rgba(0,229,160,0.3);
                 border-radius:6px;color:#00e5a0;text-decoration:none;font-size:12px;font-weight:600">
                🗺️ View on Google Maps
              </a>
            </div>

            <p style="font-size:11px;color:#2a4a65;margin:0">
              Alert threshold: {ALERT_THRESHOLD} person · Cooldown: {ALERT_COOLDOWN}s
            </p>
          </div>
        </body></html>"""
        send_email_msg(f"🚨 Crowd Alert — {t} objects detected at {loc['city']}",html)
        print(f"[EMAIL] Alert sent — {t} objects @ {loc['city']}")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")

def detect():
    global latest_frame,latest_heatmap,state,_hist_buf,_hist_last_sec
    print("[YOLO] Loading model...")
    model=YOLO(MODEL_PATH)
    print("[YOLO] Ready")
    cap=cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[CAM] No camera - demo mode"); state["cam_ok"]=False
    heatmap=None; last_log=time.time(); fps_t=time.time(); fps_n=0
    state["running"]=True
    while True:
        if not state["cam_ok"]:
            frame=np.zeros((480,640,3),np.uint8)
            cv2.putText(frame,"Demo Mode",(200,240),cv2.FONT_HERSHEY_SIMPLEX,1,(30,60,90),2)
        else:
            ret,frame=cap.read()
            if not ret: time.sleep(0.05); continue
        results=model(frame,verbose=False)
        annotated=results[0].plot()
        persons=vehicles=0; boxes=[]
        if results[0].boxes is not None:
            for b in results[0].boxes:
                cls=int(b.cls[0]); conf=float(b.conf[0])
                if cls in TARGET and conf>=0.35:
                    boxes.append((cls,b.xyxy[0].cpu().numpy()))
                    if cls==0: persons+=1
                    else: vehicles+=1
        total=persons+vehicles
        if heatmap is None:
            heatmap=np.zeros((frame.shape[0],frame.shape[1]),np.float32)
        heatmap*=0.93
        for _,(x1,y1,x2,y2) in boxes:
            heatmap[int(y1):int(y2),int(x1):int(x2)]+=1
        hm=cv2.normalize(heatmap,None,0,255,cv2.NORM_MINMAX).astype(np.uint8)
        hm=cv2.applyColorMap(hm,cv2.COLORMAP_JET)
        hm_blend=cv2.addWeighted(cv2.resize(frame,(heatmap.shape[1],heatmap.shape[0])),0.4,hm,0.6,0)
        fps_n+=1
        if time.time()-fps_t>=1:
            state["fps"]=fps_n; fps_n=0; fps_t=time.time()
        state.update({"persons":persons,"vehicles":vehicles,"total":total})
        now_sec=datetime.now().strftime("%H:%M:%S")
        _hist_buf.append({"p":persons,"v":vehicles,"tot":total})
        if now_sec!=_hist_last_sec:
            _hist_last_sec=now_sec
            if _hist_buf:
                avg_p=round(sum(x["p"] for x in _hist_buf)/len(_hist_buf),1)
                avg_v=round(sum(x["v"] for x in _hist_buf)/len(_hist_buf),1)
                avg_tot=round(sum(x["tot"] for x in _hist_buf)/len(_hist_buf),1)
                history.append({"t":now_sec,"p":avg_p,"v":avg_v,"tot":avg_tot})
                if len(history)>60: history.pop(0)
            _hist_buf.clear()
        now_t=time.time()
        if total>=ALERT_THRESHOLD and now_t-state["last_alert"]>ALERT_COOLDOWN:
            state["last_alert"]=now_t
            threading.Thread(target=send_alert,args=(persons,vehicles,total),daemon=True).start()
        if time.time()-last_log>=LOG_EVERY_SEC:
            db_insert(persons,vehicles,total); last_log=time.time()
        ann_r=cv2.resize(annotated,(640,480)); hm_r=cv2.resize(hm_blend,(640,480))
        with frame_lock:
            latest_frame=ann_r.copy(); latest_heatmap=hm_r.copy()
        time.sleep(0.01)

def mjpeg(get_frame):
    def gen():
        while True:
            with frame_lock: f=get_frame()
            if f is not None:
                _,buf=cv2.imencode(".jpg",f,[cv2.IMWRITE_JPEG_QUALITY,80])
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"+buf.tobytes()+b"\r\n"
            time.sleep(0.04)
    return Response(gen(),mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/")
def page_dashboard(): return render_template("index.html")
@app.route("/analytics")
def page_analytics(): return render_template("analytics.html")
@app.route("/heatmap")
def page_heatmap(): return render_template("heatmap.html")
@app.route("/alerts")
def page_alerts(): return render_template("alerts.html")
@app.route("/settings")
def page_settings(): return render_template("settings.html",threshold=ALERT_THRESHOLD,cooldown=ALERT_COOLDOWN,email=EMAIL_RECIPIENT)
@app.route("/video_feed")
def video_feed(): return mjpeg(lambda: latest_frame)
@app.route("/heatmap_feed")
def heatmap_feed(): return mjpeg(lambda: latest_heatmap)
@app.route("/api/stats")
def api_stats():
    return jsonify({**state,"timestamp":datetime.now().strftime("%H:%M:%S"),
        "alert_active":state["persons"]>=ALERT_THRESHOLD,"threshold":ALERT_THRESHOLD})
@app.route("/api/live_history")
def api_live_history(): return jsonify(history[-60:])
@app.route("/api/hourly")
def api_hourly():
    rows=db_hourly()
    return jsonify({"labels":[f"{int(r[0]):02d}:00" for r in rows],
        "persons":[round(r[1],1) for r in rows],"vehicles":[round(r[2],1) for r in rows],
        "totals":[round(r[3],1) for r in rows],"peaks":[r[4] for r in rows]})
@app.route("/api/periods")
def api_periods(): return jsonify(db_periods())
@app.route("/api/alerts")
def api_alerts(): return jsonify(db_alerts())
@app.route("/api/week")
def api_week():
    rows=db_last7()
    return jsonify({"labels":[r[0] for r in rows],"persons":[round(r[1],1) for r in rows],
        "vehicles":[round(r[2],1) for r in rows],"peaks":[r[3] for r in rows]})
@app.route("/api/settings",methods=["POST"])
def api_settings():
    global ALERT_THRESHOLD,ALERT_COOLDOWN,EMAIL_RECIPIENT
    d=request.json or {}
    if "threshold" in d: ALERT_THRESHOLD=int(d["threshold"])
    if "cooldown" in d: ALERT_COOLDOWN=int(d["cooldown"])
    if "email" in d: EMAIL_RECIPIENT=d["email"]
    return jsonify({"ok":True,"threshold":ALERT_THRESHOLD,"cooldown":ALERT_COOLDOWN,"email":EMAIL_RECIPIENT})
@app.route("/api/test_email")
def test_email():
    try:
        html=f"""<html><body style="background:#04080f;color:#d0e4f7;font-family:sans-serif;padding:30px">
          <div style="max-width:440px;margin:auto;background:#0c1525;border-radius:16px;padding:28px;border:1px solid rgba(0,229,160,0.3)">
            <h2 style="color:#00e5a0">✅ Email alerts are working!</h2>
            <p style="color:#4d7090;margin-top:12px">CrowdSense AI is correctly configured.</p>
            <p style="color:#4d7090;font-size:12px;margin-top:8px">
              📍 Location: {location_info['city']}, {location_info['region']}, {location_info['country']}
            </p>
          </div></body></html>"""
        send_email_msg("CrowdSense AI - Test Email",html)
        return jsonify({"ok":True,"message":f"Test email sent to {EMAIL_RECIPIENT}",
                        "location": location_info})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e),
            "fix":"Use Gmail APP PASSWORD not login password. Go to myaccount.google.com > Security > App Passwords"})

@app.route("/api/location")
def api_location():
    return jsonify(location_info)

if __name__=="__main__":
    init_db()
    seed_demo_data()
    print("[LOCATION] Fetching location from IP…")
    fetch_location()
    threading.Thread(target=detect,daemon=True).start()
    print("\n" + "="*52)
    print("  Dashboard  ->  http://localhost:5000")
    print("  Test Email ->  http://localhost:5000/api/test_email")
    print("  Location   ->  http://localhost:5000/api/location")
    print("="*52+"\n")
    app.run(host="0.0.0.0",port=5000,debug=False,threaded=True)