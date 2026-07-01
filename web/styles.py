CSS = """
:root{
--bg:#0a0c10;--bg-2:#0f1318;--panel:#13171d;--panel-2:#191f27;
--line:#232b34;--line-2:#2e3742;--fg:#e6edf3;--mut:#8a96a4;--mut-2:#6b7682;
--acc:#6ea8fe;--acc-weak:rgba(110,168,254,.14);--acc-line:rgba(110,168,254,.35);
--ok:#3fb950;--ok-weak:rgba(63,185,80,.13);
--warn:#d6a23a;--warn-weak:rgba(214,162,58,.13);
--bad:#f0584b;--bad-weak:rgba(240,88,75,.13);
--chip:#1b222b;--r:12px;--r-sm:9px}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial;
-webkit-font-smoothing:antialiased}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
::selection{background:var(--acc-weak)}
::-webkit-scrollbar{width:11px;height:11px}
::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:8px;border:3px solid var(--bg)}
::-webkit-scrollbar-thumb:hover{background:#3a4450}

header{position:sticky;top:0;z-index:10;display:flex;gap:18px;align-items:center;
flex-wrap:wrap;padding:12px 22px;
background:rgba(13,17,23,.72);backdrop-filter:saturate(140%) blur(10px);
border-bottom:1px solid var(--line)}
header .brand{display:inline-flex;align-items:center;gap:9px;font-weight:700;
letter-spacing:.2px;font-size:15px}
header .brand::before{content:"";width:11px;height:11px;border-radius:3px;
background:linear-gradient(135deg,var(--acc),#a06bff);box-shadow:0 0 12px var(--acc-line)}
header nav{display:flex;gap:4px;flex-wrap:wrap}
header nav a{color:var(--mut);font-size:13px;padding:5px 11px;border-radius:8px;
transition:.12s}
header nav a:hover{color:var(--fg);background:var(--panel);text-decoration:none}
header nav a.on{color:var(--fg);background:var(--acc-weak);
box-shadow:inset 0 0 0 1px var(--acc-line)}

main{padding:26px 22px 40px;max-width:1240px;margin:0 auto}
h1{font-size:21px;font-weight:680;letter-spacing:-.01em;margin:0 0 18px}
h2{font-size:12px;font-weight:650;text-transform:uppercase;letter-spacing:.07em;
color:var(--mut);margin:26px 0 10px}

.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
padding:16px;margin-bottom:14px;box-shadow:0 1px 2px rgba(0,0,0,.25)}

table{width:100%;border-collapse:separate;border-spacing:0;font-size:13px}
thead th{position:sticky;top:0}
th,td{text-align:left;padding:11px 12px;border-bottom:1px solid var(--line);
vertical-align:top}
th{color:var(--mut-2);font-weight:600;font-size:11px;text-transform:uppercase;
letter-spacing:.06em}
tbody tr{transition:background .1s}
tbody tr:hover td{background:var(--panel-2)}
tbody tr:last-child td{border-bottom:0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}

.chip{display:inline-flex;align-items:center;padding:2px 9px;border-radius:999px;
background:var(--chip);font-size:12px;color:var(--mut);
box-shadow:inset 0 0 0 1px var(--line)}
.v-can,.v-relevant,.v-ok,.v-done{color:var(--ok)}
.v-partial,.v-gray,.v-needs_review{color:var(--warn)}
.v-cannot,.v-out,.v-failed,.v-error{color:var(--bad)}
.chip.v-ok{background:var(--ok-weak);color:var(--ok);box-shadow:inset 0 0 0 1px rgba(63,185,80,.3)}
.mut{color:var(--mut)}.r{text-align:right}.nowrap{white-space:nowrap}
.rank{font-weight:700;color:var(--acc)}

textarea,input[type=text],input[type=password],input[type=number],select{
background:var(--bg-2);color:var(--fg);border:1px solid var(--line);
border-radius:var(--r-sm);padding:9px 11px;font-size:13px;width:100%;
transition:border-color .12s,box-shadow .12s;outline:none}
textarea{min-height:300px;font-family:ui-monospace,Menlo,monospace;resize:vertical}
input::placeholder,textarea::placeholder{color:var(--mut-2)}
textarea:focus,input:focus,select:focus{border-color:var(--acc);
box-shadow:0 0 0 3px var(--acc-weak)}
input[type=number]{-moz-appearance:textfield}

button{background:var(--acc);color:#08111f;border:0;border-radius:var(--r-sm);
padding:8px 15px;font-size:13px;font-weight:650;cursor:pointer;
transition:filter .12s,background .12s,box-shadow .12s;white-space:nowrap}
button:hover{filter:brightness(1.08)}
button:active{filter:brightness(.95)}
button:focus-visible{box-shadow:0 0 0 3px var(--acc-weak)}
button.ghost{background:var(--chip);color:var(--fg);box-shadow:inset 0 0 0 1px var(--line)}
button.ghost:hover{background:var(--panel-2);filter:none}
button.danger{background:var(--bad-weak);color:var(--bad);
box-shadow:inset 0 0 0 1px rgba(240,88,75,.3)}
button.danger:hover{background:rgba(240,88,75,.2);filter:none}

.err,.ok{border-radius:var(--r-sm);padding:11px 13px;margin:10px 0;font-size:13px}
.err{color:#ffd7d2;background:var(--bad-weak);border:1px solid rgba(240,88,75,.35)}
.ok{color:#bdf0c8;background:var(--ok-weak);border:1px solid rgba(63,185,80,.32)}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.gaps{color:var(--warn);font-size:12px;margin-top:3px}
.empty{color:var(--mut);padding:30px;text-align:center}

.kv{display:grid;grid-template-columns:150px 1fr;gap:8px 16px;font-size:13px}
.kv .k{color:var(--mut)}

.help{display:inline-flex;align-items:center;justify-content:center;width:16px;
height:16px;border-radius:50%;background:var(--chip);color:var(--mut);font-size:11px;
font-weight:700;cursor:help;margin-left:7px;box-shadow:inset 0 0 0 1px var(--line)}
.help:hover{background:var(--acc);color:#08111f;box-shadow:none}
.hint{color:var(--mut);font-size:12px;margin:9px 0 0}

.switch{position:relative;display:inline-block;width:42px;height:24px;flex:none}
.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;inset:0;background:var(--chip);border:1px solid var(--line);
border-radius:24px;transition:.16s;cursor:pointer}
.slider:before{content:"";position:absolute;height:16px;width:16px;left:3px;top:3px;
background:var(--mut);border-radius:50%;transition:.16s}
.switch input:checked + .slider{background:var(--ok);border-color:transparent}
.switch input:checked + .slider:before{transform:translateX(18px);background:#08130c}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;
vertical-align:middle}
.dot.on{background:var(--ok);box-shadow:0 0 8px rgba(63,185,80,.6)}
.dot.off{background:var(--mut);opacity:.5}
.numfield{max-width:200px}

footer{color:var(--mut-2);font-size:12px;padding:26px 22px;text-align:center;
border-top:1px solid var(--line);margin-top:20px}
"""
