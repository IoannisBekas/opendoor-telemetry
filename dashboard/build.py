"""Inject the exported JSON into the dashboard template -> final HTML."""
import json, sys, pathlib

tpl = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
data = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
out = pathlib.Path(sys.argv[3])

# Trim payload: the dashboard only needs a sample of the scatter cloud.
pp = data.get("price_position") or []
if len(pp) > 1600:
    step = len(pp) / 1600
    data["price_position"] = [pp[int(i * step)] for i in range(1600)]
    data["price_position_sampled_from"] = len(pp)

blob = json.dumps(data, separators=(",", ":"))
out.write_text(tpl.replace("/*__DATA__*/null", blob), encoding="utf-8")
kb = out.stat().st_size / 1024
print(f"wrote {out}  ({kb:.0f} KB)  data={len(blob)/1024:.0f} KB")
