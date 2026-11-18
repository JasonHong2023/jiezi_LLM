"""add-chunk-recall 2.1：長文件問答段落召回 off／reserve／hyde 的比較（舊 16 題＋新寫 16 題）。
Usage: recall-ab.py <docs dir> <mode> <out.json>；由 recall-ab.sh 在夜間呼叫。"""
import json, sys, time, httpx
sys.path.insert(0, "src")
from jiezi import documents as D, longdoc as L
T, MODE, OUT = sys.argv[1:4]
KEY = next(l.split("=",1)[1].strip() for l in open(".env") if l.startswith("JIEZI_GATEWAY_KEY="))
labor = open(f"{T}/long.txt").read(); nhi = open(f"{T}/nhi.txt").read()
Q = [
 ("labor", "公司可以叫我連續上班超過六天嗎？", "\n第 36 條\n", ["二日", "例假", "休息日"]),
 ("labor", "我做了半年，特休假有幾天？", "\n第 38 條\n", ["三日"]),
 ("labor", "薪水一個月最少要發幾次？", "\n第 23 條\n", ["二次", "兩次"]),
 ("labor", "老闆可以叫女生上大夜班嗎？", "\n第 49 條\n", ["午後十時", "晚上十點", "22"]),
 ("labor", "工作幾年才可以自己申請退休？", "\n第 53 條\n", ["十五年", "15 年", "15年"]),
 ("labor", "公司要開除我的話，要提前多久跟我說？", "\n第 16 條\n", ["十日", "二十日", "三十日", "10 日", "10天", "十天"]),
 ("labor", "最低薪資是誰決定的？", "\n第 21 條\n", ["基本工資審議委員會", "審議委員會"]),
 ("labor", "餵母乳的時間公司要給嗎？", "\n第 52 條\n", ["三十分鐘", "30 分鐘", "哺乳時間"]),
 ("nhi", "健保剛開辦那天，大家看病要帶什麼證件？", "身分證進診間", ["身分證"]),
 ("nhi", "「四大皆空」這個詞最早是誰講的？", "2009 年夏天造", ["李玉春"]),
 ("nhi", "現在健保費率是多少？", "陳時中任內再次調回", ["5.17"]),
 ("nhi", "65 歲以上的老人用掉多少健保資源？", "65 歲以上人口用掉 39.8%", ["39.8"]),
 ("nhi", "護理師一年有多少比例離職？", "2023 年 12.61%", ["12.61"]),
 ("nhi", "哪些人其實沒被健保照顧到？", "失聯移工失去健保資格", ["移工"]),
 ("nhi", "台灣是全世界第一個用健保卡的國家嗎？", "Slovenia 在 2000 年 9 月", ["Slovenia", "斯洛維尼亞", "第二"]),
 ("nhi", "急診病人留在急診超過一天的比例有多少？", "急診病人留置超過 24 小時比率 3.68%", ["3.68"]),
 # 2026-11-18 新寫的 16 題（add-chunk-recall 2.1；寫完沒有用來調參數）
 ("labor", "一個月最多可以加班幾小時？", "\n第 32 條\n", ["四十六", "46"]),
 ("labor", "生小孩可以請幾週產假？", "\n第 50 條\n", ["八星期", "8 週", "八週", "8 星期", "8週"]),
 ("labor", "被資遣的話，可以拿到多少錢？", "\n第 17 條\n", ["一個月平均工資", "一個月"]),
 ("labor", "公司可以請國中生來打工嗎？幾歲以下不能請？", "\n第 45 條\n", ["十五歲", "15"]),
 ("labor", "一週正常要上幾個小時的班？", "\n第 30 條\n", ["四十", "40"]),
 ("labor", "上班受傷了，公司要出醫藥費嗎？", "\n第 59 條\n", ["醫療費用", "補償"]),
 ("labor", "公司可以先扣我薪水當違約金嗎？", "\n第 26 條\n", ["不得預扣", "不得", "不可以", "不能"]),
 ("labor", "國定假日叫我去上班，薪水怎麼算？", "\n第 39 條\n", ["加倍"]),
 ("nhi", "健保剛開始的時候，大家滿意嗎？", "滿意度只有 39%", ["39"]),
 ("nhi", "健保是參考哪個國家的制度設計的？", "選定加拿大式", ["加拿大"]),
 ("nhi", "健保費一開始收多少趴？", "1995 年開辦時 4.25%", ["4.25"]),
 ("nhi", "新進的護理師多快就跑掉一大部分？", "三分之一在 3 個月內離職", ["3 個月", "三個月"]),
 ("nhi", "健保資料庫被法院說有什麼問題？", "三層次違憲", ["違憲", "退出權"]),
 ("nhi", "台灣人一年平均看幾次門診？", "每年看門診 18 次", ["18"]),
 ("nhi", "住院平均要住幾天？", "急性病床平均住院天數 7.3 天", ["7.3"]),
 ("nhi", "有健保之後，大家還會買商業保險嗎？", "購買率 72.3%", ["72.3"]),
]
docs = {"labor": ("勞動基準法.txt", labor), "nhi": ("台灣醫療與全民健保.md", nhi)}
H = {"Authorization": f"Bearer {KEY}"}
with httpx.Client(timeout=600) as c:
    if True:  # 和使用者一樣：附檔就先建向量 / warm like a real attach
        for name, text in docs.values():
            c.post("http://127.0.0.1:36100/v1/documents/warm", headers=H, content=D.clean_for_attach(text).encode())
        time.sleep(1)
    rows = []
    for doc, q, mark, keys in Q:
        name, text = docs[doc]
        parts = L.chunks(D.clean_for_attach(text), L.QA_CHUNK_TOKENS)
        target = [i for i, p in enumerate(parts) if mark in ("\n" + p).replace("**", "")]
        t = time.time()
        r = c.post("http://127.0.0.1:36100/v1/chat/completions", headers=H,
                   json={"model": "jiezi-local", "messages": [{"role": "user", "content": D.attach({"name": name, "text": text}, q)}]}).json()
        dt = time.time() - t
        ans = (r.get("choices") or [{}])[0].get("message", {}).get("content", "")
        tid = r.get("jiezi", {}).get("trajectory_id")
        ld = None
        for line in open(f"var/trajectories/{time.strftime('%Y-%m-%d')}.jsonl"):
            if tid and tid in line:
                ld = json.loads(line).get("longdoc")
        sel = (ld or {}).get("selected", [{}])[0]
        rows.append({"doc": doc, "q": q, "target": target, "kept": sel.get("kept"), "ranking": sel.get("ranking"),
                     "in_context": bool(set(target) & set(sel.get("kept") or [])),
                     "correct": any(k in ans for k in keys), "seconds": round(dt, 1), "recall": sel.get("recall"), "new": len(rows) >= 16, "answer": ans[:300]})
        print(json.dumps({k: rows[-1][k] for k in ("doc", "q", "in_context", "correct", "seconds", "ranking")}, ensure_ascii=False), flush=True)
json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
for d in ("old", "new", None):
    rr = [r for r in rows if d is None or r["new"] == (d == "new")]
    print(MODE, d or "all", "in_context", sum(r["in_context"] for r in rr), "/", len(rr), "correct", sum(r["correct"] for r in rr), "/", len(rr),
          "avg s", round(sum(r["seconds"] for r in rr) / len(rr), 1))
